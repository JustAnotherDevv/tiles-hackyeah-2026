"""OpenAI Chat Completions wire: `chat.completion` JSON and `chat.completion.chunk` SSE.

Streaming: first chunk carries `delta.role`, then `delta.content` pieces, then `delta.tool_calls`
(name first, arguments in pieces), a final chunk with `finish_reason`, a usage chunk (`choices: []`)
only when `stream_options.include_usage` is true, and `data: [DONE]`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from mocks.mock_llm.script import ReplyScript, tokens


def _data(obj: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(obj, separators=(',', ':'), ensure_ascii=False)}\n\n".encode()


def finish_reason(script: ReplyScript) -> str:
    if script.tool_uses:
        return "tool_calls"
    if script.truncated:
        return "length"
    return "stop"


def usage(script: ReplyScript, in_tokens: int) -> dict[str, int]:
    out = tokens(script.output_chars())
    return {"prompt_tokens": in_tokens, "completion_tokens": out, "total_tokens": in_tokens + out}


def _tool_calls(script: ReplyScript) -> list[dict[str, Any]]:
    return [
        {
            "id": t.id.replace("toolu_", "call_"),
            "type": "function",
            "function": {"name": t.name, "arguments": json.dumps(t.input, ensure_ascii=False)},
        }
        for t in script.tool_uses
    ]


def completion_json(
    script: ReplyScript, *, cid: str, model: str, created: int, in_tokens: int
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": script.text or None}
    if script.tool_uses:
        message["tool_calls"] = _tool_calls(script)
    else:
        message["content"] = script.text
    return {
        "id": cid,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason(script)}],
        "usage": usage(script, in_tokens),
    }


def sse_chunks(
    script: ReplyScript,
    *,
    cid: str,
    model: str,
    created: int,
    in_tokens: int,
    include_usage: bool = False,
) -> Iterator[bytes]:
    base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model}

    def chunk(delta: dict[str, Any], finish: str | None = None) -> bytes:
        return _data({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})

    yield chunk({"role": "assistant", "content": ""})
    for piece in script.pieces:
        yield chunk({"content": piece})
    for i, tc in enumerate(_tool_calls(script)):
        fn = tc["function"]
        yield chunk(
            {
                "tool_calls": [
                    {
                        "index": i,
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": fn["name"], "arguments": ""},
                    }
                ]
            }
        )
        args = fn["arguments"]
        for j in range(0, len(args), 16):
            yield chunk({"tool_calls": [{"index": i, "function": {"arguments": args[j : j + 16]}}]})
    yield chunk({}, finish_reason(script))
    if include_usage:
        yield _data({**base, "choices": [], "usage": usage(script, in_tokens)})
    yield b"data: [DONE]\n\n"


def error_json(status: int, message: str) -> dict[str, Any]:
    etype = {
        400: "invalid_request_error",
        401: "authentication_error",
        403: "permission_error",
        404: "not_found_error",
        429: "rate_limit_exceeded",
    }.get(status, "server_error")
    return {"error": {"message": message, "type": etype, "param": None, "code": etype}}


__all__ = ["completion_json", "error_json", "finish_reason", "sse_chunks", "usage"]
