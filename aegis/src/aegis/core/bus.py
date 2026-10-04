"""In-process event bus (`rt.bus`, CONTRACTS sections 3.2 and 6.3).

- Ring buffer of the last 1000 messages with monotonic integer ids (SSE `id:` / `Last-Event-ID`).
- `publish(event, data)` is non-blocking and thread-safe (pydantic models are dumped with
  `mode="json", by_alias=True`); delivery to subscribers on other loops/threads goes through
  `call_soon_threadsafe`.
- `subscribe(events, replay=n, last_id=None)` → async iterator with a bounded per-subscriber
  queue; a slow subscriber never blocks publishers (drop-oldest, counted in `dropped`).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections import deque
from collections.abc import AsyncIterator, Iterable
from typing import Any

from pydantic import BaseModel

from aegis.core.types import BusMessage, utcnow

log = logging.getLogger(__name__)

RING_SIZE = 1000
QUEUE_SIZE = 1000

_CLOSE = object()


def _dump(data: Any) -> dict[str, Any]:
    if data is None:
        return {}
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json", by_alias=True)
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for k, v in data.items():
            out[str(k)] = _dump_value(v)
        return out
    return {"value": _dump_value(data)}


def _dump_value(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return v.model_dump(mode="json", by_alias=True)
    if isinstance(v, dict):
        return {str(k): _dump_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_dump_value(x) for x in v]
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


class _Subscriber:
    __slots__ = ("dropped", "events", "loop", "queue")

    def __init__(self, events: set[str] | None, loop: asyncio.AbstractEventLoop) -> None:
        self.events = events
        self.loop = loop
        self.queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.dropped = 0

    def wants(self, msg: BusMessage) -> bool:
        return not self.events or msg.event in self.events

    def deliver(self, item: Any) -> None:
        """Runs on the subscriber's loop."""
        q = self.queue
        while True:
            try:
                q.put_nowait(item)
                return
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                    self.dropped += 1


class EventBus:
    """Ring-buffered pub/sub. One instance per Runtime."""

    def __init__(self, ring_size: int = RING_SIZE) -> None:
        self._lock = threading.Lock()
        self._ring: deque[BusMessage] = deque(maxlen=ring_size)
        self._next_id = 1
        self._subs: set[_Subscriber] = set()
        self._closed = False
        self.published = 0

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self._closed = False

    async def stop(self) -> None:
        self.close()

    def health(self) -> str:
        return "ok"

    def close(self) -> None:
        """Wake every subscriber with an end-of-stream marker (shutdown)."""
        self._closed = True
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            self._dispatch(sub, _CLOSE)

    # ------------------------------------------------------------------ publish
    def publish(self, event: str, data: Any = None) -> BusMessage:
        payload = _dump(data)
        with self._lock:
            msg = BusMessage(id=self._next_id, event=event, data=payload, ts=utcnow())
            self._next_id += 1
            self._ring.append(msg)
            subs = [s for s in self._subs if s.wants(msg)]
            self.published += 1
        for sub in subs:
            self._dispatch(sub, msg)
        return msg

    def _dispatch(self, sub: _Subscriber, item: Any) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is sub.loop:
            sub.deliver(item)
            return
        try:
            sub.loop.call_soon_threadsafe(sub.deliver, item)
        except RuntimeError:  # loop closed
            with self._lock:
                self._subs.discard(sub)

    # ------------------------------------------------------------------ read
    def recent(self, n: int = 100, events: set[str] | Iterable[str] | None = None) -> list[BusMessage]:
        wanted = set(events) if events else None
        with self._lock:
            items = list(self._ring)
        if wanted:
            items = [m for m in items if m.event in wanted]
        return items[-n:] if n > 0 else []

    def since(self, last_id: int, events: set[str] | Iterable[str] | None = None) -> list[BusMessage]:
        """Ring-buffer messages with id > last_id (for SSE `Last-Event-ID` resume)."""
        wanted = set(events) if events else None
        with self._lock:
            items = [m for m in self._ring if m.id > last_id]
        if wanted:
            items = [m for m in items if m.event in wanted]
        return items

    @property
    def last_id(self) -> int:
        return self._next_id - 1

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    async def subscribe(
        self,
        events: set[str] | Iterable[str] | None = None,
        *,
        replay: int = 0,
        last_id: int | None = None,
    ) -> AsyncIterator[BusMessage]:
        """Async iterator: optional backlog (replay n / since last_id), then live messages."""
        wanted = set(events) if events else None
        sub = _Subscriber(wanted, asyncio.get_running_loop())
        with self._lock:
            self._subs.add(sub)
            ring = list(self._ring)
        try:
            if last_id is not None:
                backlog = [m for m in ring if m.id > last_id]
            elif replay > 0:
                backlog = ring
            else:
                backlog = []
            if wanted:
                backlog = [m for m in backlog if m.event in wanted]
            if last_id is None and replay > 0:
                backlog = backlog[-replay:]
            seen = last_id or 0
            for msg in backlog:
                seen = max(seen, msg.id)
                yield msg
            if not backlog and ring:
                seen = max(seen, ring[-1].id if last_id is None else seen)
            while True:
                item = await sub.queue.get()
                if item is _CLOSE:
                    return
                if item.id <= seen:
                    continue
                seen = item.id
                yield item
        finally:
            with self._lock:
                self._subs.discard(sub)
            if sub.dropped:
                log.warning("bus subscriber dropped messages count=%d", sub.dropped)


def create(rt: Any = None) -> EventBus:
    """Service factory (`rt.bus`)."""
    return EventBus()


__all__ = ["QUEUE_SIZE", "RING_SIZE", "EventBus", "create"]
