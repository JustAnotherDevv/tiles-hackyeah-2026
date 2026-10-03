"""GET /healthz, HEAD|GET /api/hello (Claude Code probe).

SCAFFOLD STUB - owned by core-gateway, safe to extend/replace. Returns the `HealthResponse`
shape (CONTRACTS section 5.5); 200 even when degraded.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request, Response

from aegis import __version__

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, Any]:
    state = request.app.state
    components: dict[str, str] = {
        "plugins": "degraded" if getattr(state, "plugin_errors", None) else "ok",
        "runtime": "ok" if getattr(state, "rt", None) is not None else "off",
    }
    degraded = any(v in {"degraded", "down"} for v in components.values())
    return {
        "status": "degraded" if degraded else "ok",
        "version": __version__,
        "uptime_s": round(time.time() - getattr(state, "started_at", time.time()), 3),
        "policy_version": 0,
        "feed_serial": None,
        "components": components,
    }


@router.api_route("/api/hello", methods=["GET", "HEAD"])
async def hello() -> Response:
    return Response(status_code=200)
