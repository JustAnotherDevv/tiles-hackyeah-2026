"""/api/feed/* (threat-feed; CONTRACTS section 5.4 + Addendum A-49).

GET  /api/feed/status            member  -> FeedStatus
GET  /api/feed/signatures        member  -> {items: FeedSignatureView[] (+ extras)}
GET  /api/feed/signatures/{id}   member  -> full signature + quarantine_reason, hits_24h, self-test
POST /api/feed/refresh           admin   -> FeedStatus (clears an operator pin)
POST /api/feed/rollback          admin   {serial, reason} -> FeedStatus (re-verify cached, pin)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from aegis.core.types import FeedStatus, Identity

try:
    from aegis.core.deps import get_rt, require_role, viewer
    from aegis.core.errors import api_error
except Exception:  # TODO(integration): core-gateway deps missing -> permissive local fallbacks

    async def get_rt(request: Request) -> Any:  # type: ignore[misc]
        return getattr(request.app.state, "rt", None)

    async def viewer(request: Request) -> Identity:  # type: ignore[misc]
        return Identity(role="owner")

    def require_role(min_role: str) -> Any:  # type: ignore[misc]
        async def _dep(request: Request) -> Identity:
            return Identity(role="owner")

        return _dep

    def api_error(status: int, type: str, message: str, **fields: Any) -> JSONResponse:  # type: ignore[misc]
        return JSONResponse(
            {"error": {"type": type, "message": message, **fields}}, status_code=status
        )


router = APIRouter(tags=["feed"])
RT = Depends(get_rt)
VIEWER = Depends(viewer)
ADMIN = Depends(require_role("admin"))
ORDER = 100


def _feed(rt: Any) -> Any:
    return getattr(rt, "feed", None) if rt is not None else None


def _dump(st: Any) -> dict[str, Any]:
    if isinstance(st, FeedStatus):
        return st.model_dump(mode="json")
    return FeedStatus(status="disabled").model_dump(mode="json")


@router.get("/api/feed/status")
async def feed_status(rt: Any = RT, _: Identity = VIEWER) -> dict[str, Any]:
    feed = _feed(rt)
    return _dump(feed.status() if feed is not None else None)


@router.get("/api/feed/signatures")
async def feed_signatures(rt: Any = RT, _: Identity = VIEWER) -> dict[str, Any]:
    feed = _feed(rt)
    items = feed.signatures() if feed is not None else []
    return {"items": items, "feed_serial": getattr(feed, "serial", None) if feed else None}


@router.get("/api/feed/signatures/{sid}", response_model=None)
async def feed_signature(
    sid: str, rt: Any = RT, _: Identity = VIEWER
) -> dict[str, Any] | JSONResponse:
    feed = _feed(rt)
    detail = getattr(feed, "signature_detail", None)
    if detail is None:
        return api_error(501, "not_implemented", "feed manager without signature detail")
    out = detail(sid)
    if out is None:
        return api_error(404, "not_found", f"signature {sid} is not in the active feed")
    return out


@router.post("/api/feed/refresh")
async def feed_refresh(rt: Any = RT, _: Identity = ADMIN) -> dict[str, Any]:
    feed = _feed(rt)
    if feed is None:
        return _dump(None)
    return _dump(await feed.refresh())


@router.post("/api/feed/rollback", response_model=None)
async def feed_rollback(
    request: Request, rt: Any = RT, who: Identity = ADMIN
) -> dict[str, Any] | JSONResponse:
    feed = _feed(rt)
    fn = getattr(feed, "rollback", None)
    if fn is None:
        return api_error(501, "not_implemented", "feed manager without rollback")
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict) or not isinstance(body.get("serial"), int):
        return api_error(400, "invalid_request", "body must be {serial: int, reason?: str}")
    try:
        st = await fn(int(body["serial"]), actor=who, reason=body.get("reason"))
    except LookupError as e:
        return api_error(404, "not_found", str(e))
    except Exception as e:
        reason = getattr(e, "reason", None) or f"{type(e).__name__}: {e}"
        return api_error(409, "feed_rejected", str(reason)[:300])
    return _dump(st)
