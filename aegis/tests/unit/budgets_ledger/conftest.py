"""Shared fixtures for budgets-ledger unit tests (fake runtime, snippet-based policy)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

os.environ.setdefault("AEGIS_TEST_MODE", "1")
os.environ.setdefault("AEGIS_SEMANTIC", "off")

from aegis.budgets import windows
from aegis.budgets.ledger import Ledger
from aegis.budgets.pricing import load_pricing
from aegis.controls.budget import _common
from aegis.core.policy_schema import (
    ApplyResult,
    ControlConfig,
    PolicyDoc,
    PolicySnapshot,
)
from aegis.core.types import (
    ApprovalRoute,
    Destination,
    Identity,
    Interaction,
    RequestContext,
    TextSegment,
)
from aegis.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
SNIPPET = ROOT / "config" / "snippets" / "budgets-ledger.yaml"
PRICING = ROOT / "config" / "pricing.yaml"
ORG_SEED = ROOT / "config" / "org.seed.yaml"


def snippet_doc(mutate: Any = None) -> PolicyDoc:
    data = yaml.safe_load(SNIPPET.read_text(encoding="utf-8"))
    if mutate is not None:
        mutate(data)
    return PolicyDoc.model_validate(data)


def make_snapshot(doc: PolicyDoc | None = None, version: int = 1) -> PolicySnapshot:
    doc = doc or snippet_doc()
    return PolicySnapshot(
        version=version,
        sha256=f"sha{version}",
        doc=doc,
        controls={c.id: c for c in doc.controls},
    )


def cfg(snap: PolicySnapshot, control_id: str) -> ControlConfig:
    return snap.controls[control_id]


# ---------------------------------------------------------------- fakes
class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def publish(self, event: str, data: Any) -> None:
        self.events.append((event, data))

    def of(self, name: str) -> list[Any]:
        return [d for e, d in self.events if e == name]


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def record(self, ev: Any) -> None:
        self.events.append(ev)


class FakeMetrics:
    def __init__(self) -> None:
        self.gauges: dict[str, float] = {}
        self.counters: dict[str, float] = {}

    def set_gauge(self, name: str, value: float, labels: Any = None) -> None:
        self.gauges[name] = value

    def inc(self, name: str, labels: Any = None, value: float = 1.0) -> None:
        self.counters[name] = self.counters.get(name, 0.0) + value


class FakePolicy:
    def __init__(self, snap: PolicySnapshot) -> None:
        self.snap = snap
        self.proposed: list[dict[str, Any]] = []
        self.applied: list[dict[str, Any]] = []
        self.listeners: list[Any] = []
        self.propose_status = "pending_approval"

    def snapshot(self) -> PolicySnapshot:
        return self.snap

    def on_change(self, cb: Any) -> None:
        self.listeners.append(cb)

    def swap(self, snap: PolicySnapshot) -> None:
        self.snap = snap
        for cb in self.listeners:
            cb(snap)

    async def propose(self, actor: Any, *, patch: Any = None, reason: str = "", **kw: Any) -> Any:
        self.proposed.append({"actor": actor, "patch": patch, "reason": reason, **kw})
        return ApplyResult(status=self.propose_status, version=self.snap.version)

    async def apply_patch(self, patch: Any, actor: Any = None, **kw: Any) -> Any:
        self.applied.append({"patch": patch, "actor": actor, **kw})
        return ApplyResult(status="applied", version=self.snap.version + 1)


MEMBERS = {
    "u_piotr": Identity(
        org_id="acme-capital", team_id="trading", member_id="u_piotr", role="member"
    ),
    "u_emily": Identity(
        org_id="acme-capital", team_id="platform", member_id="u_emily", role="admin"
    ),
    "u_marek": Identity(org_id="acme-capital", member_id="u_marek", role="owner"),
}


class FakeOrg:
    async def resolve_viewer(self, headers: Any, query: dict[str, str]) -> Identity:
        who = headers.get("x-aegis-view-as") or query.get("view_as") or "u_piotr"
        return MEMBERS.get(who, Identity(member_id=who, role="member"))


class FakeApprovals:
    def route(self, **kw: Any) -> ApprovalRoute:
        return ApprovalRoute(required_role="admin", rule_id="raise-team-small")


class FakeRt:
    def __init__(self, snap: PolicySnapshot, settings: Settings) -> None:
        self.settings = settings
        self.bus = FakeBus()
        self.audit = FakeAudit()
        self.metrics = FakeMetrics()
        self.policy = FakePolicy(snap)
        self.org = FakeOrg()
        self.approvals = FakeApprovals()
        self.ledger: Any = None


# ---------------------------------------------------------------- helpers
def agent(agent_id: str, team: str = "platform") -> Identity:
    return Identity(org_id="acme-capital", team_id=team, agent_id=agent_id, authenticated=True)


def human(member_id: str, team: str = "trading", role: str = "member") -> Identity:
    return Identity(org_id="acme-capital", team_id=team, member_id=member_id, role=role)  # type: ignore[arg-type]


def ctx(
    identity: Identity,
    session: str = "s1",
    snap: PolicySnapshot | None = None,
    **kw: Any,
) -> RequestContext:
    return RequestContext(
        request_id=kw.pop("request_id", "req_1"),
        session_id=session,
        identity=identity,
        policy=snap,
        **kw,
    )


def model_hop(
    text: str = "hello",
    model: str = "mock-echo",
    max_tokens: int | None = None,
    raw: dict[str, Any] | None = None,
    dest: str = "remote",
    **kw: Any,
) -> Interaction:
    return Interaction(
        id=kw.pop("id", "i1"),
        kind="model_call",
        surface="model.request",
        model=model,
        max_output_tokens=max_tokens,
        raw=raw if raw is not None else ({"max_tokens": max_tokens} if max_tokens else {}),
        destination=Destination(name="mock", dest_class=dest),  # type: ignore[arg-type]
        segments=[TextSegment(path="messages[0].content", text=text)],
        **kw,
    )


def tool_hop(
    tool: str = "web.fetch_url", args: dict[str, Any] | None = None, **kw: Any
) -> Interaction:
    return Interaction(
        id=kw.pop("id", "t1"),
        kind="tool_call",
        surface=kw.pop("surface", "tool.input"),
        tool_name=tool,
        tool_args=args or {},
        destination=Destination(name="web", dest_class="third_party"),
        **kw,
    )


@pytest.fixture
def snap() -> PolicySnapshot:
    return make_snapshot()


@pytest.fixture
def clock():
    """Controllable wall + monotonic clocks."""

    class Clock:
        def __init__(self) -> None:
            from datetime import UTC, datetime

            self.wall = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
            self.mono = 1000.0

        def advance(self, s: float) -> None:
            from datetime import timedelta

            self.wall += timedelta(seconds=s)
            self.mono += s

    c = Clock()
    windows.set_clock(lambda: c.wall)
    windows.set_monotonic(lambda: c.mono)
    yield c
    windows.set_clock(None)
    windows.set_monotonic(None)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        pricing=PRICING,
        org_seed=ORG_SEED,
        demo_mode=False,
        test_mode=True,
    )


@pytest.fixture
def rt(snap: PolicySnapshot, settings: Settings) -> FakeRt:
    return FakeRt(snap, settings)


@pytest.fixture
def led(rt: FakeRt):
    ledger = Ledger(rt, persist=False)
    ledger.pricing = load_pricing(PRICING)
    rt.ledger = ledger
    _common.use_ledger(ledger)
    yield ledger
    _common.use_ledger(None)
