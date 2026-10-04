"""Single-use nonce cache for A2A replay protection.

A nonce is remembered per ``(peer, nonce)`` for ``ttl_s`` (messages older than the signature TTL
are already rejected as stale, so the cache never needs to outlive it). Bounded (oldest entries
evicted first), thread-safe, in-process. ``reset()`` is for tests.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

_MAX = 50_000


class NonceCache:
    def __init__(self, max_entries: int = _MAX) -> None:
        self._lock = threading.Lock()
        self._seen: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._max = max_entries

    def _sweep(self, now: float) -> None:
        while self._seen:
            _key, exp = next(iter(self._seen.items()))
            if exp > now and len(self._seen) <= self._max:
                break
            self._seen.popitem(last=False)

    def seen(self, peer: str, nonce: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            exp = self._seen.get((peer, nonce))
            return exp is not None and exp > now

    def use(self, peer: str, nonce: str, ttl_s: float, now: float | None = None) -> bool:
        """Record the nonce. False when it was already used (a replay)."""
        now = time.time() if now is None else now
        with self._lock:
            self._sweep(now)
            key = (peer, nonce)
            exp = self._seen.get(key)
            if exp is not None and exp > now:
                return False
            self._seen[key] = now + max(1.0, float(ttl_s)) * 2
            self._seen.move_to_end(key)
            return True

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()

    def __len__(self) -> int:
        return len(self._seen)


NONCES = NonceCache()


def reset() -> None:
    NONCES.reset()
