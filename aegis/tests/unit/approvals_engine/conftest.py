"""Fakes + fixtures for approvals-engine unit tests (fakes live here because of
`--import-mode=importlib`: test modules reach them through fixtures, never by import).

The org cast and resources mirror docs/seed-fixes/org.seed.yaml (binding ids, CONTRACTS 4.5).
The policy is a minimal PolicyDoc whose `approvals:` section is loaded from
config/snippets/approvals-engine.yaml (== docs/seed-fixes/approvals.yaml).
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

os.environ.setdefault("AEGIS_TEST_MODE", "1")
os.environ.setdefault("AEGIS_SEMANTIC", "off")

from aegis.core.policy_schema import (  # noqa: E402
    ApplyResult,
    ControlConfig,
    PolicyDoc,
    PolicySnapshot,
)
from aegis.core.types import (  # noqa: E402
    Agent,
    ApprovalDraft,
    BusMessage,
    Decision,
    Identity,
    Interaction,
    Member,
    Org,
    RequestContext,
    new_id,
)

ROOT = Path(__file__).resolve().parents[3]
SNIPPET = ROOT / "config" / "snippets" / "approvals-engine.yaml"

MEMBERS = [
    Member(id="u_katarzyna", org_id="acme-capital", team_id="trading", name="Katarzyna Wiśniewska", role="owner"),
    Member(id="u_marek", org_id="acme-capital", team_id="platform", name="Marek Kowalczyk", role="admin"),
    Member(id="u_emily", org_id="acme-capital", team_id="trading", name="Emily Carter", role="admin"),
    Member(id="u_piotr", org_id="acme-capital", team_id="trading", name="Piotr Zieliński", role="member"),
    Member(id="u_olivia", org_id="acme-capital", team_id="trading", name="Olivia Bennett", role="member"),
    Member(id="u_agnieszka", org_id="acme-capital", team_id="research", name="Agnieszka Lewandowska", role="member"),
    Member(id="u_james", org_id="acme-capital", team_id="research", name="James O'Connor", role="member"),
    Member(id="u_tomasz", org_id="acme-capital", team_id="platform", name="Tomasz Wójcik", role="member"),
]
AGENTS = [
    Agent(id="claude-code@platform", org_id="acme-capital", team_id="platform", owner_member_id="u_tomasz", name="Claude Code (Platform)", kind="claude-code"),
    Agent(id="research-agent@research", org_id="acme-capital", team_id="research", owner_member_id="u_agnieszka", name="Research Agent (local)", kind="scripted", max_destination="local"),
    Agent(id="trading-copilot@trading", org_id="acme-capital", team_id="trading", owner_member_id="u_piotr", name="Trading Copilot (remote)", kind="sdk"),
    Agent(id="chaos-agent@platform", org_id="acme-capital", team_id="platform", owner_member_id="u_tomasz", name="Chaos Agent (red team)", kind="other"),
]
RESOURCES: dict[str, Any] = {
    "databases": [
        {"id": "acme-prod-pg", "environment": "prod", "mcp_server": "acme-db", "tables": [
            {"name": "customers", "sensitivity": "CONFIDENTIAL"},
            {"name": "payment_cards", "sensitivity": "RESTRICTED"},
            {"name": "trades", "sensitivity": "CONFIDENTIAL"},
            {"name": "research_notes", "sensitivity": "INTERNAL"},
            {"name": "market_prices", "sensitivity": "PUBLIC"},
        ]},
        {"id": "acme-staging-pg", "environment": "staging", "schema": "staging", "tables": [
            {"name": "customers_synthetic", "sensitivity": "INTERNAL"},
            {"name": "market_prices", "sensitivity": "PUBLIC"},
        ]},
    ],
    "vendors": [
        {"id": "marketpulse", "name": "MarketPulse Pro", "approved": True, "plans": [
            {"id": "mp-pro-monthly", "usd": 50.0, "recurring": "monthly"},
            {"id": "mp-enterprise-annual", "usd": 4800.0, "recurring": "yearly"}]},
        {"id": "opendata-shop", "name": "OpenData Shop", "approved": True, "plans": [
            {"id": "eu-equities-2025-csv", "usd": 12.0, "recurring": "none"}]},
        {"id": "gpucloud", "name": "BurstGPU Cloud", "approved": True, "plans": [
            {"id": "a100-24h-reservation", "usd": 480.0, "recurring": "none"},
            {"id": "a100-cluster-week", "usd": 1500.0, "recurring": "none"}]},
        {"id": "shady-signals", "name": "Shady Signals Ltd", "approved": False, "plans": [
            {"id": "alpha-signals", "usd": 15.0, "recurring": "monthly"}]},
    ],
}


def load_snippet() -> dict[str, Any]:
    return yaml.safe_load(SNIPPET.read_text(encoding="utf-8"))


def make_doc(profile: str = "balanced", **overrides: Any) -> PolicyDoc:
    snippet = load_snippet()
    data: dict[str, Any] = {
        "profile": profile,
        "providers": {
            "anthropic": {"wire": "anthropic", "base_url": "https://api.anthropic.com", "destination": "remote"},
            "ollama": {"wire": "ollama", "base_url": "http://127.0.0.1:11434", "destination": "local"},
            "openai": {"wire": "openai", "base_url": "https://api.openai.com/v1", "destination": "remote"},
        },
        "models": {
            "allowed": ["claude-*", "qwen*"],
            "routes": [{"match": "claude-*", "provider": "anthropic"},
                       {"match": "gpt-*", "provider": "openai"},
                       {"match": "*", "provider": "ollama"}],
        },
        "budgets": {"limits": [{"scope": "team:trading", "window": "day", "usd": 60}]},
        "approvals": snippet["approvals"],
        "controls": [
            {"id": "DLP-02", "severity": "critical", "action": "block"},
            {"id": "INJ-02", "severity": "high", "action": "block"},
            {"id": "INJ-03", "severity": "medium", "action": "block"},
            *snippet["controls"],
        ],
    }
    data.update(overrides)
    return PolicyDoc.model_validate(data)


def make_snapshot(doc: PolicyDoc, version: int = 1) -> PolicySnapshot:
    return PolicySnapshot(version=version, sha256=f"sha{version}", doc=doc,
                          controls={c.id: c for c in doc.controls})


# ---------------------------------------------------------------- fakes
class FakeBus:
    def __init__(self) -> None:
        self.messages: list[BusMessage] = []

    def publish(self, event: str, data: Any) -> BusMessage:
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        msg = BusMessage(id=len(self.messages) + 1, event=event, data=dict(data))
        self.messages.append(msg)
        return msg

    def events(self, name: str) -> list[dict[str, Any]]:
        return [m.data for m in self.messages if m.event == name]

    async def subscribe(self, events: set[str] | None = None, *, replay: int = 0):  # pragma: no cover
        if False:
            yield None

    def recent(self, n: int = 100, events: set[str] | None = None) -> list[BusMessage]:
        return self.messages[-n:]


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def record(self, event: Any) -> Any:
        event.seq = len(self.events) + 1
        self.events.append(event)
        return event

    def of(self, event_type: str) -> list[Any]:
        return [e for e in self.events if e.event_type == event_type]

    async def query(self, *, event_type: str | None = None, since: Any = None, limit: int = 200,
                    cursor: str | None = None) -> tuple[list[Any], str | None]:
        return [e for e in self.events if event_type is None or e.event_type == event_type][:limit], None


class FakeMetrics:
    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str]]] = []
        self.gauges: dict[str, float] = {}

    def inc(self, name: str, labels: Any = None, value: float = 1.0) -> None:
        self.counters.append((name, dict(labels or {})))

    def set_gauge(self, name: str, value: float, labels: Any = None) -> None:
        self.gauges[name] = value


class FakeRedactor:
    def mask_for_log(self, text: str, max_len: int = 160) -> str:
        out = re.sub(r"\d{6,}", lambda m: m.group(0)[:2] + "*" * (len(m.group(0)) - 2), text)
        out = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]", out)
        return out[:max_len]


class FakeOrg:
    def __init__(self) -> None:
        self.members = list(MEMBERS)
        self.agents = list(AGENTS)

    async def list_members(self) -> list[Member]:
        return list(self.members)

    async def list_agents(self) -> list[Agent]:
        return list(self.agents)

    async def resources(self) -> dict[str, Any]:
        return RESOURCES

    async def org(self) -> Org:
        return Org(id="acme-capital", name="Acme Capital")

    async def resolve_viewer(self, headers: Any, query: Any = None) -> Identity:
        mid = headers.get("x-aegis-view-as") or (query or {}).get("view_as") or "u_katarzyna"
        m = next((x for x in self.members if x.id == mid), None)
        if m is None:
            return Identity(member_id=mid, role="member")
        return Identity(org_id=m.org_id, member_id=m.id, team_id=m.team_id, role=m.role,
                        display_name=m.name)


class FakePolicy:
    def __init__(self, doc: PolicyDoc) -> None:
        self.snap = make_snapshot(doc, 1)
        self.calls: list[dict[str, Any]] = []
        self.callbacks: list[Any] = []
        self.fail: Exception | None = None

    def snapshot(self) -> PolicySnapshot:
        return self.snap

    def set_profile(self, profile: str) -> None:
        doc = self.snap.doc.model_copy(update={"profile": profile})
        self.snap = make_snapshot(doc, self.snap.version + 1)

    def control_config(self, control_id: str) -> ControlConfig | None:
        return self.snap.controls.get(control_id)

    def on_change(self, cb: Any) -> None:
        self.callbacks.append(cb)

    async def apply_patch(self, patch: Any, *, actor: Any, source: str, reason: str | None = None) -> ApplyResult:
        if self.fail:
            raise self.fail
        self.calls.append({"op": "patch", "patch": patch, "actor": actor, "source": source, "reason": reason})
        prev = self.snap.version
        self.snap = make_snapshot(self.snap.doc, prev + 1)
        return ApplyResult(status="applied", version=prev + 1, previous_version=prev)

    async def apply_yaml(self, yaml_text: str, *, actor: Any, source: str, reason: str | None = None,
                         base_version: int | None = None) -> ApplyResult:
        self.calls.append({"op": "yaml", "actor": actor, "source": source, "reason": reason})
        prev = self.snap.version
        self.snap = make_snapshot(self.snap.doc, prev + 1)
        return ApplyResult(status="applied", version=prev + 1, previous_version=prev)


class FakeRuntime:
    def __init__(self, doc: PolicyDoc) -> None:
        self.settings = SimpleNamespace(test_mode=True, org_seed=None, data_dir=None)
        self.bus = FakeBus()
        self.audit = FakeAudit()
        self.metrics = FakeMetrics()
        self.redactor = FakeRedactor()
        self.org = FakeOrg()
        self.policy = FakePolicy(doc)
        self.feed = None
        self.approvals: Any = None

    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn


# ---------------------------------------------------------------- helpers
class Helpers:
    """Builders for identities, contexts, interactions and decisions."""

    @staticmethod
    def agent(agent_id: str) -> Identity:
        a = next(x for x in AGENTS if x.id == agent_id)
        return Identity(org_id=a.org_id, agent_id=a.id, member_id=a.owner_member_id,
                        team_id=a.team_id, role="agent")

    @staticmethod
    def member(member_id: str) -> Identity:
        m = next(x for x in MEMBERS if x.id == member_id)
        return Identity(org_id=m.org_id, member_id=m.id, team_id=m.team_id, role=m.role)

    @staticmethod
    def ctx(identity: Identity, *, token: str | None = None, source: str = "mcp") -> RequestContext:
        return RequestContext(request_id=new_id("req"), identity=identity, source=source,  # type: ignore[arg-type]
                              approval_token=token)

    @staticmethod
    def spend(amount: float, *, tool: str = "marketpulse.purchase_subscription",
              vendor: str = "marketpulse", plan: str = "mp-pro-monthly",
              extra_args: dict[str, Any] | None = None, labels: dict[str, str] | None = None) -> Interaction:
        args = {"vendor": vendor, "plan": plan, "amount_usd": amount, **(extra_args or {})}
        return Interaction(kind="mcp", surface="mcp.call", tool_name=tool, tool_args=args,
                           mcp_server=tool.split(".")[0], action_type="spend.subscription",
                           amount_usd=amount, resource=f"vendor:{vendor}", labels=labels or {})

    @staticmethod
    def db(sql: str, table: str, action_type: str = "db.read", labels: dict[str, str] | None = None) -> Interaction:
        return Interaction(kind="mcp", surface="mcp.call", tool_name="acme-db.query",
                           tool_args={"sql": sql}, mcp_server="acme-db", action_type=action_type,
                           resource=f"db:{table}", labels=labels or {})

    @staticmethod
    def decision(i: Interaction, *, control: str = "ACT-01", title: str | None = None,
                 kind: str = "action", payload: dict[str, Any] | None = None,
                 labels: dict[str, str] | None = None, action_type: str | None = None) -> Decision:
        draft = ApprovalDraft(kind=kind, action_type=action_type or i.action_type or "other",  # type: ignore[arg-type]
                              title=title or f"spend ${i.amount_usd}", amount_usd=i.amount_usd,
                              resource=i.resource, labels=labels or {}, payload=payload or {})
        return Decision(action="require_approval", control_id=control, reason="needs approval",
                        approval=draft)

    @staticmethod
    def config_interaction(changes: list[dict[str, Any]], proposal: dict[str, Any] | None = None) -> Interaction:
        return Interaction(kind="config_change", surface="config.change", resource="policy:abcdef0123456789",
                           action_type=changes[0]["kind"] if changes else "other",
                           meta={"changes": changes, "proposal": proposal or {"patch": [], "base_version": 1}})


@pytest.fixture
def h() -> type[Helpers]:
    return Helpers


@pytest.fixture
def doc() -> PolicyDoc:
    return make_doc()


@pytest.fixture
def snippet() -> dict[str, Any]:
    return load_snippet()


@pytest.fixture
def fake_rt(doc: PolicyDoc) -> FakeRuntime:
    return FakeRuntime(doc)


@pytest.fixture
async def svc(fake_rt: FakeRuntime):
    from aegis.approvals.service import create

    service = create(fake_rt)
    fake_rt.approvals = service
    await service.start()
    yield service
    await service.stop()


@pytest.fixture
def make_doc_fn():
    return make_doc


@pytest.fixture
def make_snapshot_fn():
    return make_snapshot
