"""MCP dashboard/admin API (owner: mcp-proxy).

    GET  /api/mcp/servers                                   -> {items: McpServerView[]}
    GET  /api/mcp/servers/{server}/tools/{tool}             -> {tool, pinned, candidate, diff, findings, approval_id}
    POST /api/mcp/servers/{server}/tools/{tool}/approve     {comment?} -> McpToolView   (admin)
    POST /api/mcp/servers/{server}/tools/{tool}/quarantine  {reason?}  -> McpToolView   (admin)
    POST /api/mcp/servers/{server}/scan                     -> McpServerView            (admin)
    GET  /api/mcp/claude-config?agent_id=&servers=          -> {mcpServers: {...}}
    POST /api/mcp/reset                                     -> {ok: true}               (admin; demo)

Approve votes on the pending `mcp_pin` approval through `rt.approvals.vote` (so the approvals
engine's routing / separation of duties applies); a PermissionError becomes 403 `forbidden`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from aegis.core.types import ROLE_RANK, Identity
from aegis.mcp.proxy import lower_headers
from aegis.mcp.service import McpService, get_service

log = logging.getLogger(__name__)

ORDER = 100
router = APIRouter(tags=["mcp-admin"])


def _error(status: int, type_: str, message: str, **fields: Any) -> JSONResponse:
    try:
        from aegis.core.errors import api_error

        return api_error(status, type_, message, **fields)
    except Exception:  # TODO(integration): fallback until aegis.core.errors lands
        return JSONResponse(
            {"error": {"type": type_, "message": message, **fields}}, status_code=status
        )


def _svc() -> McpService | None:
    svc = get_service()
    return svc if svc is not None and svc.started else None


async def _viewer(svc: McpService, request: Request) -> Identity:
    try:
        return await svc.rt.org.resolve_viewer(lower_headers(request), dict(request.query_params))
    except Exception:
        log.warning("viewer resolution failed; defaulting to anonymous member", exc_info=True)
        return Identity(role="viewer")


def _forbidden_role(viewer: Identity, min_role: str) -> JSONResponse | None:
    if ROLE_RANK.get(viewer.role, 0) < ROLE_RANK[min_role]:
        who = viewer.member_id or viewer.principal
        return _error(
            403,
            "forbidden",
            f"{who} ({viewer.role}) cannot do this: requires {min_role}",
            required_role=min_role,
        )
    return None


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError:
        return {}
    return body if isinstance(body, dict) else {}


@router.get("/api/mcp/servers")
async def list_servers() -> Response:
    svc = _svc()
    if svc is None:
        return JSONResponse({"items": []})
    return JSONResponse({"items": [v.model_dump(mode="json") for v in svc.inventory()]})


@router.get("/api/mcp/servers/{server}/tools/{tool}")
async def tool_detail(server: str, tool: str) -> Response:
    svc = _svc()
    detail = svc.tool_detail(server, tool) if svc is not None else None
    if detail is None:
        return _error(404, "not_found", f"MCP tool {server}.{tool} not found")
    return JSONResponse(detail)


@router.post("/api/mcp/servers/{server}/tools/{tool}/approve")
async def approve_tool(server: str, tool: str, request: Request) -> Response:
    svc = _svc()
    if svc is None:
        return _error(503, "unavailable", "MCP proxy not ready")
    viewer = await _viewer(svc, request)
    if (denied := _forbidden_role(viewer, "admin")) is not None:
        return denied
    body = await _json(request)
    try:
        view = await svc.approve_tool(server, tool, viewer, body.get("comment"))
    except PermissionError as e:
        return _error(403, "forbidden", str(e) or "not allowed to approve this request")
    except KeyError:
        return _error(404, "not_found", f"MCP tool {server}.{tool} not found")
    return JSONResponse(view.model_dump(mode="json"))


@router.post("/api/mcp/servers/{server}/tools/{tool}/quarantine")
async def quarantine_tool(server: str, tool: str, request: Request) -> Response:
    svc = _svc()
    if svc is None:
        return _error(503, "unavailable", "MCP proxy not ready")
    viewer = await _viewer(svc, request)
    if (denied := _forbidden_role(viewer, "admin")) is not None:
        return denied
    body = await _json(request)
    try:
        view = await svc.quarantine(server, tool, viewer, body.get("reason"))
    except KeyError:
        return _error(404, "not_found", f"MCP tool {server}.{tool} not found")
    return JSONResponse(view.model_dump(mode="json"))


@router.post("/api/mcp/servers/{server}/scan")
async def scan_server(server: str, request: Request) -> Response:
    svc = _svc()
    if svc is None:
        return _error(503, "unavailable", "MCP proxy not ready")
    viewer = await _viewer(svc, request)
    if (denied := _forbidden_role(viewer, "admin")) is not None:
        return denied
    snap = svc.rt.policy.snapshot()
    if server not in snap.doc.mcp.servers:
        return _error(404, "not_found", f"MCP server {server} is not in mcp.servers")
    try:
        await svc.scan_server(server, viewer, snap=snap, force=True)
    except Exception as e:
        await svc.upstream_failed(
            await svc.make_ctx(
                server, {}, era="legacy", transport="http", snap=snap, identity=viewer
            ),
            type(e).__name__,
        )
        return _error(
            502, "upstream_error", f"MCP server {server} unreachable ({type(e).__name__})"
        )
    for view in svc.inventory(snap):
        if view.name == server:
            return JSONResponse(view.model_dump(mode="json"))
    return _error(404, "not_found", f"MCP server {server} not found")


@router.get("/api/mcp/claude-config")
async def claude_config(request: Request) -> Response:
    from aegis.mcp.claude_config import build_claude_config

    svc = _svc()
    q = request.query_params
    servers = [s for s in (q.get("servers") or "").split(",") if s] or None
    try:
        snap = svc.rt.policy.snapshot() if svc is not None else None
        settings = getattr(svc.rt, "settings", None) if svc is not None else None
        gateway = str(getattr(settings, "public_url", "")) or str(request.base_url).rstrip("/")
    except Exception:
        snap, gateway = None, str(request.base_url).rstrip("/")
    if snap is None:
        return _error(503, "unavailable", "policy not loaded")
    return JSONResponse(
        build_claude_config(
            snap,
            gateway_url=gateway,
            agent_id=q.get("agent_id") or "claude-code@platform",
            servers=servers,
        )
    )


@router.post("/api/mcp/reset")
async def reset(request: Request) -> Response:
    svc = _svc()
    if svc is None:
        return JSONResponse({"ok": True})
    viewer = await _viewer(svc, request)
    if (denied := _forbidden_role(viewer, "admin")) is not None:
        return denied
    body = await _json(request)
    await svc.reset(body.get("server"))
    return JSONResponse({"ok": True})
