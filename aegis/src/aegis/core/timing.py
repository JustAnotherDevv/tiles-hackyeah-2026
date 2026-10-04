"""Request timing helpers and the `Server-Timing` header (CONTRACTS section 5.2).

Owner: core-gateway (bundle B02). Imported by the pipeline (B01), the model proxies and any
surface handler that wants per-request telemetry. Pure helpers, no I/O, no import-time effects.

Conventions for `RequestContext.timings` (stage -> milliseconds, accumulated with `add_timing`):

* ``ctl``          total control time of every pipeline evaluation in this request
* ``ctl.<ID>``     per-control time (e.g. ``ctl.DLP-01``)
* ``upstream``     time spent waiting for the model / tool upstream
* ``pipeline``     wall time inside `rt.pipeline.evaluate` (request + response hops)
* anything else    free-form phases (``enrich``, ``semantic``, ``parse``, ``stream`` ...)

`server_timing_header(ctx)` renders e.g.
``aegis;dur=1.84;desc="gateway overhead", ctl;dur=0.92, upstream;dur=812.30, total;dur=814.14,
ctl-DLP-01;dur=0.41`` where ``aegis`` = total wall time minus upstream time.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

__all__ = [
    "Stopwatch",
    "add_timing",
    "elapsed_ms",
    "overhead_ms",
    "server_timing_header",
    "timed",
]

_TOKEN_BAD = re.compile(r"[^A-Za-z0-9!#$%&'*+.^_`|~-]")


def _timings(ctx: Any) -> dict[str, float] | None:
    t = getattr(ctx, "timings", None)
    if t is None and isinstance(ctx, dict):
        t = ctx
    return t if isinstance(t, dict) else None


def add_timing(ctx: Any, key: str, ms: float) -> None:
    """Accumulate `ms` under `key` in `ctx.timings` (a RequestContext or a plain dict)."""
    t = _timings(ctx)
    if t is None:
        return
    try:
        t[key] = round(float(t.get(key, 0.0)) + float(ms), 3)
    except (TypeError, ValueError):
        t[key] = round(float(ms), 3)


def elapsed_ms(ctx: Any) -> float:
    """Milliseconds since `ctx.t0` (perf_counter at ingress); 0.0 when t0 is unset."""
    t0 = float(getattr(ctx, "t0", 0.0) or 0.0)
    if t0 <= 0.0:
        return 0.0
    return max(0.0, (time.perf_counter() - t0) * 1000.0)


def overhead_ms(ctx: Any, *, total_ms: float | None = None, upstream_ms: float | None = None) -> float:
    """Gateway overhead = total wall time minus upstream time (never negative)."""
    total = elapsed_ms(ctx) if total_ms is None else total_ms
    t = _timings(ctx) or {}
    up = upstream_ms if upstream_ms is not None else float(t.get("upstream", 0.0) or 0.0)
    return max(0.0, total - up)


class Stopwatch:
    """`perf_counter` stopwatch with laps.

    >>> sw = Stopwatch(); ...; ms = sw.lap("parse"); total = sw.ms
    """

    __slots__ = ("_last", "laps", "t0")

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self._last = self.t0
        self.laps: dict[str, float] = {}

    @property
    def ms(self) -> float:
        """Milliseconds since construction (or the last `reset`)."""
        return (time.perf_counter() - self.t0) * 1000.0

    @property
    def seconds(self) -> float:
        return time.perf_counter() - self.t0

    def lap(self, key: str | None = None) -> float:
        """Milliseconds since the previous lap; recorded under `key` when given."""
        now = time.perf_counter()
        ms = (now - self._last) * 1000.0
        self._last = now
        if key:
            self.laps[key] = self.laps.get(key, 0.0) + ms
        return ms

    def reset(self) -> None:
        self.t0 = self._last = time.perf_counter()
        self.laps.clear()

    def flush(self, ctx: Any, prefix: str = "") -> None:
        """Add every recorded lap to `ctx.timings` (optionally prefixed)."""
        for key, ms in self.laps.items():
            add_timing(ctx, f"{prefix}{key}", ms)


@contextmanager
def timed(ctx: Any, key: str) -> Iterator[Stopwatch]:
    """`with timed(ctx, "parse"): ...` adds the block's wall time to `ctx.timings[key]`."""
    sw = Stopwatch()
    try:
        yield sw
    finally:
        add_timing(ctx, key, sw.ms)


def _token(name: str) -> str:
    return _TOKEN_BAD.sub("-", name) or "x"


def _fmt(ms: float) -> str:
    return f"{max(0.0, float(ms)):.2f}"


def server_timing_header(
    ctx: Any,
    *,
    total_ms: float | None = None,
    upstream_ms: float | None = None,
    top_controls: int = 8,
    extra: Mapping[str, float] | None = None,
) -> str:
    """Render the `Server-Timing` header for a data-plane response.

    Always contains ``aegis`` (overhead), ``ctl`` (control time) and ``upstream``; adds
    ``total``, the ``top_controls`` slowest ``ctl-<ID>`` entries and any `extra` entries.
    """
    t = dict(_timings(ctx) or {})
    total = elapsed_ms(ctx) if total_ms is None else float(total_ms)
    up = float(upstream_ms if upstream_ms is not None else t.get("upstream", 0.0) or 0.0)
    if total <= 0.0:
        total = up + float(t.get("pipeline", t.get("ctl", 0.0)) or 0.0)
    aegis = max(0.0, total - up)
    ctl = float(t.get("ctl", 0.0) or 0.0)
    parts = [
        f'aegis;dur={_fmt(aegis)};desc="gateway overhead"',
        f"ctl;dur={_fmt(ctl)}",
        f"upstream;dur={_fmt(up)}",
        f"total;dur={_fmt(total)}",
    ]
    per_ctl = sorted(
        ((k[4:], float(v or 0.0)) for k, v in t.items() if k.startswith("ctl.")),
        key=lambda kv: kv[1],
        reverse=True,
    )
    for cid, ms in per_ctl[: max(0, top_controls)]:
        parts.append(f"ctl-{_token(cid)};dur={_fmt(ms)}")
    for key, ms in (extra or {}).items():
        parts.append(f"{_token(key)};dur={_fmt(ms)}")
    return ", ".join(parts)
