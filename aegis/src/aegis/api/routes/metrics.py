"""GET /metrics - Prometheus exposition (CONTRACTS section 6.4). Owner: audit-metrics."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Response

from aegis.metrics.web import rt_of

log = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics(request: Request) -> Any:
    rt = rt_of(request)
    m = getattr(rt, "metrics", None) if rt is not None else None
    if m is None:
        return Response(b"", media_type="text/plain; version=0.0.4; charset=utf-8")
    refresh = getattr(m, "refresh_gauges", None)
    if refresh is not None:
        try:
            await refresh(rt)
        except Exception:
            log.debug("refresh_gauges failed", exc_info=True)
    try:
        body, ctype = m.render()
    except Exception:
        log.exception("metrics render failed")
        body, ctype = b"", "text/plain; version=0.0.4; charset=utf-8"
    return Response(content=body, media_type=ctype)
