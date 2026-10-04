"""GET /api/events — the live SSE stream (CONTRACTS sections 5.4 and 6.3).

Query: `events=decision,approval.created` (filter), `replay=<n>` (last n ring-buffer messages),
`view_as` (accepted; all members may read). Header `Last-Event-ID` resumes from the ring buffer.
Wire format `id: <bus id>\\nevent: <name>\\ndata: <json>\\n\\n`. A per-connection `heartbeat`
`{ts}` event is sent every 15 s (never stored in the ring buffer).

`event_stream()` is a plain async generator so tests can drive it without a server
(ASGI test transports buffer streaming bodies).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from aegis.core.types import BusMessage, utcnow

log = logging.getLogger(__name__)

router = APIRouter(tags=["events"])

HEARTBEAT_S = 15.0
MAX_REPLAY = 1000


def _frame(msg: BusMessage) -> dict[str, str]:
    return {
        "id": str(msg.id),
        "event": msg.event,
        "data": json.dumps(msg.data, ensure_ascii=False, separators=(",", ":"), default=str),
    }


def _heartbeat() -> dict[str, str]:
    ts = utcnow().isoformat().replace("+00:00", "Z")
    return {"event": "heartbeat", "data": json.dumps({"ts": ts})}


def parse_events(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    names = {p.strip() for p in raw.split(",") if p.strip()}
    return names or None


async def event_stream(
    bus: Any,
    *,
    events: set[str] | None = None,
    replay: int = 0,
    last_id: int | None = None,
    heartbeat_s: float = HEARTBEAT_S,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[dict[str, str]]:
    """Yield SSE frames: backlog, then live bus messages interleaved with heartbeats."""
    want_heartbeat = events is None or "heartbeat" in events
    bus_events = None if events is None else {e for e in events if e != "heartbeat"}
    if events is not None and not bus_events:
        bus_events = {"__none__"}
    source = bus.subscribe(bus_events, replay=max(0, min(MAX_REPLAY, replay)), last_id=last_id)
    pending: asyncio.Future[BusMessage] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(source.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_s)
            if not done:
                if is_disconnected is not None and await is_disconnected():
                    return
                if want_heartbeat:
                    yield _heartbeat()
                continue
            fut, pending = pending, None
            try:
                msg = fut.result()
            except StopAsyncIteration:
                return
            yield _frame(msg)
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                await pending
        with contextlib.suppress(Exception):
            await source.aclose()


@router.get("/api/events")
async def events_endpoint(
    request: Request,
    events: str | None = Query(default=None, description="comma-separated event names"),
    replay: int = Query(default=0, ge=0, le=MAX_REPLAY),
    view_as: str | None = Query(default=None),
    last_event_id: int | None = Query(default=None, include_in_schema=False),
) -> EventSourceResponse:
    from aegis.core.deps import get_rt

    rt = await get_rt(request)
    with contextlib.suppress(Exception):  # viewer resolved for RBAC/audit; every member may read
        await rt.org.resolve_viewer(request.headers, dict(request.query_params))
    header_id = request.headers.get("last-event-id")
    last_id: int | None = last_event_id
    if header_id:
        try:
            last_id = int(header_id)
        except ValueError:
            last_id = None
    stream = event_stream(
        rt.bus,
        events=parse_events(events),
        replay=replay,
        last_id=last_id,
        is_disconnected=request.is_disconnected,
    )
    return EventSourceResponse(
        stream,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        ping=3600,
    )
