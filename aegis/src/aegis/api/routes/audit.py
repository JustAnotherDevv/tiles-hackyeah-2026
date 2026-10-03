"""GET /api/audit · GET /api/audit/export (admin) · GET /api/audit/verify  (owner: audit-metrics)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from aegis.audit.export import EXTENSIONS, MEDIA_TYPES, export_stream
from aegis.core.types import AuditVerifyResult, utcnow
from aegis.metrics.timing import iso_z
from aegis.metrics.web import api_error, forbidden, has_role, rt_of, viewer_of

log = logging.getLogger(__name__)

router = APIRouter(tags=["audit"])


def _audit(request: Request) -> Any:
    rt = rt_of(request)
    return getattr(rt, "audit", None) if rt is not None else None


@router.get("/api/audit")
async def list_audit(
    request: Request,
    event_type: str | None = None,
    since: str | None = None,
    decision_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    cursor: str | None = None,
    seq_from: int | None = Query(None, ge=1),
) -> Any:
    audit = _audit(request)
    if audit is None:
        return {"items": [], "next_cursor": None}
    raw = getattr(audit, "query_raw", None)
    try:
        if raw is not None:
            items, nxt = await raw(
                event_type=event_type,
                since=since,
                decision_id=decision_id,
                limit=limit,
                cursor=cursor,
                seq_from=seq_from,
            )
            return {"items": items, "next_cursor": nxt}
        events, nxt = await audit.query(
            event_type=event_type, since=since, limit=limit, cursor=cursor
        )
        return {
            "items": [e.model_dump(mode="json", by_alias=True) for e in events],
            "next_cursor": nxt,
        }
    except Exception as exc:
        log.exception("audit query failed")
        return api_error(500, "internal_error", f"audit query failed: {exc}")


@router.get("/api/audit/verify")
async def verify_audit(request: Request) -> Any:
    audit = _audit(request)
    if audit is None:
        return AuditVerifyResult(ok=False, message="audit disabled").model_dump(mode="json")
    res = await audit.verify()
    return res.model_dump(mode="json")


@router.get("/api/audit/export")
async def export_audit(
    request: Request,
    format: str = Query("jsonl", pattern="^(jsonl|csv|ocsf)$"),
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    action: str | None = None,
    control_id: str | None = None,
    agent_id: str | None = None,
    event_type: str | None = None,
) -> Any:
    viewer = await viewer_of(request)
    if not has_role(viewer, "admin"):
        return forbidden(viewer, "admin", "Audit export")
    audit = _audit(request)
    if audit is None or not hasattr(audit, "audit_dir"):
        return api_error(503, "unavailable", "audit log disabled")
    filters = {
        "from": from_,
        "to": to,
        "action": action,
        "control_id": control_id,
        "agent_id": agent_id,
        "event_type": event_type,
    }
    filters = {k: v for k, v in filters.items() if v}
    # verify before export when the cached result is older than 60 s
    lv = getattr(audit, "last_verify", None)
    stale = lv is None or (utcnow() - lv.checked_at).total_seconds() > 60
    if stale:
        lv = await audit.verify()
    if hasattr(audit, "system"):  # the export itself is audited (and included in this export)
        try:
            await audit.system(
                "audit.export",
                f"audit exported as {format} by {viewer.member_id}",
                actor=viewer,
                format=format,
                filters=filters,
                by=viewer.member_id,
            )
        except Exception:
            log.exception("audit export self-audit failed")
    head = audit.head() if hasattr(audit, "head") else {"seq": 0, "hash": ""}
    date = iso_z()[:10].replace("-", "")
    fname = f"aegis-audit-{date}.{EXTENSIONS[format]}"
    headers = {
        "Content-Disposition": f'attachment; filename="{fname}"',
        "X-Aegis-Audit-Head": str(head.get("hash") or ""),
        "X-Aegis-Audit-Records": str(head.get("seq") or 0),
        "X-Aegis-Audit-Verified": "ok" if (lv is not None and lv.ok) else "broken",
        "Cache-Control": "no-store",
    }
    return StreamingResponse(
        export_stream(audit.audit_dir, format, **filters),
        media_type=MEDIA_TYPES[format],
        headers=headers,
    )
