"""`POST /v1/hooks/claude-code` - Claude Code hook endpoint (owner: claude-code-integration).

Body = raw Claude Code hook JSON (forwarded by `scripts/aegis-hook`). Response = Claude Code
hook-output JSON, **always 200** (`{}` = no opinion). Blocking events fail closed on any error.
Additive (gap G7): `GET /v1/hooks/claude-code/status` for check.sh / demo preflight.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from aegis.integrations.claude_code import handle_hook, hook_status
from aegis.integrations.claude_code.handler import MAX_BODY_BYTES
from aegis.integrations.claude_code.respond import fail_closed_output

log = logging.getLogger(__name__)

ORDER = 100
router = APIRouter(tags=["claude-code"])


async def rt_or_none(request: Request) -> Any:
    """`aegis.core.deps.get_rt`, but never raises (the hook must always get a 200)."""
    try:
        from aegis.core.deps import get_rt
    except Exception:  # TODO(integration): core deps missing -> app.state.rt
        return getattr(request.app.state, "rt", None)
    try:
        return await get_rt(request)
    except Exception:
        return None


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.post("/v1/hooks/claude-code")
async def claude_code_hook(request: Request, rt: Any = Depends(rt_or_none)) -> JSONResponse:
    event = request.headers.get("x-aegis-hook-event", "")
    try:
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > MAX_BODY_BYTES:
                log.warning("claude code hook body too large event=%s", event or "?")
                return JSONResponse(fail_closed_output(event, "hook payload too large"))
        out = await handle_hook(rt, raw, request.headers, _base_url(request))
    except Exception:
        log.exception("claude code hook route failed event=%s", event or "?")
        out = fail_closed_output(event, "decision unavailable")
    return JSONResponse(out, headers={"cache-control": "no-store"})


@router.get("/v1/hooks/claude-code/status")
async def claude_code_hook_status(rt: Any = Depends(rt_or_none)) -> dict[str, Any]:
    return hook_status(rt)
