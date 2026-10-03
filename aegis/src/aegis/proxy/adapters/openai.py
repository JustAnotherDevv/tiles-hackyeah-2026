"""OpenAI chat-completions wire adapter (`POST /v1/chat/completions`, `/openai/v1/...`).

Owner: core-gateway (bundle B02). Implements `aegis.core.protocols.ProviderAdapter`.

Segments: `messages[i].content` (string or `[{type: text}]` parts); roles `system`/`developer` ->
`system`, `user`, `assistant`, `tool`/`function` -> `tool_result` (`trusted=False`);
`tool_calls[k].function.arguments` (one JSON-string segment, role `tool_args`).
Streaming requests get `stream_options.include_usage=true` (exact usage for budgets); the
synthesized stream hides the usage chunk again when the client did not ask for it.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, Literal

from aegis.core.types import Interaction, TextSegment, Usage, Verdict, new_id
from aegis.proxy.adapters._common import apply_segments as _apply_segments
from aegis.proxy.adapters._common import dumps, estimate_tokens, is_claude_code
from aegis.proxy.adapters._common import error_body as _error_body
from aegis.proxy.blocking import block_info
from aegis.proxy.streaming import openai_chunks

__all__ = ["ADAPTERS", "OpenAIAdapter", "prepare_openai_request"]

_ROLE = {"system": "system", "developer": "system", "user": "user", "assistant": "assistant",
         "tool": "tool_result", "function": "tool_result"}


def prepare_openai_request(body: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Force `stream_options.include_usage` so budgets get exact counts.

    Returns `(new_body, client_requested_usage)` (ported from the streaming spike).
    """
    if not body.get("stream"):
        return body, False
    so = dict(body.get("stream_options") or {})
    requested = bool(so.get("include_usage"))
    so["include_usage"] = True
    return {**body, "stream_options": so}, requested


class OpenAIAdapter:
    wire: Literal["openai"] = "openai"

    def parse_request(self, body: dict[str, Any], headers: Mapping[str, str]) -> Interaction:
        segs: list[TextSegment] = []
        messages = body.get("messages") or []
        for i, m in enumerate(messages):
            if not isinstance(m, dict):
                continue
            role = _ROLE.get(str(m.get("role")), "user")
            trusted = role != "tool_result"
            content = m.get("content")
            if isinstance(content, str):
                segs.append(TextSegment(path=f"messages[{i}].content", text=content, role=role,
                                        trusted=trusted))
            elif isinstance(content, list):
                for j, part in enumerate(content):
                    if (isinstance(part, dict) and part.get("type") == "text"
                            and isinstance(part.get("text"), str)):
                        segs.append(TextSegment(path=f"messages[{i}].content[{j}].text",
                                                text=part["text"], role=role, trusted=trusted))
            for k, tc in enumerate(m.get("tool_calls") or []):
                fn = (tc or {}).get("function") or {}
                if isinstance(fn.get("arguments"), str):
                    segs.append(TextSegment(path=f"messages[{i}].tool_calls[{k}].function.arguments",
                                            text=fn["arguments"], role="tool_args"))
        model = body.get("model")
        text = "\n".join(s.text for s in segs)
        tools = body.get("tools") or []
        est = estimate_tokens(text, model) + (len(dumps(tools)) // 4 if tools else 0)
        max_out = body.get("max_completion_tokens", body.get("max_tokens"))
        so = body.get("stream_options") or {}
        return Interaction(
            kind="model_call",
            surface="model.request",
            direction="out",
            model=model if isinstance(model, str) else None,
            segments=segs,
            max_output_tokens=int(max_out) if isinstance(max_out, (int, float)) else None,
            est_input_tokens=est,
            meta={
                "wire": "openai",
                "stream": bool(body.get("stream", False)),
                "client": "claude-code" if is_claude_code(headers) else None,
                "n_messages": len(messages),
                "n_tools": len(tools) if isinstance(tools, list) else 0,
                "include_usage_requested": bool(isinstance(so, dict) and so.get("include_usage")),
            },
        )

    def parse_response(self, body: dict[str, Any]) -> Interaction:
        segs: list[TextSegment] = []
        for i, ch in enumerate(body.get("choices") or []):
            msg = (ch or {}).get("message") or {}
            if isinstance(msg.get("content"), str):
                segs.append(TextSegment(path=f"choices[{i}].message.content", text=msg["content"],
                                        role="assistant"))
            for k, tc in enumerate(msg.get("tool_calls") or []):
                fn = (tc or {}).get("function") or {}
                if isinstance(fn.get("arguments"), str):
                    segs.append(TextSegment(
                        path=f"choices[{i}].message.tool_calls[{k}].function.arguments",
                        text=fn["arguments"], role="tool_args"))
        model = body.get("model")
        return Interaction(
            kind="model_call",
            surface="model.response",
            direction="in",
            model=model if isinstance(model, str) else None,
            segments=segs,
            meta={"wire": "openai"},
        )

    def apply_segments(self, body: dict[str, Any], segments: list[TextSegment]) -> dict[str, Any]:
        return _apply_segments(body, segments)

    def parse_usage(self, body: dict[str, Any]) -> Usage:
        u = body.get("usage") or {}
        if not isinstance(u, dict):
            return Usage()
        details = u.get("prompt_tokens_details") or {}
        return Usage(
            input_tokens=int(u.get("prompt_tokens") or 0),
            output_tokens=int(u.get("completion_tokens") or 0),
            cache_read_tokens=int((details or {}).get("cached_tokens") or 0),
            requests=1,
            estimated=not bool(u),
        )

    # ------------------------------------------------------------------ synthetic replies
    @staticmethod
    def completion(text: str, *, model: str | None) -> dict[str, Any]:
        return {
            "id": "chatcmpl-aegis-" + new_id("x")[2:22],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model or "aegis",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                         "logprobs": None, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    @staticmethod
    def error_body(error_type: str, message: str, inner: dict[str, Any] | None = None) -> dict[str, Any]:
        return _error_body("openai", error_type, message, inner)

    def blocked_response(
        self,
        verdict: Verdict,
        *,
        model: str | None,
        stream: bool,
        style: Literal["message", "error"],
        include_usage: bool = False,
        **_: Any,
    ) -> tuple[int, dict[str, Any] | bytes, dict[str, str]]:
        info = block_info(verdict, wire="openai")
        if info.forced_error or style == "error":
            status = info.status or 403
            return status, self.error_body(info.error_type, info.message, info.inner), info.headers
        comp = self.completion(info.message, model=model)
        if stream:
            return 200, openai_chunks(comp, include_usage=include_usage), {
                "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-cache",
                **info.headers}
        return 200, comp, info.headers

    def notice_message(self, text: str, *, model: str | None) -> dict[str, Any]:
        return self.completion(text, model=model)


ADAPTERS = [OpenAIAdapter()]
