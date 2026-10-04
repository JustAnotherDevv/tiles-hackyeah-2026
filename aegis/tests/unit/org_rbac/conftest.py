"""org-rbac unit-test harness: FakeRT (tmp SQLite, captured bus/audit, fake approvals/policy)."""

from __future__ import annotations

import re
import sqlite3
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from aegis.core.policy_schema import PolicyDoc, PolicySnapshot
from aegis.core.types import (
    ApprovalDraft,
    ApprovalRequest,
    ApprovalRoute,
    ApprovalVote,
    BusMessage,
    Identity,
    RequestContext,
    Span,
    new_id,
    utcnow,
)
from aegis.org.compat import glob_any

REPO = Path(__file__).resolve().parents[3]
SEED = REPO / "config" / "org.seed.yaml"

KEYS = {
    "cc": "aegis_demo_cc_platform_0000000000000001_NOT_A_SECRET",
    "research": "aegis_demo_research_agent_0000000000000002_NOT_A_SECRET",
    "copilot": "aegis_demo_trading_copilot_0000000000000003_NOT_A_SECRET",
    "chaos": "aegis_demo_chaos_agent_0000000000000004_NOT_A_SECRET",
    "revoked": "aegis_demo_revoked_key_0000000000000099_NOT_A_SECRET",
    "expired": "aegis_demo_expired_key_0000000000000098_NOT_A_SECRET",
}

POLICY: dict[str, Any] = {
    "version": 1,
    "defaults": {"require_auth": False},
    "models": {
        "allowed": [
            "claude-*",
            "gpt-4.1-mini",
            "meta-llama/*",
            "aegis-judge*",
            "qwen*",
            "hf.co/*",
            "mock-*",
        ],
        "denied": ["*:cloud", "aegis-guard*"],
        "default_local": "aegis-judge",
    },
    "budgets": {"kill_switch": {"global": False, "agents": []}},
    "approvals": {
        "defaults": {"default_approver": "admin", "default_config_approver": "owner"},
        "rules": [
            {
                "id": "org-owner-grants",
                "when": {
                    "kind": ["action"],
                    "action": [
                        "org.role.promote_owner",
                        "org.role.demote_owner",
                        "org.member.create_owner",
                    ],
                },
                "approver": "owner",
                "ttl_s": 3600,
            },
            {
                "id": "org-privileged",
                "when": {
                    "kind": ["action"],
                    "action": [
                        "org.role.*",
                        "org.member.create_admin",
                        "org.member.deactivate_privileged",
                        "org.agent.widen_destination",
                    ],
                },
                "approver": "owner",
                "ttl_s": 3600,
            },
            {
                "id": "org-routine",
                "when": {"kind": ["action"], "action": ["org.member.*", "org.agent.*"]},
                "approver": "admin",
            },
            {
                "id": "spend-self",
                "when": {"action": ["spend.*"], "amount_usd_lte": 20},
                "approver": "self",
            },
        ],
        "config_rules": [
            {
                "id": "tighten",
                "when": {
                    "action": [
                        "budget.lower",
                        "control.enable",
                        "control.*.tighten",
                        "killswitch.on",
                        "model.disallow",
                    ]
                },
                "approver": "admin",
            },
            {
                "id": "raise-team-small",
                "when": {
                    "action": ["budget.raise"],
                    "scope_type": ["team"],
                    "increase_pct_lte": 50,
                },
                "approver": "admin",
            },
            {"id": "raise-large", "when": {"action": ["budget.raise"]}, "approver": "owner"},
            {
                "id": "loosen-threshold",
                "when": {"action": ["control.threshold.loosen", "model.allow", "killswitch.off"]},
                "approver": "admin",
            },
            {
                "id": "disable-control",
                "when": {
                    "action": [
                        "control.disable",
                        "control.remove",
                        "control.mode",
                        "control.action.loosen",
                    ]
                },
                "approver": "owner",
            },
        ],
    },
    "controls": [
        {
            "id": "GOV-01",
            "action": "log",
            "severity": "high",
            "params": {
                "anonymous_action": "allow",
                "unknown_agent_action": "log",
                "invalid_key_action": "block",
                "disabled_principal_action": "block",
                "principal_mismatch_action": "block",
            },
        },
        {"id": "GOV-02", "action": "block", "severity": "high", "params": {}},
    ],
}


def make_snapshot(doc: dict[str, Any] | None = None, version: int = 1) -> PolicySnapshot:
    pdoc = PolicyDoc.model_validate(doc or POLICY)
    return PolicySnapshot(
        version=version, sha256="t", doc=pdoc, controls={c.id: c for c in pdoc.controls}
    )


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, Any]] = []

    def publish(self, event: str, data: Any) -> BusMessage:
        self.published.append((event, data))
        return BusMessage(
            id=len(self.published), event=event, data=data if isinstance(data, dict) else {}
        )

    async def subscribe(self, events: set[str] | None = None, *, replay: int = 0):
        if False:  # pragma: no cover
            yield None

    def recent(self, n: int = 100, events: set[str] | None = None) -> list[BusMessage]:
        return []

    def events(self, name: str) -> list[Any]:
        return [d for e, d in self.published if e == name]


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def record(self, event: Any) -> Any:
        self.events.append(event)
        return event

    def org_changes(self) -> list[Any]:
        return [e for e in self.events if e.event_type == "org.changed"]


class FakePolicy:
    def __init__(self) -> None:
        self.snap = make_snapshot()

    def snapshot(self) -> PolicySnapshot:
        return self.snap

    def control_config(self, control_id: str) -> Any:
        return self.snap.controls.get(control_id)


def _rule_matches(
    rule: Any, kind: str, action_type: str, changes: list[Any] | None, amount: float | None
) -> bool:
    w = rule.when
    if w.kind and kind not in w.kind:
        return False
    if w.action and not glob_any(w.action, action_type):
        return False
    if w.amount_usd_lte is not None and (amount is None or amount > w.amount_usd_lte):
        return False
    if w.amount_usd_gt is not None and (amount is None or amount <= w.amount_usd_gt):
        return False
    ch = (changes or [None])[0]
    if w.scope_type and (ch is None or not ch.scope or ch.scope.split(":")[0] not in w.scope_type):
        return False
    if w.increase_pct_lte is not None and (
        ch is None or ch.increase_pct is None or ch.increase_pct > w.increase_pct_lte
    ):
        return False
    return True


class FakeApprovals:
    """First-match routing over the snapshot rules; manual requests; votes run executors."""

    def __init__(self, policy: FakePolicy, org_getter: Any) -> None:
        self.policy = policy
        self.org_getter = org_getter
        self.requests: dict[str, ApprovalRequest] = {}
        self.executors: dict[str, Any] = {}
        self.create_status: str | None = None  # force "denied"/"approved" at creation
        self.fail_route = False

    def route(
        self,
        *,
        kind: str,
        action_type: str,
        requester: Identity,
        amount_usd: float | None = None,
        resource: str | None = None,
        labels: Any = None,
        changes: Any = None,
    ) -> ApprovalRoute:
        if self.fail_route:
            raise RuntimeError("route unavailable")
        doc = self.policy.snapshot().doc
        rules = doc.approvals.config_rules if kind == "config_change" else doc.approvals.rules
        for rule in rules:
            if _rule_matches(rule, kind, action_type, changes, amount_usd):
                return ApprovalRoute(
                    required_role=rule.approver,
                    two_person=rule.two_person,
                    rule_id=rule.id,
                    ttl_s=rule.ttl_s or 900,
                )
        default = (
            doc.approvals.defaults.default_config_approver
            if kind == "config_change"
            else doc.approvals.defaults.default_approver
        )
        return ApprovalRoute(required_role=default)

    async def create_manual(self, requester: Identity, draft: ApprovalDraft) -> ApprovalRequest:
        route = self.route(
            kind=draft.kind,
            action_type=draft.action_type,
            requester=requester,
            resource=draft.resource,
            labels=draft.labels,
        )
        req = ApprovalRequest(
            id=new_id("apr"),
            kind=draft.kind,
            action_type=draft.action_type,
            title=draft.title,
            summary=draft.summary,
            requester=requester,
            resource=draft.resource,
            labels=draft.labels,
            payload=draft.payload,
            fingerprint="fp",
            required_role=route.required_role,
            rule_id=route.rule_id,
            expires_at=utcnow() + timedelta(seconds=route.ttl_s),
            status=self.create_status or "pending",  # type: ignore[arg-type]
        )
        if route.required_role == "auto" and not self.create_status:
            req.status = "approved"
        self.requests[req.id] = req
        fn = self.executors.get(req.kind)
        if req.status == "approved" and fn is not None:  # like approvals-engine (A-25)
            req.execution = await fn(req)
        return req

    async def get(self, approval_id: str) -> ApprovalRequest | None:
        return self.requests.get(approval_id)

    async def vote(
        self,
        approval_id: str,
        voter: Identity,
        decision: str,
        comment: str | None = None,
        *,
        run_executor: bool = True,
    ) -> ApprovalRequest:
        req = self.requests[approval_id]
        req.votes.append(
            ApprovalVote(member_id=voter.member_id or "?", role=voter.role, decision=decision)
        )  # type: ignore[arg-type]
        req.status = "approved" if decision == "approve" else "denied"
        req.decided_by = [voter.member_id or "?"]
        req.decided_at = utcnow()
        fn = self.executors.get(req.kind)
        if run_executor and decision == "approve" and fn is not None:
            req.execution = await fn(req)
        return req

    def register_executor(self, kind: str, fn: Any) -> None:
        self.executors[kind] = fn


class FakeLedger:
    async def status(self, scope: str | None = None) -> list[Any]:
        return []


_PAN = re.compile(r"\b4\d{15}\b")


class FakeRedactor:
    def detect(self, text: str, *, entities: Any = None, use_ner: bool = False) -> list[Span]:
        return [
            Span(
                start=m.start(),
                end=m.end(),
                entity="PAN",
                data_class="RESTRICTED",
                detector_id="pci.pan",
                category="pci",
            )
            for m in _PAN.finditer(text)
        ]


class FakeRT:
    def __init__(self, tmp: Path, **settings: Any) -> None:
        self.tmp = tmp
        self.settings = SimpleNamespace(
            org_seed=settings.pop("org_seed", SEED),
            demo_mode=True,
            default_viewer=None,
            admin_token=None,
            test_mode=True,
            data_dir=tmp,
            **settings,
        )
        self.bus = FakeBus()
        self.audit = FakeAudit()
        self.policy = FakePolicy()
        self.org: Any = None
        self.approvals = FakeApprovals(self.policy, lambda: self.org)
        self.ledger = FakeLedger()
        self.redactor = FakeRedactor()

    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.tmp / "aegis.db"), check_same_thread=False, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


@pytest.fixture(autouse=True)
def _hmac_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from aegis.core import crypto

    monkeypatch.setenv("AEGIS_TEST_MODE", "1")
    crypto.configure(data_dir=tmp_path, key="org-rbac-test-hmac-key")
    yield
    crypto.configure(data_dir=None, key=None)
    from aegis.controls.governance import _common

    _common.set_runtime(None)


@pytest.fixture
def make_rt(tmp_path: Path):
    def _make(**settings: Any) -> FakeRT:
        return FakeRT(tmp_path, **settings)

    return _make


@pytest.fixture
async def rt(make_rt):
    from aegis.controls.governance import _common
    from aegis.org.service import create

    fake = make_rt()
    svc = create(fake)
    fake.org = svc
    await svc.start()
    _common.set_runtime(fake)
    yield fake
    await svc.stop()


@pytest.fixture
async def client(rt):
    from aegis.api.routes import org as org_routes

    app = FastAPI()
    app.state.rt = rt
    app.include_router(org_routes.router)
    await org_routes.on_startup(rt)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://aegis.test") as c:
        yield c
    await org_routes.on_shutdown(rt)


def as_viewer(member_id: str) -> dict[str, str]:
    return {"X-Aegis-View-As": member_id}


def ctx_for(
    identity: Identity, source: str = "proxy", snap: PolicySnapshot | None = None
) -> RequestContext:
    ctx = RequestContext(request_id="r", identity=identity, source=source)  # type: ignore[arg-type]
    ctx.policy = snap or make_snapshot()
    return ctx


@pytest.fixture
def helpers():
    return SimpleNamespace(
        KEYS=KEYS,
        as_viewer=as_viewer,
        ctx_for=ctx_for,
        make_snapshot=make_snapshot,
        POLICY=POLICY,
        SEED=SEED,
    )
