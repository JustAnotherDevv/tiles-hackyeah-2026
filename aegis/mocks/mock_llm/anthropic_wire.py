"""Anthropic Messages wire: JSON body and SSE event stream for a `ReplyScript`.

SSE builders ported from staging/spikes/streaming/demo/fake_upstream.py: `message_start` -> `ping`
-> content blocks (`text_delta`, `tool_use` + `input_json_delta`) -> `message_delta` (stop_reason,
usage) -> `message_stop`. Block indices are contiguous from 0.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from mocks.mock_llm.script import ReplyScript, tokens


def ev(name: str, obj: dict[str, Any]) -> bytes:
    data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return f"event: {name}\ndata: {data}\n\n".encode()


def _start(i: int, block: dict[str, Any]) -> bytes:
    return ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": block})


def _delta(i: int, d: dict[str, Any]) -> bytes:
    return ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": d})


def _stop(i: int) -> bytes:
    return ev("content_block_stop", {"type": "content_block_stop", "index": i})


def stop_reason(script: ReplyScript) -> str:
    if script.tool_uses:
        return "tool_use"
    if script.truncated:
        return "max_tokens"
    return "end_turn"


def usage(script: ReplyScript, in_tokens: int) -> dict[str, int]:
    return {"input_tokens": in_tokens, "output_tokens": tokens(script.output_chars())}


def message_json(script: ReplyScript, *, msg_id: str, model: str, in_tokens: int) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if script.text or not script.tool_uses:
        content.append({"type": "text", "text": script.text})
    for t in script.tool_uses:
        content.append({"type": "tool_use", "id": t.id, "name": t.name, "input": t.input})
    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason(script),
        "stop_sequence": None,
        "usage": usage(script, in_tokens),
    }


def sse_events(script: ReplyScript, *, msg_id: str, model: str, in_tokens: int) -> Iterator[bytes]:
    yield ev(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": in_tokens, "output_tokens": 1},
            },
        },
    )
    yield ev("ping", {"type": "ping"})
    idx = 0
    if script.pieces or not script.tool_uses:
        yield _start(idx, {"type": "text", "text": ""})
        for piece in script.pieces:
            yield _delta(idx, {"type": "text_delta", "text": piece})
        yield _stop(idx)
        idx += 1
    for t in script.tool_uses:
        yield _start(idx, {"type": "tool_use", "id": t.id, "name": t.name, "input": {}})
        raw = json.dumps(t.input, ensure_ascii=False)
        for i in range(0, len(raw), 16):
            yield _delta(idx, {"type": "input_json_delta", "partial_json": raw[i : i + 16]})
        yield _stop(idx)
        idx += 1
    yield ev(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason(script), "stop_sequence": None},
            "usage": {"output_tokens": tokens(script.output_chars())},
        },
    )
    yield ev("message_stop", {"type": "message_stop"})


def error_json(status: int, message: str) -> dict[str, Any]:
    etype = {
        400: "invalid_request_error",
        401: "authentication_error",
        403: "permission_error",
        404: "not_found_error",
        413: "request_too_large",
        429: "rate_limit_error",
        529: "overloaded_error",
    }.get(status, "api_error")
    return {"type": "error", "error": {"type": etype, "message": message}}


__all__ = ["error_json", "ev", "message_json", "sse_events", "stop_reason", "usage"]
