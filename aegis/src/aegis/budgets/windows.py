"""Budget windows: calendar periods in `budgets.timezone` (default Europe/Warsaw, fallback UTC).

The clock is patchable for tests: `set_clock(fn)` / `set_monotonic(fn)`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, tzinfo
from functools import lru_cache
from typing import Any

DEFAULT_TZ = "Europe/Warsaw"
IDENTITY_WINDOWS: tuple[str, ...] = ("hour", "day", "week", "month", "total")
SESSION_WINDOWS: tuple[str, ...] = ("session",)

_now_fn: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731
_mono_fn: Callable[[], float] = time.monotonic


def now() -> datetime:
    return _now_fn()


def monotonic() -> float:
    return _mono_fn()


def set_clock(fn: Callable[[], datetime] | None) -> None:
    """Patch the wall clock (tests). None restores the real clock."""
    global _now_fn
    _now_fn = fn or (lambda: datetime.now(UTC))


def set_monotonic(fn: Callable[[], float] | None) -> None:
    global _mono_fn
    _mono_fn = fn or time.monotonic


@lru_cache(maxsize=16)
def _zone(name: str) -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return UTC


def zone(snapshot: Any = None) -> tzinfo:
    """Timezone for calendar windows from `budgets.timezone` (extra key) of a snapshot/doc."""
    name = DEFAULT_TZ
    try:
        doc = getattr(snapshot, "doc", snapshot)
        budgets = getattr(doc, "budgets", None)
        extra = getattr(budgets, "model_extra", None) or {}
        name = str(extra.get("timezone") or DEFAULT_TZ)
    except Exception:
        name = DEFAULT_TZ
    return _zone(name)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_start(window: str, at: datetime, tz: tzinfo) -> datetime | None:
    local = at.astimezone(tz)
    if window == "hour":
        start = local.replace(minute=0, second=0, microsecond=0)
    elif window == "day":
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    elif window == "week":
        day = local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = day - timedelta(days=day.weekday())
    elif window == "month":
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        return None
    # re-localize (DST-safe): build a naive wall time and attach the zone again
    return start.replace(tzinfo=None).replace(tzinfo=tz)


def window_start(window: str, at: datetime | None = None, tz: tzinfo | None = None) -> str:
    """UTC ISO of the local period start; "session" / "total" for those windows."""
    if window in ("session", "total"):
        return window
    at = at or now()
    tz = tz or _zone(DEFAULT_TZ)
    start = _local_start(window, at, tz)
    if start is None:
        return "total"
    return iso(start)


def window_start_dt(
    window: str, at: datetime | None = None, tz: tzinfo | None = None
) -> datetime | None:
    if window in ("session", "total"):
        return None
    at = at or now()
    start = _local_start(window, at, tz or _zone(DEFAULT_TZ))
    return start.astimezone(UTC) if start else None


def resets_at(window: str, at: datetime | None = None, tz: tzinfo | None = None) -> datetime | None:
    """Start of the next period (UTC) or None for session / total windows."""
    if window in ("session", "total"):
        return None
    at = at or now()
    tz = tz or _zone(DEFAULT_TZ)
    start = _local_start(window, at, tz)
    if start is None:
        return None
    naive = start.replace(tzinfo=None)
    if window == "hour":
        nxt = naive + timedelta(hours=1)
    elif window == "day":
        nxt = naive + timedelta(days=1)
    elif window == "week":
        nxt = naive + timedelta(days=7)
    else:  # month
        nxt = (naive.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt.replace(tzinfo=tz).astimezone(UTC)


def windows_for(scope_type: str) -> tuple[str, ...]:
    return SESSION_WINDOWS if scope_type == "session" else IDENTITY_WINDOWS


__all__ = [
    "DEFAULT_TZ",
    "iso",
    "monotonic",
    "now",
    "resets_at",
    "set_clock",
    "set_monotonic",
    "window_start",
    "window_start_dt",
    "windows_for",
    "zone",
]
