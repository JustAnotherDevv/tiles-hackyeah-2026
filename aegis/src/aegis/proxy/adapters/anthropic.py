"""Anthropic Messages wire adapter (`POST /v1/messages`), used by Claude Code.

Owner: core-gateway (bundle B02). Implements `aegis.core.protocols.ProviderAdapter`.

Segment conventions (CONTRACTS 3.1/3.4 + plan 01 section 2.7):

* `system` (string or text blocks) -> role `system`; **`redactable=False` for Claude Code clients**
  (attribution block / prompt-cache safety) unless the provider sets `redact_system: true`
  (the flow flips the flag);
* `messages[i].content` string or `text` blocks -> role of the message (`user` / `assistant`);
* `tool_result` blocks (string or text blocks) -> role `tool_result`, `trusted=False`;
* `tool_use.input` string leaves -> role `tool_args`;
* `thinking` -> `redactable=False` (signed); `redacted_thinking`, base64 payloads (images, PDFs),
  signatures, `cache_control`, tool definitions and `metadata` are never segments and are copied
  verbatim (`apply_segments` uses copy-on-write: untouched bytes stay identical);
* every other block (`document` incl. `source.type` text/content, `search_result`, server tool
  results, `tool_result` sub-blocks, unknown types) and every other string field -> generic
  `text_leaves` fallback, role `document`, `trusted=False` (R9: fail closed on unknown shapes).
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from typing import Any, Literal

from aegis.core.types import Interaction, TextSegment, Usage, Verdict, new_id
from aegis.proxy.adapters._common import (
    apply_segments as _apply_segments,
)
from aegis.proxy.adapters._common import (
    as_list,
    claude_code_meta,
    dumps,
    estimate_tokens,
    is_claude_code,
    opt_int,
    safe_int,
    string_leaves,
    text_leaves,
)
from aegis.proxy.adapters._common import error_body as _error_body
from aegis.proxy.blocking import block_info
from aegis.proxy.streaming import anthropic_events

__all__ = ["ADAPTERS", "AnthropicAdapter"]

_TOOL_NAME = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")
_TOOL_USE_TYPES = {"tool_use", "server_tool_use", "mcp_tool_use"}
# legacy / foreign top-level text fields a lenient upstream may still render to the model
_EXTRA_TEXT_KEYS = ("prompt", "input", "instructions")


class AnthropicAdapter:
    wire: Literal["anthropic"] = "anthropic"

    # ------------------------------------------------------------------ blocks
    @staticmethod
    def _blocks(segs: list[TextSegment], blocks: list[Any], base: str, role: str,
                trusted: bool = True) -> None:
        """Segments for a content-block list. Known types map to their specific roles; every
        other block (document, search_result, image, server tool results, unknown types) falls
        back to `text_leaves` (R9: inspect everything model-visible, never skip silently)."""
        for j, b in enumerate(blocks):
            p = f"{base}[{j}]"
            if isinstance(b, str):
                if b:
                    segs.append(TextSegment(path=p, text=b, role=role, trusted=trusted))
                continue
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text" and isinstance(b.get("text"), str):
                segs.append(TextSegment(path=f"{p}.text", text=b["text"], role=role,
                                        trusted=trusted))
                for lp, s in text_leaves(b, p, exclude={"text"}):
                    segs.append(TextSegment(path=lp, text=s, role="document", trusted=False))
            elif t == "tool_result":
                tc = b.get("content")
                if isinstance(tc, str):
                    if tc:
                        segs.append(TextSegment(path=f"{p}.content", text=tc,
                                                role="tool_result", trusted=False))
                elif isinstance(tc, list):
                    AnthropicAdapter._blocks(segs, tc, f"{p}.content", "tool_result", False)
                elif tc is not None:
                    for lp, s in text_leaves(tc, f"{p}.content"):
                        segs.append(TextSegment(path=lp, text=s, role="tool_result",
                                                trusted=False))
                for lp, s in text_leaves(b, p, exclude={"content"}):
                    segs.append(TextSegment(path=lp, text=s, role="tool_result", trusted=False))
            elif t in _TOOL_USE_TYPES:
                for lp, s in string_leaves(b.get("input"), f"{p}.input"):
                    segs.append(TextSegment(path=lp, text=s, role="tool_args"))
                name = b.get("name")
                skip = {"input", "name"} if isinstance(name, str) and _TOOL_NAME.match(name) \
                    else {"input"}
                for lp, s in text_leaves(b, p, exclude=skip):
                    segs.append(TextSegment(path=lp, text=s, role="tool_args"))
            elif t == "thinking":
                if isinstance(b.get("thinking"), str):
                    segs.append(TextSegment(path=f"{p}.thinking", text=b["thinking"],
                                            role="assistant", redactable=False))
            elif t == "redacted_thinking":
                continue  # opaque, encrypted by the provider
            else:
                for lp, s in text_leaves(b, p):
                    segs.append(TextSegment(path=lp, text=s, role="document", trusted=False))

    # ------------------------------------------------------------------ requests
    def parse_request(self, body: dict[str, Any], headers: Mapping[str, str]) -> Interaction:
        cc = is_claude_code(headers)
        segs: list[TextSegment] = []
        system = body.get("system")
        if isinstance(system, str):
            if system:
                segs.append(TextSegment(path="system", text=system, role="system",
                                        redactable=not cc))
        elif isinstance(system, list):
            sys_segs: list[TextSegment] = []
            self._blocks(sys_segs, system, "system", "system")
            for s in sys_segs:
                if s.role == "system":
                    s.redactable = not cc
            segs.extend(sys_segs)
        messages = as_list(body.get("messages"))
        for i, m in enumerate(messages):
            if not isinstance(m, dict):
                continue
            role = "assistant" if m.get("role") == "assistant" else "user"
            content = m.get("content")
            if isinstance(content, str):
                if content:
                    segs.append(TextSegment(path=f"messages[{i}].content", text=content,
                                            role=role))
            elif isinstance(content, list):
                self._blocks(segs, content, f"messages[{i}].content", role)
            # any other model-visible field on the message (fail closed on unknown shapes)
            for lp, s in text_leaves(m, f"messages[{i}]", exclude={"content"}):
                segs.append(TextSegment(path=lp, text=s, role=role))
        for key in _EXTRA_TEXT_KEYS:
            if key in body:
                for lp, s in text_leaves(body[key], key):
                    segs.append(TextSegment(path=lp, text=s, role="user"))
        model = body.get("model")
        text = "\n".join(s.text for s in segs)
        tools = body.get("tools") or []
        est = estimate_tokens(text, model) + (len(dumps(tools)) // 4 if tools else 0)
        return Interaction(
            kind="model_call",
            surface="model.request",
            direction="out",
            model=model if isinstance(model, str) else None,
            segments=segs,
            max_output_tokens=opt_int(body.get("max_tokens")),
            est_input_tokens=est,
            meta={
                "wire": "anthropic",
                "stream": bool(body.get("stream", False)),
                "client": "claude-code" if cc else None,
                "n_messages": len(messages),
                "n_tools": len(tools) if isinstance(tools, list) else 0,
                "thinking": bool(body.get("thinking")),
                **({"claude_code": claude_code_meta(headers)} if cc else {}),
            },
        )

    # ------------------------------------------------------------------ responses
    def parse_response(self, body: dict[str, Any]) -> Interaction:
        segs: list[TextSegment] = []
        self._blocks(segs, as_list(body.get("content")), "content", "assistant")
        model = body.get("model")
        stop = body.get("stop_reason")
        return Interaction(
            kind="model_call",
            surface="model.response",
            direction="in",
            model=model if isinstance(model, str) else None,
            segments=segs,
            meta={"wire": "anthropic", "stop_reason": stop if isinstance(stop, str) else None},
        )

    def apply_segments(self, body: dict[str, Any], segments: list[TextSegment]) -> dict[str, Any]:
        return _apply_segments(body, segments)

    def parse_usage(self, body: dict[str, Any]) -> Usage:
        u = body.get("usage") or {}
        if not isinstance(u, dict):
            return Usage()
        inp = safe_int(u.get("input_tokens"))
        cr = safe_int(u.get("cache_read_input_tokens"))
        cw = safe_int(u.get("cache_creation_input_tokens"))
        return Usage(
            input_tokens=inp + cr + cw,
            output_tokens=safe_int(u.get("output_tokens")),
            cache_read_tokens=cr,
            cache_write_tokens=cw,
            requests=1,
            estimated=not bool(u),
        )

    # ------------------------------------------------------------------ synthetic replies
    @staticmethod
    def message(text: str, *, model: str | None) -> dict[str, Any]:
        return {
            "id": "msg_aegis_" + new_id("x")[2:22],
            "type": "message",
            "role": "assistant",
            "model": model or "aegis",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    @staticmethod
    def error_body(error_type: str, message: str, inner: dict[str, Any] | None = None) -> dict[str, Any]:
        return _error_body("anthropic", error_type, message, inner)

    def blocked_response(
        self,
        verdict: Verdict,
        *,
        model: str | None,
        stream: bool,
        style: Literal["message", "error"],
        **_: Any,
    ) -> tuple[int, dict[str, Any] | bytes, dict[str, str]]:
        info = block_info(verdict, wire="anthropic")
        if info.forced_error or style == "error":
            status = info.status or 403
            return status, self.error_body(info.error_type, info.message, info.inner), info.headers
        msg = self.message(info.message, model=model)
        if stream:
            return 200, anthropic_events(msg), {"content-type": "text/event-stream; charset=utf-8",
                                                "cache-control": "no-cache", **info.headers}
        return 200, msg, info.headers

    def notice_message(self, text: str, *, model: str | None) -> dict[str, Any]:
        """Synthetic assistant message for response-hop blocks (always style=message)."""
        return self.message(text, model=model)

    @staticmethod
    def created() -> int:
        return int(time.time())


ADAPTERS = [AnthropicAdapter()]
