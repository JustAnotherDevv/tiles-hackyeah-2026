"""Sliding-window rate counters (EXE-04) and local-model concurrency slots (BUD-02)."""

from __future__ import annotations

import asyncio
import math
from collections import deque

from aegis.core.types import new_id

from . import windows


class SlidingCounter:
    """Per-key sliding window (default 60 s): `hit()` -> (allowed, retry_after_s)."""

    def __init__(self, window_s: float = 60.0, max_keys: int = 10_000) -> None:
        self.window_s = window_s
        self.max_keys = max_keys
        self._events: dict[tuple[str, str], deque[float]] = {}

    def hit(
        self, key: tuple[str, str], limit: int | None, *, record: bool = True
    ) -> tuple[bool, int]:
        if not limit or limit <= 0:
            return True, 0
        now = windows.monotonic()
        dq = self._events.get(key)
        if dq is None:
            if not record:
                return True, 0
            dq = self._events[key] = deque()
            if len(self._events) > self.max_keys:
                self._prune(now)
        cutoff = now - self.window_s
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False, max(1, math.ceil(dq[0] + self.window_s - now))
        if record:
            dq.append(now)
        return True, 0

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        self._events = {k: v for k, v in self._events.items() if v and v[-1] > cutoff}

    def reset(self) -> None:
        self._events.clear()


class LocalSlots:
    """Concurrency slots for local model inference (8 GB laptop: one at a time)."""

    def __init__(self) -> None:
        self._leases: dict[str, float] = {}  # lease id -> expiry (monotonic)
        self._released: asyncio.Event | None = None

    def _purge(self) -> None:
        now = windows.monotonic()
        for lid, exp in list(self._leases.items()):
            if exp < now:
                self._leases.pop(lid, None)

    @property
    def active(self) -> int:
        self._purge()
        return len(self._leases)

    async def acquire(self, max_concurrency: int, wait_s: float, lease_s: float) -> str | None:
        """Lease id, or None when no slot freed up within `wait_s`."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, wait_s)
        while True:
            self._purge()
            if len(self._leases) < max(1, max_concurrency):
                lid = new_id("slot")
                self._leases[lid] = windows.monotonic() + lease_s
                return lid
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            if self._released is None:
                self._released = asyncio.Event()
            self._released.clear()
            try:
                await asyncio.wait_for(self._released.wait(), timeout=min(remaining, 1.0))
            except TimeoutError:
                pass

    def release(self, lease_id: str | None) -> None:
        if lease_id and self._leases.pop(lease_id, None) is not None and self._released:
            self._released.set()

    def reset(self) -> None:
        self._leases.clear()
