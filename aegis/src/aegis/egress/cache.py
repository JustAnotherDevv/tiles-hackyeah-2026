"""Tiny LRU caches (text-scan results, media results). In-process, bounded, no TTL."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class LRU:
    def __init__(self, maxsize: int) -> None:
        self.maxsize = maxsize
        self._d: OrderedDict[Any, Any] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            val = self._d[key]
        except KeyError:
            self.misses += 1
            return default
        self._d.move_to_end(key)
        self.hits += 1
        return val

    def put(self, key: Any, value: Any) -> None:
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self.maxsize:
            self._d.popitem(last=False)

    def clear(self) -> None:
        self._d.clear()

    def __len__(self) -> int:
        return len(self._d)


TEXT_CACHE = LRU(4096)
MEDIA_CACHE = LRU(64)
