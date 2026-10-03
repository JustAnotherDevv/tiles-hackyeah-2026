"""Streamable HTTP reverse proxy as a FastAPI APIRouter (drop-in for the gateway).

    app.include_router(build_mcp_router(governor))          # POST/GET/DELETE /mcp/{server}
    app.include_router(build_admin_router(governor, sink))  # /aegis/mcp/{pins,events,reset}

Message-level and era-agnostic: HTTP requests/responses are forwarded as-is (Mcp-Session-Id,
MCP-Protocol-Version, Mcp-* headers, SSE framing and keep-alive comments), each JSON-RPC body or
SSE event is parsed, and only rewritten when the governor says so. Session management stays
with the upstream server, so legacy (2025-11-25, stateful) and modern (2026-07-28, stateless)
clients both work without the proxy terminating MCP.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .events import MemorySink
from .governor import Ctx, Governor
from .protocol import (
    MODERN,
    check_modern_request,
    detect_era,
    is_request,
    is_response,
    iter_sse,
    jsonrpc_error,
    recompute_routing_headers,
)

# Request headers we pass upstream. Client credentials (Authorization, Cookie) are deliberately
# NOT forwarded: the catalog injects a per-server credential instead (MCP-04, no token passthrough).
_FWD_REQUEST = {"accept", "content-type", "mcp-session-id", "mcp-protocol-version", "mcp-method", "mcp-name",
                "last-event-id"}
_FWD_RESPONSE = {"content-type", "mcp-session-id", "mcp-protocol-version", "cache-control", "x-accel-buffering"}

PARSE_ERROR, INVALID_REQUEST = -32700, -32600


def _request_headers(request: Request) -> dict[str, str]:
    return {k: v for k, v in ((k.lower(), v) for k, v in request.headers.items())
            if k in _FWD_REQUEST or k.startswith("mcp-param-")}


def _response_headers(resp: httpx.Response) -> dict[str, str]:
    return {k: v for k, v in resp.headers.items() if k.lower() in _FWD_RESPONSE}


def build_mcp_router(governor: Governor, *, prefix: str = "/mcp", client: httpx.AsyncClient | None = None,
                     ) -> APIRouter:
    owned = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=False)

    @asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        yield
        if owned:
            await http.aclose()

    router = APIRouter(prefix=prefix, lifespan=lifespan, tags=["mcp"])

    def upstream_for(server: str, request: Request) -> str:
        origin = request.headers.get("origin")
        if origin and not any(origin == o or origin.startswith(o + ":") for o in governor.policy.allowed_origins):
            # DNS-rebinding protection is a MUST for local Streamable HTTP endpoints.
            raise HTTPException(403, "origin not allowed")
        entry = governor.policy.servers.get(server)
        if entry is None or not entry.url:
            governor.emit(Ctx(server), "*", "block", controls=["MCP-01"],
                          reasons=["unknown MCP server (not in the aegis catalog)"])
            raise HTTPException(404, f"unknown MCP server {server!r}")
        return entry.url

    async def relay(ctx: Ctx, resp: httpx.Response, request_msg: dict[str, Any] | None) -> Response:
        headers = _response_headers(resp)
        ctx.session = resp.headers.get("mcp-session-id") or ctx.session

        def transform(msg: Any) -> Any:
            answers = request_msg is not None and is_response(msg) and msg.get("id") == request_msg.get("id")
            return governor.on_server_message(ctx, msg, request_msg if answers else None)

        if "text/event-stream" in resp.headers.get("content-type", ""):
            async def events() -> AsyncIterator[bytes]:
                try:
                    async for ev in iter_sse(resp.aiter_bytes()):
                        msg = ev.json()
                        if msg is not None:
                            new = transform(msg)
                            if new is not msg:
                                ev.data = json.dumps(new, ensure_ascii=False)
                        yield ev.encode()
                finally:
                    await resp.aclose()

            headers.setdefault("x-accel-buffering", "no")
            return StreamingResponse(events(), status_code=resp.status_code, headers=headers)

        data = await resp.aread()
        await resp.aclose()
        if data and "application/json" in resp.headers.get("content-type", ""):
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                msg = None
            if msg is not None:
                new = transform(msg)
                if new is not msg:
                    data = json.dumps(new, ensure_ascii=False).encode()
        return Response(content=data, status_code=resp.status_code, headers=headers)

    async def send(method: str, url: str, server: str, headers: dict[str, str], content: bytes | None = None
                   ) -> httpx.Response:
        entry = governor.policy.servers[server]
        req = http.build_request(method, url, headers={**headers, **entry.headers}, content=content)
        try:
            return await http.send(req, stream=True)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"upstream MCP server {server!r} unreachable: {type(e).__name__}") from e

    @router.post("/{server}")
    async def post(server: str, request: Request) -> Response:
        url = upstream_for(server, request)
        raw = await request.body()
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse(jsonrpc_error(None, PARSE_ERROR, "Parse error"), status_code=400)
        if isinstance(body, list):  # JSON-RPC batching was removed in 2025-06-18; refuse rather than half-govern
            return JSONResponse(jsonrpc_error(None, INVALID_REQUEST, "aegis: JSON-RPC batches are not supported"),
                                status_code=400)

        headers = _request_headers(request)
        era = detect_era(headers, body)
        ctx = Ctx(server, "http", era, headers.get("mcp-session-id"))
        schema = None
        if is_request(body) and body.get("method") == "tools/call":
            schema = governor.pins.input_schema(server, str((body.get("params") or {}).get("name")))

        if era == MODERN and is_request(body):
            raw_pairs = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in request.headers.raw]
            if rejection := check_modern_request(body, headers, raw_pairs, schema):
                governor.emit(ctx, str(body.get("method")), "block", controls=["MCP-HDR"],
                              tool=(body.get("params") or {}).get("name"),
                              reasons=[f"header/body mismatch (request smuggling defense): {rejection.message}"])
                return JSONResponse(jsonrpc_error(body.get("id"), rejection.code, rejection.message), status_code=400)

        verdict = governor.on_client_message(ctx, body)
        if verdict.action == "respond":
            return JSONResponse(verdict.message)

        content = raw
        if verdict.rewritten:
            content = json.dumps(verdict.message, ensure_ascii=False).encode()
            if era == MODERN:
                headers = recompute_routing_headers(headers, verdict.message, schema)
        resp = await send("POST", url, server, headers, content)
        return await relay(ctx, resp, verdict.message if is_request(verdict.message) else None)

    @router.get("/{server}")
    async def get_stream(server: str, request: Request) -> Response:
        # legacy standalone SSE stream (server->client notifications/requests); modern servers answer 405
        url = upstream_for(server, request)
        headers = _request_headers(request)
        ctx = Ctx(server, "http", detect_era(headers, None), headers.get("mcp-session-id"))
        return await relay(ctx, await send("GET", url, server, headers), None)

    @router.delete("/{server}")
    async def delete_session(server: str, request: Request) -> Response:
        url = upstream_for(server, request)
        resp = await send("DELETE", url, server, _request_headers(request))
        data = await resp.aread()
        await resp.aclose()
        return Response(content=data, status_code=resp.status_code, headers=_response_headers(resp))

    return router


def build_admin_router(governor: Governor, events: MemorySink | None = None, *, prefix: str = "/aegis/mcp"
                       ) -> APIRouter:
    """Dashboard/ops endpoints. In the gateway: behind admin auth + the org approval flow."""
    router = APIRouter(prefix=prefix, tags=["mcp-admin"])

    @router.get("/pins")
    async def pins() -> dict[str, Any]:
        return governor.pins.snapshot()

    @router.post("/pins/{server}/{tool}/approve")
    async def approve(server: str, tool: str) -> dict[str, Any]:
        try:
            pin = governor.pins.approve(server, tool, approved_by="admin")
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        governor.emit(Ctx(server), "tools/list", "allow", tool=tool, controls=["MCP-03"],
                      reasons=["new definition approved by admin"], detail={"hash": pin.hash})
        return {"ok": True, "hash": pin.hash}

    @router.post("/reset")
    async def reset() -> dict[str, Any]:
        governor.pins.reset()
        if events is not None:
            events.events.clear()
        return {"ok": True}

    @router.get("/events")
    async def recent(limit: int = 100) -> list[dict[str, Any]]:
        return [] if events is None else events.events[-limit:]

    return router
