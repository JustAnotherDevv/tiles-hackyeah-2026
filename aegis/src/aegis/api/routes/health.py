"""GET /healthz (HealthResponse, CONTRACTS section 5.5) and HEAD|GET /api/hello.

`/healthz` is always 200: `status` = degraded if any component is `down` or `degraded`.
`/api/hello` answers Claude Code's warm-up probe locally (no upstream call, works offline).
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from aegis import __version__

router = APIRouter(tags=["health"])


@router.api_route("/healthz", methods=["GET", "HEAD"])
async def healthz(request: Request) -> dict[str, Any]:
    state = request.app.state
    rt = getattr(state, "rt", None)
    if rt is None:
        from aegis.core.discovery import plugin_errors

        return {
            "status": "degraded",
            "version": __version__,
            "uptime_s": round(time.time() - getattr(state, "started_at", time.time()), 3),
            "policy_version": 0,
            "feed_serial": None,
            "components": {"runtime": "down", "plugins": "degraded" if plugin_errors else "ok"},
        }
    try:
        await rt.probe_ollama()
    except Exception:
        pass
    components = rt.component_status()
    degraded = any(v in {"down", "degraded"} for v in components.values())
    return {
        "status": "degraded" if degraded else "ok",
        "version": __version__,
        "uptime_s": rt.uptime_s,
        "policy_version": rt.policy_version,
        "feed_serial": rt.feed_serial,
        "components": components,
    }


@router.get("/healthz/details", include_in_schema=False)
async def healthz_details(request: Request) -> dict[str, Any]:
    """Debug view: fallback reasons and plugin import errors (no secrets)."""
    from aegis.core.discovery import plugin_errors

    rt = getattr(request.app.state, "rt", None)
    return {
        "services": dict(getattr(rt, "status", {}) or {}),
        "errors": dict(getattr(rt, "errors", {}) or {}),
        "plugin_errors": list(plugin_errors),
        "routers": list(getattr(request.app.state, "router_modules", []) or []),
        "controls": sorted(c.id for c in rt.controls.all()) if rt and rt.controls else [],
    }


@router.api_route("/api/hello", methods=["GET", "HEAD"])
async def hello(request: Request) -> Response:
    if request.method == "HEAD":
        return Response(status_code=200, media_type="application/json")
    return JSONResponse({"ok": True})
