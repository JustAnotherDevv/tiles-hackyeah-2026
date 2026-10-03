"""Route helpers for the audit-metrics routers.

Prefer core-gateway's public surfaces (`aegis.core.deps`, `aegis.core.errors`); fall back to
local equivalents so these routes work before/without them.
# TODO(integration): the fallbacks become dead code once aegis.core.deps/errors exist.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from aegis.core.types import ROLE_RANK, Identity

log = logging.getLogger(__name__)

try:  # core-gateway public surface (CONTRACTS 3.3)
    from aegis.core.errors import api_error as _core_api_error
except Exception:  # pragma: no cover - depends on build order
    _core_api_error = None

try:
    from aegis.core.deps import viewer as _core_viewer
except Exception:  # pragma: no cover
    _core_viewer = None


def api_error(status: int, type_: str, message: str, **fields: Any) -> JSONResponse:
    if _core_api_error is not None:
        try:
            return _core_api_error(status, type_, message, **fields)
        except Exception:
            log.debug("core api_error failed; using local envelope", exc_info=True)
    return JSONResponse(status_code=status, content={"error": {"type": type_, "message": message, **fields}})


def rt_of(request: Request) -> Any:
    rt = getattr(request.app.state, "rt", None)
    if rt is not None:
        return rt
    try:
        from aegis.core.runtime import get_runtime

        return get_runtime()
    except Exception:
        return None


async def viewer_of(request: Request) -> Identity:
    """Dashboard viewer (X-Aegis-View-As / ?view_as=) via rt.org.resolve_viewer."""
    rt = rt_of(request)
    org = getattr(rt, "org", None) if rt is not None else None
    if org is not None:
        try:
            return await org.resolve_viewer(request.headers, request.query_params)
        except Exception:
            log.debug("resolve_viewer failed", exc_info=True)
    view_as = request.headers.get("x-aegis-view-as") or request.query_params.get("view_as")
    # TODO(integration): Null org fallback = viewer is owner (CONTRACTS 3.3)
    return Identity(member_id=view_as or "u_katarzyna", role="owner", authenticated=False)


def has_role(viewer: Identity, min_role: str) -> bool:
    return ROLE_RANK.get(viewer.role, 0) >= ROLE_RANK.get(min_role, 99)


def forbidden(viewer: Identity, min_role: str, what: str) -> JSONResponse:
    return api_error(
        403,
        "forbidden",
        f"{what} needs role {min_role}; viewing as {viewer.member_id or viewer.principal} ({viewer.role})",
        required_role=min_role,
    )


def settings_of(rt: Any) -> Any:
    return getattr(rt, "settings", None)


def demo_mode(rt: Any) -> bool:
    return bool(getattr(settings_of(rt), "demo_mode", True))


def test_mode(rt: Any) -> bool:
    return bool(getattr(settings_of(rt), "test_mode", False))


def warmup_mode(rt: Any) -> str:
    import os

    value = getattr(settings_of(rt), "warmup", None) or os.environ.get("AEGIS_WARMUP") or "auto"
    return str(value).strip().lower()


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


__all__ = ["api_error", "demo_mode", "forbidden", "has_role", "parse_bool", "rt_of", "test_mode",
           "viewer_of", "warmup_mode"]
