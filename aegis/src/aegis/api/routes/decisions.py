"""GET /api/decisions (Page<DecisionSummary>, newest first) · GET /api/decisions/{id}
(DecisionDetail incl. in-memory wire view + audit_seq/audit_hash). Owner: audit-metrics."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request

from aegis.audit import index as idx
from aegis.audit.log import open_db
from aegis.metrics.timing import iso_z, parse_since
from aegis.metrics.web import api_error, demo_mode, parse_bool, rt_of

log = logging.getLogger(__name__)

router = APIRouter(tags=["decisions"])


def _data_dir(rt: Any) -> Path:
    return Path(getattr(getattr(rt, "settings", None), "data_dir", None) or "data")


@router.get("/api/decisions")
async def list_decisions(
    request: Request,
    action: str | None = None,
    control_id: str | None = None,
    kind: str | None = None,
    surface: str | None = None,
    agent_id: str | None = None,
    team_id: str | None = None,
    member_id: str | None = None,
    since: str | None = None,
    q: str | None = None,
    synthetic: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    cursor: str | None = None,
) -> Any:
    rt = rt_of(request)
    if rt is None:
        return {"items": [], "next_cursor": None}
    since_dt = parse_since(since)
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
    except Exception as exc:
        log.exception("decisions query failed")
        return api_error(500, "internal_error", f"decisions query failed: {exc}")
    return {"items": items, "next_cursor": nxt}


@router.get("/api/decisions/{decision_id}")
async def get_decision(request: Request, decision_id: str) -> Any:
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
