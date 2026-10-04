"""Anthropic Messages wire adapter (`POST /v1/messages`), used by Claude Code.

Owner: core-gateway (bundle B02). Implements `aegis.core.protocols.ProviderAdapter`.

Segment conventions (CONTRACTS 3.1/3.4 + plan 01 section 2.7):

* `system` (string or text blocks) -> role `system`; **`redactable=False` for Claude Code clients**
  (attribution block / prompt-cache safety) unless the provider sets `redact_system: true`
  (the flow flips the flag);
* `messages[i].content` string or `text` blocks -> role of the message (`user` / `assistant`);
* `tool_result` blocks (string or text blocks) -> role `tool_result`, `trusted=False`;
* `tool_use.input` string leaves -> role `tool_args`;
* `thinking` -> `redactable=False` (signed); `redacted_thinking`, images, documents with base64,
  tool definitions, `cache_control`, `metadata` and unknown fields are never segments and are
  copied verbatim (`apply_segments` uses copy-on-write: untouched bytes stay identical).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, Literal

from aegis.core.types import Interaction, TextSegment, Usage, Verdict, new_id
from aegis.proxy.adapters._common import (
    apply_segments as _apply_segments,
)
from aegis.proxy.adapters._common import (
    claude_code_meta,
    dumps,
    estimate_tokens,
    is_claude_code,
    string_leaves,
)
from aegis.proxy.adapters._common import error_body as _error_body
from aegis.proxy.blocking import block_info
from aegis.proxy.streaming import anthropic_events

__all__ = ["ADAPTERS", "AnthropicAdapter"]

_TOOL_USE_TYPES = {"tool_use", "server_tool_use", "mcp_tool_use"}


class AnthropicAdapter:
    wire: Literal["anthropic"] = "anthropic"

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
            for j, b in enumerate(system):
                if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                    segs.append(TextSegment(path=f"system[{j}].text", text=b["text"],
                                            role="system", redactable=not cc))
        messages = body.get("messages") or []
        for i, m in enumerate(messages):
            if not isinstance(m, dict):
                continue
            role = "assistant" if m.get("role") == "assistant" else "user"
            content = m.get("content")
            if isinstance(content, str):
                segs.append(TextSegment(path=f"messages[{i}].content", text=content, role=role))
                continue
            if not isinstance(content, list):
                continue
            for j, b in enumerate(content):
                if not isinstance(b, dict):
                    continue
                base = f"messages[{i}].content[{j}]"
                t = b.get("type")
                if t == "text" and isinstance(b.get("text"), str):
                    segs.append(TextSegment(path=f"{base}.text", text=b["text"], role=role))
                elif t == "tool_result":
                    tc = b.get("content")
                    if isinstance(tc, str):
                        segs.append(TextSegment(path=f"{base}.content", text=tc,
                                                role="tool_result", trusted=False))
                    elif isinstance(tc, list):
                        for k, tb in enumerate(tc):
                            if (isinstance(tb, dict) and tb.get("type") == "text"
                                    and isinstance(tb.get("text"), str)):
                                segs.append(TextSegment(path=f"{base}.content[{k}].text",
                                                        text=tb["text"], role="tool_result",
                                                        trusted=False))
                elif t in _TOOL_USE_TYPES:
                    for p, s in string_leaves(b.get("input"), f"{base}.input"):
                        segs.append(TextSegment(path=p, text=s, role="tool_args"))
                elif t == "thinking" and isinstance(b.get("thinking"), str):
                    segs.append(TextSegment(path=f"{base}.thinking", text=b["thinking"],
                                            role="assistant", redactable=False))
                elif t == "document":
                    src = b.get("source") or {}
                    if src.get("type") == "text" and isinstance(src.get("data"), str):
                        segs.append(TextSegment(path=f"{base}.source.data", text=src["data"],
                                                role="document", trusted=False))
        model = body.get("model")
        text = "\n".join(s.text for s in segs)
        tools = body.get("tools") or []
        est = estimate_tokens(text, model) + (len(dumps(tools)) // 4 if tools else 0)
        max_out = body.get("max_tokens")
        return Interaction(
            kind="model_call",
            surface="model.request",
            direction="out",
            model=model if isinstance(model, str) else None,
            segments=segs,
            max_output_tokens=int(max_out) if isinstance(max_out, (int, float)) else None,
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
        for i, b in enumerate(body.get("content") or []):
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text" and isinstance(b.get("text"), str):
                segs.append(TextSegment(path=f"content[{i}].text", text=b["text"],
                                        role="assistant"))
            elif t in _TOOL_USE_TYPES:
                for p, s in string_leaves(b.get("input"), f"content[{i}].input"):
                    segs.append(TextSegment(path=p, text=s, role="tool_args"))
            elif t == "thinking" and isinstance(b.get("thinking"), str):
                segs.append(TextSegment(path=f"content[{i}].thinking", text=b["thinking"],
                                        role="assistant", redactable=False))
        model = body.get("model")
        return Interaction(
            kind="model_call",
            surface="model.response",
            direction="in",
            model=model if isinstance(model, str) else None,
            segments=segs,
            meta={"wire": "anthropic", "stop_reason": body.get("stop_reason")},
        )

    def apply_segments(self, body: dict[str, Any], segments: list[TextSegment]) -> dict[str, Any]:
        return _apply_segments(body, segments)

    def parse_usage(self, body: dict[str, Any]) -> Usage:
        u = body.get("usage") or {}
        if not isinstance(u, dict):
            return Usage()
        inp = int(u.get("input_tokens") or 0)
        cr = int(u.get("cache_read_input_tokens") or 0)
        cw = int(u.get("cache_creation_input_tokens") or 0)
        return Usage(
            input_tokens=inp + cr + cw,
            output_tokens=int(u.get("output_tokens") or 0),
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
