"""Fakes + helpers for threat-feed tests (imported by conftest and tests; unique module name)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aegis.core.policy_schema import FeedOverride, FeedsSection

FEED_BASE = "http://feed.test"


class Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish(self, event: str, data: dict) -> None:
        self.events.append((event, data))

    def of(self, name: str) -> list[dict]:
        return [d for e, d in self.events if e == name]


class Audit:
    def __init__(self) -> None:
        self.records: list[Any] = []

    async def record(self, ev: Any) -> None:
        self.records.append(ev)

    def of(self, name: str) -> list[Any]:
        return [r for r in self.records if r.event_type == name]


class Metrics:
    def __init__(self) -> None:
        self.gauges: dict[str, float] = {}
        self.counters: list[tuple[str, dict]] = []

    def inc(self, name: str, labels: dict | None = None, value: float = 1.0) -> None:
        self.counters.append((name, labels or {}))

    def set_gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        self.gauges[name] = value


class Policy:
    def __init__(self) -> None:
        self.feeds = FeedsSection()

    def snapshot(self) -> Any:
        return SimpleNamespace(doc=SimpleNamespace(feeds=self.feeds), version=1)

    def set_override(self, sid: str, **kw: Any) -> None:
        self.feeds = FeedsSection(
            sources=self.feeds.sources, overrides={**self.feeds.overrides, sid: FeedOverride(**kw)}
        )


class FakeRT:
    def __init__(self, tmp: Path, cfg_dir: Path, feed_url: str = FEED_BASE) -> None:
        self.settings = SimpleNamespace(
            feed_url=feed_url,
            feed_pubkey=str(cfg_dir / "feed_pubkey.b64"),
            data_dir=str(tmp / "data"),
            test_mode=True,
        )
        self.bus, self.audit, self.metrics, self.policy = Bus(), Audit(), Metrics(), Policy()
        self.redactor = None
        self.feed: Any = None
        self._db = tmp / "aegis.db"

    def db(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db)


def ctx(rt: Any = None, *, dry_run: bool = False, feed_serial: int | None = None) -> Any:
    policy = rt.policy.snapshot() if rt is not None else None
    return SimpleNamespace(policy=policy, dry_run=dry_run, feed_serial=feed_serial, state={})


def cfg(**params: Any) -> Any:
    return SimpleNamespace(params=params, owasp=[], action="block")
