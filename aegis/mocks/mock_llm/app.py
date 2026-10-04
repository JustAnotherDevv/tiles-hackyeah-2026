"""mock_llm FastAPI app (:8791): Anthropic + OpenAI wires, JSON + SSE, request log, scan.

Routes (CONTRACTS 5.6 + Addendum A-56):
    POST /v1/messages                 Anthropic Messages (JSON or SSE with `stream: true`)
    POST /v1/messages/count_tokens    {input_tokens}
    POST /v1/chat/completions         OpenAI Chat Completions (JSON or chunks, [DONE])
    GET  /v1/models                   mock-echo, mock-sonnet
    GET  /_mock/requests?limit=       newest-first log of what actually LEFT THE GATEWAY
    DELETE /_mock/requests            clear it
    POST /_mock/scan                  {values: [...]} -> {found: {fingerprint: count}, total}
    POST /_mock/reset                 clear log + counters
    GET  /_mock/health                {service: "mock_llm", port, requests}
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from mocks import RequestLog, mock_data_dir, safe_headers
from mocks.mock_llm import anthropic_wire, openai_wire
from mocks.mock_llm.script import build_script, input_tokens

SERVICE = "mock_llm"
MODELS = [
    {"id": "mock-echo", "display_name": "Mock Echo (repeats what it received)"},
    {"id": "mock-sonnet", "display_name": "Mock Sonnet (echo + templated draft)"},
]


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def create_app(
    *,
    data_dir: str | os.PathLike[str] | None = None,
    log_requests: bool = True,
    seed: int | None = None,
    delta_ms: float | None = None,
) -> FastAPI:
    """Cheap and side-effect free; the JSONL log file is created lazily on the first request."""
    app = FastAPI(title="Aegis mock LLM", docs_url=None, redoc_url=None, openapi_url=None)
    path: Path | None = (mock_data_dir(data_dir) / "mock_llm.requests.jsonl") if log_requests else None
    reqlog = RequestLog(SERVICE, path=path)
    rng = random.Random(seed)
    if delta_ms is None:
        try:
            delta_ms = float(os.environ.get("AEGIS_MOCK_DELTA_MS", "8"))
        except ValueError:
            delta_ms = 8.0
    state: dict[str, Any] = {"n": 0, "delta_s": max(0.0, delta_ms) / 1000.0}
    app.state.reqlog = reqlog
    app.state.mock = state

    def _next_id() -> int:
        state["n"] += 1
        return state["n"]

    def _record(request: Request, wire: str, body: Any) -> None:
        reqlog.add(
            {
                "wire": wire,
                "method": request.method,
                "path": request.url.path,
                "model": body.get("model") if isinstance(body, dict) else None,
                "stream": bool(body.get("stream")) if isinstance(body, dict) else False,
                "headers": safe_headers(request.headers),
                "body": body,
            }
        )

    async def _body(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None, Any]:
        raw = await request.body()
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return None, None, raw.decode("utf-8", errors="replace")
        if not isinstance(body, dict):
            return None, None, body
        return body, None, body

    async def _stream(chunks: Iterator[bytes], delay_ms: int) -> AsyncIterator[bytes]:
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000.0)
        for c in chunks:
            yield c
            if state["delta_s"]:
                await asyncio.sleep(state["delta_s"])

    # ------------------------------------------------------------------------------ Anthropic
    @app.post("/v1/messages")
    async def messages(request: Request) -> Any:
        body, _, logged = await _body(request)
        _record(request, "anthropic", logged)
        if body is None:
            return JSONResponse(anthropic_wire.error_json(400, "invalid JSON body"), status_code=400)
        n = _next_id()
        script = build_script(body, rng, tool_id=f"toolu_mock_{n}")
        model = str(body.get("model") or "mock-echo")
        in_tok = input_tokens(body)
        if script.error_status:
            if script.delay_ms:
                await asyncio.sleep(script.delay_ms / 1000.0)
            return JSONResponse(
                anthropic_wire.error_json(script.error_status, f"mock upstream error {script.error_status}"),
                status_code=script.error_status,
            )
        msg_id = f"msg_mock_{n}"
        if body.get("stream"):
            events = anthropic_wire.sse_events(script, msg_id=msg_id, model=model, in_tokens=in_tok)
            return StreamingResponse(
                _stream(events, script.delay_ms),
                media_type="text/event-stream",
                headers={"cache-control": "no-cache", "request-id": f"req_mock_{n}"},
            )
        if script.delay_ms:
            await asyncio.sleep(script.delay_ms / 1000.0)
        return JSONResponse(
            anthropic_wire.message_json(script, msg_id=msg_id, model=model, in_tokens=in_tok),
            headers={"request-id": f"req_mock_{n}"},
        )

    @app.post("/v1/messages/count_tokens")
    async def count_tokens(request: Request) -> Any:
        body, _, _ = await _body(request)
        return {"input_tokens": input_tokens(body or {})}

    # --------------------------------------------------------------------------------- OpenAI
    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Any:
        body, _, logged = await _body(request)
        _record(request, "openai", logged)
        if body is None:
            return JSONResponse(openai_wire.error_json(400, "invalid JSON body"), status_code=400)
        n = _next_id()
        script = build_script(body, rng, tool_id=f"toolu_mock_{n}")
        model = str(body.get("model") or "mock-echo")
        in_tok = input_tokens(body)
        if script.error_status:
            if script.delay_ms:
                await asyncio.sleep(script.delay_ms / 1000.0)
            return JSONResponse(
                openai_wire.error_json(script.error_status, f"mock upstream error {script.error_status}"),
                status_code=script.error_status,
            )
        cid = f"chatcmpl-mock-{n}"
        created = int(time.time())
        if body.get("stream"):
            include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
            chunks = openai_wire.sse_chunks(
                script, cid=cid, model=model, created=created, in_tokens=in_tok,
                include_usage=include_usage,
            )
            return StreamingResponse(
                _stream(chunks, script.delay_ms),
                media_type="text/event-stream",
                headers={"cache-control": "no-cache"},
            )
        if script.delay_ms:
            await asyncio.sleep(script.delay_ms / 1000.0)
        return openai_wire.completion_json(script, cid=cid, model=model, created=created, in_tokens=in_tok)

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        data = [
            {
                "id": m["id"],
                "object": "model",
                "type": "model",
                "display_name": m["display_name"],
                "created": 1759449600,
                "created_at": "2025-10-03T00:00:00Z",
                "owned_by": "aegis-mock",
            }
            for m in MODELS
        ]
        return {
            "object": "list",
            "data": data,
            "has_more": False,
            "first_id": data[0]["id"],
            "last_id": data[-1]["id"],
        }

    # ---------------------------------------------------------------------------- inspection
    @app.get("/_mock/requests")
    async def get_requests(limit: int = 50) -> dict[str, Any]:
        return {"count": reqlog.total, "items": reqlog.items(limit)}

    @app.delete("/_mock/requests")
    async def delete_requests() -> dict[str, Any]:
        return {"cleared": reqlog.clear()}

    @app.post("/_mock/scan")
    async def scan(request: Request) -> dict[str, Any]:
        """Count raw values in everything that reached the mock (values never go in URLs)."""
        body, _, _ = await _body(request)
        values = [str(v) for v in ((body or {}).get("values") or []) if str(v)]
        blobs = [json.dumps(it.get("body"), ensure_ascii=False) for it in reqlog.items()]
        found: dict[str, int] = {}
        for v in values:
            found[fingerprint(v)] = sum(b.count(v) for b in blobs)
        return {"found": found, "total": sum(found.values()), "requests_scanned": len(blobs)}

    @app.post("/_mock/reset")
    async def reset() -> dict[str, Any]:
        cleared = reqlog.clear()
        state["n"] = 0
        return {"ok": True, "cleared": cleared}

    @app.get("/_mock/health")
    async def health(request: Request) -> dict[str, Any]:
        return {"service": SERVICE, "port": request.url.port, "requests": reqlog.total, "ok": True}

    return app


__all__ = ["MODELS", "SERVICE", "create_app", "fingerprint"]
