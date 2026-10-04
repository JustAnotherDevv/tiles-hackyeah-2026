"""GET /api/decisions (Page<DecisionSummary>, newest first) · GET /api/decisions/{id}
(DecisionDetail incl. in-memory wire view + audit_seq/audit_hash). Owner: audit-metrics."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi import Path as PathParam

from aegis.audit import index as idx
from aegis.audit.log import open_db
from aegis.metrics.timing import iso_z, parse_since
from aegis.metrics.web import api_error, demo_mode, parse_bool, rt_of

log = logging.getLogger(__name__)

router = APIRouter(tags=["decisions"])

# R8/R13: bound filters; SQLite INTEGER is signed 64-bit (cursor rowid).
MAX_ROWID = 2**63 - 1
MAX_FILTER_LEN = 200


def _since(since: str | None) -> tuple[Any, str | None]:
    """(datetime | None, error). Unparseable `since` used to be silently ignored."""
    if since is None or not since.strip():
        return None, None
    try:
        dt = parse_since(since)
    except (ValueError, OverflowError, OSError):
        dt = None
    if dt is None:
        return None, (
            f"invalid since {since[:40]!r} (use 15m / 1h / 24h / 7d, an ISO timestamp or epoch)"
        )
    return dt, None


def _cursor_error(cursor: str | None) -> str | None:
    if not cursor:
        return None
    parts = idx.decode_cursor(cursor)
    if parts and len(parts) == 2 and parts[0] and (
        not parts[1].isdigit() or int(parts[1]) <= MAX_ROWID
    ):
        return None
    return "invalid cursor (use next_cursor from a previous page)"


def _data_dir(rt: Any) -> Path:
    return Path(getattr(getattr(rt, "settings", None), "data_dir", None) or "data")


@router.get("/api/decisions")
async def list_decisions(
    request: Request,
    action: str | None = Query(None, max_length=MAX_FILTER_LEN),
    control_id: str | None = Query(None, max_length=MAX_FILTER_LEN),
    kind: str | None = Query(None, max_length=MAX_FILTER_LEN),
    surface: str | None = Query(None, max_length=MAX_FILTER_LEN),
    agent_id: str | None = Query(None, max_length=MAX_FILTER_LEN),
    team_id: str | None = Query(None, max_length=MAX_FILTER_LEN),
    member_id: str | None = Query(None, max_length=MAX_FILTER_LEN),
    since: str | None = Query(None, max_length=64),
    q: str | None = Query(None, max_length=500),
    synthetic: str | None = Query(None, max_length=16),
    limit: int = Query(100, ge=1, le=1000),
    cursor: str | None = Query(None, max_length=512),
) -> Any:
    since_dt, err = _since(since)
    if err := err or _cursor_error(cursor):
        return api_error(400, "invalid_request", err)
    rt = rt_of(request)
    if rt is None:
        return {"items": [], "next_cursor": None}
    include_synth = parse_bool(synthetic, demo_mode(rt))

    def _q() -> tuple[list[dict[str, Any]], str | None]:
        conn = open_db(rt, _data_dir(rt))
        try:
            idx.ensure_schema(conn)
            return idx.query_decisions(
                conn,
                action=action,
                control_id=control_id,
                kind=kind,
                surface=surface,
                agent_id=agent_id,
                team_id=team_id,
                member_id=member_id,
                since=iso_z(since_dt) if since_dt else None,
                q=q,
                include_synthetic=include_synth,
                limit=limit,
                cursor=cursor,
            )
        finally:
            conn.close()

    try:
        items, nxt = await asyncio.to_thread(_q)
    except Exception as exc:  # never echo the raw exception text to the client
        log.exception("decisions query failed")
        return api_error(500, "internal_error", f"decisions query failed ({type(exc).__name__})")
    return {"items": items, "next_cursor": nxt}


@router.get("/api/decisions/{decision_id}")
async def get_decision(
    request: Request, decision_id: str = PathParam(max_length=MAX_FILTER_LEN)
) -> Any:
    rt = rt_of(request)
    if rt is None:
        return api_error(404, "not_found", f"decision {decision_id} not found")

    def _q() -> dict[str, Any] | None:
        conn = open_db(rt, _data_dir(rt))
        try:
            idx.ensure_schema(conn)
            return idx.get_decision(conn, decision_id)
        finally:
            conn.close()

    try:
        detail = await asyncio.to_thread(_q)
    except Exception:
        log.exception("decision lookup failed id=%s", decision_id)
        detail = None
    if detail is None:  # just written / DB unavailable -> in-memory LRU of recent details
        recent = getattr(getattr(rt, "audit", None), "recent_detail", None)
        if recent is not None:
            try:
                detail = recent(decision_id)
            except Exception:
                detail = None
    if detail is None:
        return api_error(404, "not_found", f"decision {decision_id} not found")
    detail.pop("synthetic", None)
    for key in ("decisions", "redactions", "mutations"):
        detail.setdefault(key, [])
    detail.setdefault("usage", None)
    detail.setdefault("audit_seq", None)
    detail.setdefault("audit_hash", None)
    wire = None
    pipeline = getattr(rt, "pipeline", None)
    if pipeline is not None:
        try:
            w = pipeline.wire(decision_id)
            if w is not None:
                wire = w.model_dump(mode="json") if hasattr(w, "model_dump") else w
        except Exception:
            wire = None
    detail["wire"] = wire
    return detail
