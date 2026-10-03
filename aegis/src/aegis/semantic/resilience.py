"""Resilience primitives for the model runtime (pure Python, injectable clock).

- ``CircuitBreaker``: CLOSED -> OPEN on ``consecutive`` failures, on ``error_rate`` over a rolling
  window (``min_calls``), or when the rolling p95 exceeds ``slow_p95_ms``. OPEN for ``cooldown``
  (doubling up to ``max_cooldown_s``), then HALF_OPEN lets exactly one probe through:
  success -> CLOSED (cooldown reset), failure -> OPEN again.
- ``LatencyWindow``: last N latencies with p50 / p95.
- ``TTLCache``: small LRU + TTL map (scores only, never text).
- ``SingleFlight``: de-duplicates identical concurrent async calls with shielded futures, so one
  cancelled caller never cancels the shared work.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Hashable
from typing import Any, Literal

BreakerState = Literal["closed", "open", "half_open"]
Clock = Callable[[], float]


def _percentile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


class LatencyWindow:
    def __init__(self, size: int = 512) -> None:
        self._vals: deque[float] = deque(maxlen=size)
        self.count = 0  # total observations (not capped)

    def add(self, ms: float) -> None:
        self._vals.append(float(ms))
        self.count += 1

    def percentile(self, q: float) -> float | None:
        return _percentile(sorted(self._vals), q)

    @property
    def p50(self) -> float | None:
        return self.percentile(0.50)

    @property
    def p95(self) -> float | None:
        return self.percentile(0.95)

    def __len__(self) -> int:
        return len(self._vals)


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        window: int = 20,
        error_rate: float = 0.3,
        min_calls: int = 5,
        consecutive: int = 3,
        cooldown_s: float = 30.0,
        max_cooldown_s: float = 300.0,
        slow_p95_ms: float | None = None,
        clock: Clock = time.monotonic,
        on_change: Callable[[CircuitBreaker, BreakerState, BreakerState, str], Any] | None = None,
    ) -> None:
        self.name = name
        self.window = window
        self.error_rate = error_rate
        self.min_calls = min_calls
        self.consecutive = consecutive
        self.base_cooldown_s = cooldown_s
        self.max_cooldown_s = max_cooldown_s
        self.slow_p95_ms = slow_p95_ms
        self.clock = clock
        self.on_change = on_change
        self._state: BreakerState = "closed"
        self._calls: deque[tuple[bool, float]] = deque(maxlen=window)
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self.cooldown_s = cooldown_s
        self._probe_in_flight = False
        self.last_reason = ""
        self.opens = 0

    # ------------------------------------------------------------ state
    @property
    def state(self) -> BreakerState:
        if self._state == "open" and self.clock() - self._opened_at >= self.cooldown_s:
            self._set("half_open", "cooldown elapsed")
        return self._state

    def _set(self, new: BreakerState, reason: str) -> None:
        old = self._state
        if old == new:
            return
        self._state = new
        self.last_reason = reason
        if new == "open":
            self._opened_at = self.clock()
            self.opens += 1
        if new == "half_open":
            self._probe_in_flight = False
        if self.on_change is not None:
            try:
                self.on_change(self, old, new, reason)
            except Exception:  # never let a listener break the caller
                pass

    def allow(self) -> bool:
        """True if a call may proceed now (HALF_OPEN admits one probe at a time)."""
        st = self.state
        if st == "closed":
            return True
        if st == "half_open" and not self._probe_in_flight:
            self._probe_in_flight = True
            return True
        return False

    def release_probe(self) -> None:
        """Give back a HALF_OPEN probe slot that was admitted but never reached the model."""
        self._probe_in_flight = False

    def seconds_until_probe(self) -> float:
        if self._state != "open":
            return 0.0
        return max(0.0, self.cooldown_s - (self.clock() - self._opened_at))

    # ------------------------------------------------------------ outcomes
    def record(self, ok: bool, ms: float = 0.0) -> None:
        st = self.state
        if st == "half_open":
            self._probe_in_flight = False
            if ok:
                self._calls.clear()
                self._consecutive_failures = 0
                self.cooldown_s = self.base_cooldown_s
                self._set("closed", "probe succeeded")
            else:
                self.cooldown_s = min(self.cooldown_s * 2, self.max_cooldown_s)
                self._set("open", "probe failed")
            return
        if st == "open":
            return  # late result of a call admitted before the breaker opened
        self._calls.append((ok, float(ms)))
        self._consecutive_failures = 0 if ok else self._consecutive_failures + 1
        if self._consecutive_failures >= self.consecutive:
            self._set("open", f"{self._consecutive_failures} consecutive failures")
            return
        n = len(self._calls)
        if n >= self.min_calls:
            fails = sum(1 for c_ok, _ in self._calls if not c_ok)
            if fails / n >= self.error_rate:
                self._set("open", f"error rate {fails}/{n}")
                return
            if self.slow_p95_ms is not None:
                p95 = _percentile(sorted(m for c_ok, m in self._calls if c_ok), 0.95)
                if p95 is not None and p95 > self.slow_p95_ms:
                    self._set("open", f"slow p95 {p95:.0f} ms > {self.slow_p95_ms:.0f} ms")

    def reset(self) -> None:
        self._calls.clear()
        self._consecutive_failures = 0
        self.cooldown_s = self.base_cooldown_s
        self._set("closed", "reset")

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "opens": self.opens,
            "cooldown_s": self.cooldown_s,
            "reason": self.last_reason or None,
        }


class TTLCache:
    """LRU + TTL. ``get`` returns None when missing or expired."""

    def __init__(self, maxsize: int = 4096, ttl_s: float = 3600.0, clock: Clock = time.monotonic):
        self.maxsize = maxsize
        self.ttl_s = ttl_s
        self.clock = clock
        self._d: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> Any:
        item = self._d.get(key)
        if item is None:
            self.misses += 1
            return None
        exp, value = item
        if self.clock() >= exp:
            self._d.pop(key, None)
            self.misses += 1
            return None
        self._d.move_to_end(key)
        self.hits += 1
        return value

    def set(self, key: Hashable, value: Any) -> None:
        self._d[key] = (self.clock() + self.ttl_s, value)
        self._d.move_to_end(key)
        while len(self._d) > self.maxsize:
            self._d.popitem(last=False)

    def clear(self) -> None:
        self._d.clear()

    def __len__(self) -> int:
        return len(self._d)

    def __contains__(self, key: Hashable) -> bool:
        item = self._d.get(key)
        return item is not None and self.clock() < item[0]


class SingleFlight:
    """Concurrent callers with the same key share one in-flight coroutine."""

    def __init__(self) -> None:
        self._inflight: dict[Hashable, asyncio.Future[Any]] = {}
        self.shared = 0

    async def do(self, key: Hashable, fn: Callable[[], Awaitable[Any]]) -> Any:
        fut = self._inflight.get(key)
        if fut is None:
            task = asyncio.ensure_future(fn())
            self._inflight[key] = task

            def _done(f: asyncio.Future[Any], k: Hashable = key) -> None:
                self._inflight.pop(k, None)
                if not f.cancelled():
                    f.exception()  # mark retrieved: every caller may have been cancelled

            task.add_done_callback(_done)
            fut = task
        else:
            self.shared += 1
        return await asyncio.shield(fut)

    def __len__(self) -> int:
        return len(self._inflight)


__all__ = ["BreakerState", "CircuitBreaker", "LatencyWindow", "SingleFlight", "TTLCache"]
