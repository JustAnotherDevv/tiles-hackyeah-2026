"""Budget events: threshold crossings (50/80/100 + warn_pct), coalesced `budget.updated`,
audit helpers and Prometheus gauges. Every side effect is best-effort (never raises)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from aegis.core.types import AuditEvent, Identity, new_id

from . import windows

log = logging.getLogger(__name__)

DEFAULT_LEVELS: tuple[float, ...] = (50.0, 80.0, 100.0)


class ThresholdTracker:
    """Fires each level once per (scope, window instance, dimension)."""

    def __init__(self, max_entries: int = 50_000) -> None:
        self._fired: set[tuple[str, str, str, str, float]] = set()
        self.max_entries = max_entries

    def crossings(
        self,
        key: tuple[str, str, str, str],
        pct: float,
        levels: tuple[float, ...] | list[float] = DEFAULT_LEVELS,
    ) -> list[float]:
        out: list[float] = []
        for lvl in levels:
            if pct + 1e-9 >= lvl:
                k = (*key, float(lvl))
                if k not in self._fired:
                    self._fired.add(k)
                    out.append(float(lvl))
        if len(self._fired) > self.max_entries:
            self._fired.clear()
        return out

    def clear(self, scope: str | None = None) -> None:
        if scope is None:
            self._fired.clear()
        else:
            self._fired = {k for k in self._fired if k[0] != scope}


class UpdateCoalescer:
    """Publishes `budget.updated` at most `max_per_s` times per second (immediately in test mode).

    `publish(scopes)` is a sync callback that builds and publishes the statuses of `scopes`
    (None = everything).
    """

    def __init__(
        self,
        publish: Callable[[set[str] | None], None],
        *,
        max_per_s: float = 2.0,
        immediate: bool = False,
    ) -> None:
        self._publish = publish
        self.min_interval = 1.0 / max(0.1, max_per_s)
        self.immediate = immediate
        self._dirty: set[str] = set()
        self._all = False
        self._last = 0.0
        self._handle: asyncio.TimerHandle | None = None

    def mark(self, scopes: set[str] | None) -> None:
        if scopes is None:
            self._all = True
        else:
            self._dirty |= scopes
        if self.immediate:
            self.flush()
            return
        if self._handle is not None:
            return
        wait = self._last + self.min_interval - windows.monotonic()
        if wait <= 0:
            self.flush()
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.flush()
            return
        self._handle = loop.call_later(wait, self.flush)

    def flush(self) -> None:
        self._handle = None
        if not self._dirty and not self._all:
            return
        scopes = None if self._all else set(self._dirty)
        self._dirty.clear()
        self._all = False
        self._last = windows.monotonic()
        try:
            self._publish(scopes)
        except Exception:
            log.exception("budget.updated publish failed")

    def cancel(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None


def publish(rt: Any, event: str, data: Any) -> None:
    bus = getattr(rt, "bus", None)
    if bus is None:
        return
    try:
        bus.publish(event, data)
    except Exception:
        log.warning("bus publish failed event=%s", event, exc_info=True)


async def audit_event(
    rt: Any,
    event_type: str,
    *,
    data: dict[str, Any],
    actor: Identity | None = None,
    reason: str | None = None,
    control_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    policy_version: int | None = None,
    action: str | None = None,
) -> None:
    audit = getattr(rt, "audit", None)
    if audit is None:
        return
    try:
        await audit.record(
            AuditEvent(
                event_id=new_id("evt"),
                event_type=event_type,  # type: ignore[arg-type]
                actor=actor,
                reason=reason,
                control_id=control_id,
                session_id=session_id,
                request_id=request_id,
                policy_version=policy_version,
                action=action,  # type: ignore[arg-type]
                data=data,
            )
        )
    except Exception:
        log.warning("audit record failed event_type=%s", event_type, exc_info=True)


def spawn(coro: Any) -> asyncio.Task[Any] | None:
    """Fire-and-forget a coroutine on the running loop (kept alive until done)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return None
    task = loop.create_task(coro)
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    return task


_BACKGROUND: set[asyncio.Task[Any]] = set()


def set_gauge(rt: Any, name: str, value: float, labels: dict[str, str] | None = None) -> None:
    metrics = getattr(rt, "metrics", None)
    if metrics is None:
        return
    try:
        metrics.set_gauge(name, value, labels)
    except Exception:
        log.debug("gauge failed name=%s", name, exc_info=True)


def inc(rt: Any, name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
    metrics = getattr(rt, "metrics", None)
    if metrics is None:
        return
    try:
        metrics.inc(name, labels, value)
    except Exception:
        log.debug("counter failed name=%s", name, exc_info=True)


__all__ = [
    "DEFAULT_LEVELS",
    "ThresholdTracker",
    "UpdateCoalescer",
    "audit_event",
    "inc",
    "publish",
    "set_gauge",
    "spawn",
]
