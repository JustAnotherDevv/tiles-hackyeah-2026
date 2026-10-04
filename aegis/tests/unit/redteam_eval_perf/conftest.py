"""Fakes for redteam-eval-perf unit tests (fake runtimes only ever write to tmp_path)."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("AEGIS_SEMANTIC", "off")
os.environ.setdefault("AEGIS_TEST_MODE", "1")


def decision(cid: str, action: str = "block", *, mode: str = "enforce", degraded: bool = False,
             reason: str = "", score: float | None = None, latency_ms: float = 0.1) -> dict[str, Any]:
    return {"control_id": cid, "action": action, "mode": mode, "degraded": degraded, "reason": reason,
            "score": score, "latency_ms": latency_ms, "meta": {}}


def verdict(action: str, decisions: list[dict], primary: dict | None = None, **kw: Any) -> dict[str, Any]:
    if primary is None:
        primary = next((d for d in decisions if d["action"] == action), decisions[0] if decisions else None)
    return {"action": action, "decisions": decisions, "primary": primary, "latency_ms": kw.get("latency_ms", 1.0),
            "degraded": kw.get("degraded", False), "segments": kw.get("segments", [])}


class FakePipeline:
    """`decide(interaction) -> Verdict-like object` or raise."""

    def __init__(self, decide):
        self.decide = decide

    def new_context(self, **kw: Any) -> Any:
        return SimpleNamespace(**kw)

    async def evaluate(self, ctx: Any, interaction: Any, dry_run: bool = False) -> Any:
        v = self.decide(interaction)
        return SimpleNamespace(**{**v, "segments": [SimpleNamespace(text=t) for t in v.get("segments", [])]})


class FakeRuntime:
    def __init__(self, decide):
        self.pipeline = FakePipeline(decide)
        self.org = SimpleNamespace(resolve_identity=self._resolve)
        self.redactor = None
        self.policy = SimpleNamespace(snapshot=lambda: SimpleNamespace(version=7, doc=None))

    async def _resolve(self, headers: dict) -> Any:
        from aegis.core.types import Identity

        return Identity(org_id="acme-capital", agent_id=headers.get("x-aegis-agent"), role="agent")


@pytest.fixture
def fake_rt():
    return FakeRuntime
