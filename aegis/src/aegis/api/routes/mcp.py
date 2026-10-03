"""MCP Streamable HTTP proxy routes (owner: mcp-proxy).

    POST|GET|DELETE /mcp/{server}     transparent proxy to mcp.servers[server].url (both eras)
    POST /mcp/{server}/_stdio         inspection endpoint for `python -m aegis.mcp.stdio`

Thin: all logic lives in `aegis.mcp.proxy` / `aegis.mcp.service`. `on_startup(rt)` creates and
starts the McpService (shared httpx client, PinStore, `mcp_pin` approval executor, policy hot
reload hook); `on_shutdown(rt)` stops it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from aegis.mcp.jsonrpc import INTERNAL_ERROR, INVALID_REQUEST, jsonrpc_error
from aegis.mcp.proxy import handle_delete, handle_get, handle_post, lower_headers
from aegis.mcp.service import McpService, get_service, set_service

log = logging.getLogger(__name__)

ORDER = 100
router = APIRouter(tags=["mcp"])


def _not_ready() -> JSONResponse:
    return JSONResponse(jsonrpc_error(None, INTERNAL_ERROR, "[Aegis] MCP proxy not ready"),
                        status_code=503)


def _svc() -> McpService | None:
    svc = get_service()
    return svc if svc is not None and svc.started else None


@router.post("/mcp/{server}")
async def mcp_post(server: str, request: Request) -> Response:
    svc = _svc()
    if svc is None:
        return _not_ready()
    return await handle_post(svc, request, server)


@router.get("/mcp/{server}")
async def mcp_get(server: str, request: Request) -> Response:
    svc = _svc()
    if svc is None:
        return _not_ready()
    return await handle_get(svc, request, server)


@router.delete("/mcp/{server}")
async def mcp_delete(server: str, request: Request) -> Response:
    svc = _svc()
    if svc is None:
        return _not_ready()
    return await handle_delete(svc, request, server)


@router.post("/mcp/{server}/_stdio")
async def mcp_stdio(server: str, request: Request) -> Response:
    """{direction: "out"|"in", message: <jsonrpc>, session_id} -> {action, message, decision_id}."""
    svc = _svc()
    if svc is None:
        return _not_ready()
    try:
        body: Any = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("message"), dict | list):
        return JSONResponse(jsonrpc_error(None, INVALID_REQUEST,
                                          "[Aegis] expected {direction, message, session_id}"),
                            status_code=400)
    if isinstance(body.get("message"), list):
        return JSONResponse(jsonrpc_error(None, INVALID_REQUEST,
                                          "[Aegis] JSON-RPC batches are not supported"), status_code=400)
    out = await svc.handle_stdio(server, body, lower_headers(request))
    return JSONResponse(out)


async def on_startup(rt: Any) -> None:
    svc = get_service()
    if svc is None or svc.rt is not rt:
        svc = McpService(rt)
        set_service(svc)
    if not svc.started:
        await svc.start()


async def on_shutdown(rt: Any) -> None:
    svc = get_service()
    if svc is not None and svc.rt is rt:
        await svc.stop()
        set_service(None)
