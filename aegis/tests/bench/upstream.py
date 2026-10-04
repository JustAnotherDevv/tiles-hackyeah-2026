"""Tiny deterministic OpenAI + Anthropic echo upstream for the bench (JSON + SSE, fixed delay).

Served by `uvicorn.Server` on an OS-assigned port (port 0) in a daemon thread; never logs bodies.
Delay: `?delay_ms=` / `X-Bench-Delay-Ms` header / the server default.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


def _text_of(messages: Any) -> str:
    out = []
    for m in messages or []:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out.extend(str(b.get("text", "")) for b in c if isinstance(b, dict))
    return "\n".join(out)


def make_app(default_delay_ms: float = 0.0) -> FastAPI:
    app = FastAPI(title="aegis-bench-echo", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.requests = 0

    async def delay(request: Request) -> None:
        d = request.query_params.get("delay_ms") or request.headers.get("x-bench-delay-ms")
        ms = float(d) if d else default_delay_ms
        if ms > 0:
            await asyncio.sleep(ms / 1000.0)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        app.state.requests += 1
        body = await request.json()
        await delay(request)
        text = _text_of(body.get("messages"))[:2000] or "ok"
        reply = f"echo: {text[:200]}"
        pt, ct = max(1, len(text) // 4), max(1, len(reply) // 4)
        if body.get("stream"):
            async def gen():
                base = {"id": "chatcmpl-bench", "object": "chat.completion.chunk", "created": int(time.time()),
                        "model": body.get("model", "mock-echo")}
                for i in range(0, len(reply), 16):
                    chunk = {**base, "choices": [{"index": 0, "delta": {"content": reply[i:i + 16]},
                                                  "finish_reason": None}]}
                    yield f"data: {json.dumps(chunk)}\n\n"
                end = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}}
                yield f"data: {json.dumps(end)}\n\ndata: [DONE]\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        return JSONResponse({
            "id": "chatcmpl-bench", "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model", "mock-echo"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct},
        })

    @app.post("/v1/messages")
    async def messages(request: Request) -> Any:
        app.state.requests += 1
        body = await request.json()
        await delay(request)
        text = _text_of(body.get("messages"))[:2000] or "ok"
        reply = f"echo: {text[:200]}"
        return JSONResponse({
            "id": "msg_bench", "type": "message", "role": "assistant", "model": body.get("model", "mock-echo"),
            "content": [{"type": "text", "text": reply}], "stop_reason": "end_turn",
            "usage": {"input_tokens": max(1, len(text) // 4), "output_tokens": max(1, len(reply) // 4)},
        })

    return app


class EchoUpstream:
    """`with EchoUpstream(delay_ms=0) as up: up.url` - uvicorn on 127.0.0.1:<ephemeral> in a thread."""

    def __init__(self, delay_ms: float = 0.0):
        import uvicorn

        self.app = make_app(delay_ms)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        cfg = uvicorn.Config(self.app, log_level="warning", access_log=False, lifespan="off")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> EchoUpstream:
        self.thread.start()
        t0 = time.monotonic()
        while not self.server.started and time.monotonic() - t0 < 10:
            time.sleep(0.02)
        if not self.server.started:
            raise RuntimeError("echo upstream failed to start")
        return self

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self) -> EchoUpstream:
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


__all__ = ["EchoUpstream", "make_app"]
