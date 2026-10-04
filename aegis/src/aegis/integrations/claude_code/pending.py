"""In-memory registry of allowed PreToolUse evaluations awaiting their PostToolUse.

Keyed `(session_id, tool_use_id)`; LRU-bounded (2000) with a TTL (600 s, Addendum A-13). Expired entries are
swept lazily on every call (no background tasks, so `AEGIS_TEST_MODE` is honoured). The handler
guarantees `rt.pipeline.complete()` runs exactly once per PreToolUse: on PostToolUse /
PostToolUseFailure (pop), on Stop / SessionEnd (sweep_session) or on expiry (sweep_expired,
completed with `Outcome(status_code=200)`).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from aegis.core.types import Interaction, RequestContext, Verdict

MAX_ENTRIES = 2000
TTL_S = 600


@dataclass
class PendingEntry:
    ctx: RequestContext
    interaction: Interaction
    verdict: Verdict
    t0: float
    routed_mcp: bool = False
    created: float = field(default_factory=time.monotonic)
    extra: dict[str, Any] = field(default_factory=dict)


class PendingRegistry:
    def __init__(self, max_entries: int = MAX_ENTRIES, ttl_s: float = TTL_S) -> None:
        self.max_entries = max_entries
        self.ttl_s = ttl_s
        self._items: OrderedDict[tuple[str, str], PendingEntry] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def put(self, session_id: str, tool_use_id: str, entry: PendingEntry) -> list[PendingEntry]:
        """Store an entry; returns entries evicted by the LRU bound (caller completes them)."""
        key = (session_id, tool_use_id)
        evicted: list[PendingEntry] = []
        old = self._items.pop(key, None)
        if old is not None:
            evicted.append(old)
        self._items[key] = entry
        while len(self._items) > self.max_entries:
            _, e = self._items.popitem(last=False)
            evicted.append(e)
        return evicted

    def pop(self, session_id: str, tool_use_id: str | None) -> PendingEntry | None:
        if not tool_use_id:
            return None
        return self._items.pop((session_id, tool_use_id), None)

    def sweep_expired(self, now: float | None = None) -> list[PendingEntry]:
        now = time.monotonic() if now is None else now
        out: list[PendingEntry] = []
        for key in [k for k, e in self._items.items() if now - e.created > self.ttl_s]:
            out.append(self._items.pop(key))
        return out

    def sweep_session(self, session_id: str) -> list[PendingEntry]:
        out: list[PendingEntry] = []
        for key in [k for k in self._items if k[0] == session_id]:
            out.append(self._items.pop(key))
        return out

    def sessions(self) -> set[str]:
        return {k[0] for k in self._items}

    def clear(self) -> None:
        self._items.clear()


__all__ = ["MAX_ENTRIES", "TTL_S", "PendingEntry", "PendingRegistry"]
