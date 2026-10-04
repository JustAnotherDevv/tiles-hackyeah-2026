"""Ollama native wire adapter (`/ollama/api/chat`, `/ollama/api/generate`).

Owner: core-gateway (bundle B02). Implements `aegis.core.protocols.ProviderAdapter`.

`/api/chat`: `messages[i].content` (roles as OpenAI; `thinking` -> `redactable=False`);
`/api/generate`: `prompt` (user) and `system`. Ollama streams by default (`stream` defaults to
true). Usage: `prompt_eval_count`, `eval_count`, `compute_s = total_duration / 1e9`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from aegis.core.types import Interaction, TextSegment, Usage, Verdict
from aegis.proxy.adapters._common import apply_segments as _apply_segments
from aegis.proxy.adapters._common import error_body as _error_body
from aegis.proxy.adapters._common import estimate_tokens, is_claude_code, iso_now, string_leaves
from aegis.proxy.blocking import block_info
from aegis.proxy.streaming import ollama_lines

__all__ = ["ADAPTERS", "OllamaAdapter"]

_ROLE = {"system": "system", "user": "user", "assistant": "assistant", "tool": "tool_result"}


class OllamaAdapter:
    wire: Literal["ollama"] = "ollama"

    @staticmethod
    def op_of(body: dict[str, Any]) -> str:
        return "chat" if "messages" in body else "generate"

    def parse_request(self, body: dict[str, Any], headers: Mapping[str, str]) -> Interaction:
        segs: list[TextSegment] = []
        op = self.op_of(body)
        if op == "chat":
            for i, m in enumerate(body.get("messages") or []):
                if not isinstance(m, dict):
                    continue
                role = _ROLE.get(str(m.get("role")), "user")
                if isinstance(m.get("content"), str):
                    segs.append(TextSegment(path=f"messages[{i}].content", text=m["content"],
                                            role=role, trusted=role != "tool_result"))
                if isinstance(m.get("thinking"), str) and m["thinking"]:
                    segs.append(TextSegment(path=f"messages[{i}].thinking", text=m["thinking"],
                                            role="assistant", redactable=False))
                for k, tc in enumerate(m.get("tool_calls") or []):
                    fn = (tc or {}).get("function") or {}
                    for p, s in string_leaves(fn.get("arguments"),
                                              f"messages[{i}].tool_calls[{k}].function.arguments"):
                        segs.append(TextSegment(path=p, text=s, role="tool_args"))
        else:
            if isinstance(body.get("system"), str) and body["system"]:
                segs.append(TextSegment(path="system", text=body["system"], role="system"))
            if isinstance(body.get("prompt"), str):
                segs.append(TextSegment(path="prompt", text=body["prompt"], role="user"))
        model = body.get("model")
        opts = body.get("options") or {}
        num_predict = opts.get("num_predict") if isinstance(opts, dict) else None
        text = "\n".join(s.text for s in segs)
        return Interaction(
            kind="model_call",
            surface="model.request",
            direction="out",
            model=model if isinstance(model, str) else None,
            segments=segs,
            max_output_tokens=int(num_predict) if isinstance(num_predict, (int, float))
            and num_predict > 0 else None,
            est_input_tokens=estimate_tokens(text, model),
            meta={
                "wire": "ollama",
                "op": op,
                "stream": bool(body.get("stream", True)),
                "client": "claude-code" if is_claude_code(headers) else None,
                "n_messages": len(body.get("messages") or []),
            },
        )

    def parse_response(self, body: dict[str, Any]) -> Interaction:
        segs: list[TextSegment] = []
        if "message" in body:
            msg = body.get("message") or {}
            if isinstance(msg.get("content"), str):
                segs.append(TextSegment(path="message.content", text=msg["content"],
                                        role="assistant"))
            if isinstance(msg.get("thinking"), str) and msg["thinking"]:
                segs.append(TextSegment(path="message.thinking", text=msg["thinking"],
                                        role="assistant", redactable=False))
            for k, tc in enumerate(msg.get("tool_calls") or []):
                fn = (tc or {}).get("function") or {}
                for p, s in string_leaves(fn.get("arguments"),
                                          f"message.tool_calls[{k}].function.arguments"):
                    segs.append(TextSegment(path=p, text=s, role="tool_args"))
        elif isinstance(body.get("response"), str):
            segs.append(TextSegment(path="response", text=body["response"], role="assistant"))
        model = body.get("model")
        return Interaction(
            kind="model_call",
            surface="model.response",
            direction="in",
            model=model if isinstance(model, str) else None,
            segments=segs,
            meta={"wire": "ollama", "op": "chat" if "message" in body else "generate"},
        )

    def apply_segments(self, body: dict[str, Any], segments: list[TextSegment]) -> dict[str, Any]:
        return _apply_segments(body, segments)

    def parse_usage(self, body: dict[str, Any]) -> Usage:
        # A-08: compute_s = (load + prompt_eval + eval durations) / 1e9 (wall time if missing)
        parts = [body.get(k) for k in ("load_duration", "prompt_eval_duration", "eval_duration")]
        ns = sum(float(p) for p in parts if isinstance(p, (int, float)))
        if not ns and isinstance(body.get("total_duration"), (int, float)):
            ns = float(body["total_duration"])
        return Usage(
            input_tokens=int(body.get("prompt_eval_count") or 0),
            output_tokens=int(body.get("eval_count") or 0),
            compute_s=round(ns / 1e9, 6),
            requests=1,
            estimated="eval_count" not in body,
        )

    # ------------------------------------------------------------------ synthetic replies
    @staticmethod
    def reply(text: str, *, model: str | None, op: str = "chat") -> dict[str, Any]:
        base: dict[str, Any] = {"model": model or "aegis", "created_at": iso_now()}
        if op == "generate":
            return {**base, "response": text, "done": True, "done_reason": "stop"}
        return {**base, "message": {"role": "assistant", "content": text}, "done": True,
                "done_reason": "stop"}

    @staticmethod
    def error_body(error_type: str, message: str, inner: dict[str, Any] | None = None) -> dict[str, Any]:
        return _error_body("ollama", error_type, message, inner)

    def blocked_response(
        self,
        verdict: Verdict,
        *,
        model: str | None,
        stream: bool,
        style: Literal["message", "error"],
        op: str = "chat",
        **_: Any,
    ) -> tuple[int, dict[str, Any] | bytes, dict[str, str]]:
        info = block_info(verdict, wire="ollama")
        if info.forced_error or style == "error":
            status = info.status or 403
            return status, self.error_body(info.error_type, info.message, info.inner), info.headers
        reply = self.reply(info.message, model=model, op=op)
        if stream:
            return 200, ollama_lines(reply, op=op), {"content-type": "application/x-ndjson",
                                                    **info.headers}
        return 200, reply, info.headers

    def notice_message(self, text: str, *, model: str | None, op: str = "chat") -> dict[str, Any]:
        return self.reply(text, model=model, op=op)


ADAPTERS = [OllamaAdapter()]
