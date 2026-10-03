"""Time helpers shared by audit + metrics (UTC everywhere, millisecond precision, 'Z' suffix).

`iso_z()` is the single formatter for every timestamp we persist in SQLite so string range
comparisons and `strftime('%s', ts)` bucketing agree with the Python side.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

#: window -> (span seconds, bucket seconds); 60 / 96 / 56 buckets (CONTRACTS section 5.4)
WINDOWS: dict[str, tuple[int, int]] = {
    "1h": (3600, 60),
    "24h": (86400, 900),
    "7d": (7 * 86400, 3 * 3600),
}

_REL = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(s|m|h|d|w)\s*$", re.IGNORECASE)
_UNIT_S = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc(value: Any) -> datetime | None:
    """datetime | ISO string | epoch (s or ms) -> aware UTC datetime (None if unparseable)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, (int, float)):
        secs = float(value)
        if secs > 1e11:  # epoch milliseconds
            secs /= 1000.0
        return datetime.fromtimestamp(secs, UTC)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if s.endswith(("Z", "z")):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:
                return to_utc(float(s))
            except ValueError:
                return None
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return None


def iso_z(value: Any = None) -> str:
    """'YYYY-MM-DDTHH:MM:SS.mmmZ' (UTC). None -> now."""
    dt = utc_now() if value is None else (to_utc(value) or utc_now())
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_since(value: str | None, now: datetime | None = None) -> datetime | None:
    """'15m' / '1h' / '24h' / '7d' (relative to now) or an ISO timestamp / epoch."""
    if value is None or str(value).strip() == "":
        return None
    m = _REL.match(str(value))
    if m:
        secs = float(m.group(1)) * _UNIT_S[m.group(2).lower()]
        return (now or utc_now()) - timedelta(seconds=secs)
    return to_utc(value)


def bucket_starts(window: str, now: datetime | None = None) -> tuple[list[int], int]:
    """Epoch-aligned bucket start times (oldest first) and the bucket size for a window."""
    span, step = WINDOWS[window]
    n = span // step
    t = int((now or utc_now()).timestamp())
    last = (t // step) * step
    first = last - (n - 1) * step
    return [first + i * step for i in range(n)], step


def epoch_iso(epoch_s: float) -> str:
    return iso_z(datetime.fromtimestamp(epoch_s, UTC))


__all__ = [
    "WINDOWS",
    "bucket_starts",
    "epoch_iso",
    "iso_z",
    "parse_since",
    "to_utc",
    "utc_now",
]
