"""FakeRuntime for claude-code-integration unit tests (no other workstream needed)."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

import pytest

os.environ.setdefault("AEGIS_TEST_MODE", "1")
os.environ.setdefault("AEGIS_SEMANTIC", "off")

from aegis.core.policy_schema import (
    ControlConfig,
    McpServerConfig,
    PolicyDoc,
    PolicySnapshot,
)
from aegis.core.types import (
    Agent,
    ApprovalRequest,
    BudgetStatus,
    Decision,
    Identity,
    Interaction,
    Outcome,
    Redaction,
    RequestContext,
    SessionState,
    TextSegment,
    Verdict,
    new_id,
)

KEY_CONTROLS = ["EXE-01", "EXE-02", "DLP-01", "INJ-01", "BUD-01", "GOV-03", "ACT-01", "DLP-08"]
NAMES = {
    "EXE-01": "Dangerous command guard",
    "EXE-02": "Filesystem & network scope (SSRF)",
    "DLP-01": "PII/PCI/Polish-ID tokenization",
    "INJ-01": "Normalization + deterministic injection signatures",
    "BUD-01": "Token & cost budgets",
    "GOV-03": "Tool authorization",
    "ACT-01": "Spend guard",
    "DLP-08": "Vault & controlled re-identification",
}


def make_snapshot(*, hook_hold: float = 60, gov06: dict[str, Any] | None = None,
                  version: int = 7) -> PolicySnapshot:
    doc = PolicyDoc()
    doc.mcp.servers = {
        "payments": McpServerConfig(url="http://127.0.0.1:8792/mcp/payments", destination="third_party"),
        "acme-db": McpServerConfig(url="http://127.0.0.1:8792/mcp/acme-db", destination="local"),
    }
    doc.approvals.defaults.hold_s = {**doc.approvals.defaults.hold_s, "hook": hook_hold}
    controls = {cid: ControlConfig(id=cid, name=NAMES.get(cid)) for cid in KEY_CONTROLS}
    if gov06 is not None:
        controls["GOV-06"] = ControlConfig(id="GOV-06", name="Agent harness integrity", **gov06)
    doc.controls = list(controls.values())
    return PolicySnapshot(version=version, sha256="0" * 64, doc=doc, controls=controls)


def make_verdict(
    action: str = "allow",
    *,
    control_id: str | None = None,
    reason: str = "",
    segments: list[TextSegment] | None = None,
    redactions: list[Redaction] | None = None,
    approval: ApprovalRequest | None = None,
    http_status: int | None = None,
    error_type: str | None = None,
    meta: dict[str, Any] | None = None,
    extra: list[Decision] | None = None,
    version: int = 7,
) -> Verdict:
    primary = None
    decisions: list[Decision] = list(extra or [])
    if control_id:
        primary = Decision(action=action, control_id=control_id, reason=reason,  # type: ignore[arg-type]
                           http_status=http_status, error_type=error_type, meta=meta or {})
        decisions.insert(0, primary)
    return Verdict(
        id=new_id("dec"), request_id=new_id("req"), interaction_id=new_id("int"),
        action=action,  # type: ignore[arg-type]
        primary=primary, decisions=decisions, segments=segments or [],
        redactions=redactions or [], approval=approval, policy_version=version,
    )


class FakePolicy:
    def __init__(self, snap: PolicySnapshot | None) -> None:
        self.snap = snap

    def snapshot(self) -> PolicySnapshot:
        if self.snap is None:
            raise RuntimeError("no policy")
        return self.snap


class FakeOrg:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, str], dict[str, str] | None]] = []

    async def resolve_identity(self, headers: Mapping[str, str], *, hints: Mapping[str, str] | None = None) -> Identity:
        self.calls.append((dict(headers), dict(hints or {})))
        aid = headers.get("x-aegis-agent") or (hints or {}).get("agent_id")
        auth = headers.get("authorization", "")
        return Identity(org_id="acme-capital", team_id="platform", agent_id=aid, role="agent",
                        authenticated=auth.startswith("Bearer aegis_"))

    async def get_agent(self, agent_id: str) -> Agent | None:
        if agent_id == "claude-code@platform":
            return Agent(id=agent_id, org_id="acme-capital", team_id="platform",
                         owner_member_id="u_tomasz", name="Claude Code", kind="claude-code",
                         max_destination="remote")
        return None


class FakePipeline:
    def __init__(self) -> None:
        self.verdict_fn: Callable[[RequestContext, Interaction], Verdict] = (
            lambda ctx, i: make_verdict("allow")
        )
        self.contexts: list[dict[str, Any]] = []
        self.evaluated: list[tuple[RequestContext, Interaction]] = []
        self.completed: list[tuple[Interaction, Verdict, Outcome]] = []
        self.raise_on_evaluate = False

    def new_context(self, *, source: str, identity: Identity, session_id: str | None = None,
                    headers: Mapping[str, str] | None = None, approval_token: str | None = None,
                    wait_for_approval_s: float = 0.0, dry_run: bool = False) -> RequestContext:
        self.contexts.append({"source": source, "identity": identity, "session_id": session_id,
                              "headers": dict(headers or {}), "approval_token": approval_token,
                              "wait_for_approval_s": wait_for_approval_s})
        return RequestContext(request_id=new_id("req"), session_id=session_id or "default",
                              identity=identity, source=source,  # type: ignore[arg-type]
                              headers=dict(headers or {}), wait_for_approval_s=wait_for_approval_s)

    async def evaluate(self, ctx: RequestContext, interaction: Interaction, *, policy: Any = None,
                       dry_run: bool = False) -> Verdict:
        if self.raise_on_evaluate:
            raise RuntimeError("pipeline exploded")
        self.evaluated.append((ctx, interaction))
        return self.verdict_fn(ctx, interaction)

    async def complete(self, ctx: RequestContext, interaction: Interaction, verdict: Verdict,
                       outcome: Outcome) -> None:
        self.completed.append((interaction, verdict, outcome))


class FakeRedactor:
    VAULT = {"[PESEL_1]": "44051401359", "[EMAIL_1]": "jan.kowalski@example.com"}

    def rehydrate(self, ctx: RequestContext, text: str) -> str:
        for k, v in self.VAULT.items():
            text = text.replace(k, v)
        return text

    def mask_for_log(self, text: str, max_len: int = 160) -> str:
        return "".join("#" if ch.isdigit() else ch for ch in text)[:max_len]


class FakeLedger:
    def __init__(self) -> None:
        self.statuses: dict[str, list[BudgetStatus]] = {}

    def scopes_for(self, identity: Identity, session_id: str) -> list[str]:
        return [f"org:{identity.org_id}", f"team:{identity.team_id}",
                f"agent:{identity.agent_id}", f"session:{session_id}"]

    async def status(self, scope: str | None = None) -> list[BudgetStatus]:
        return list(self.statuses.get(scope or "", []))


class Recorder:
    def __init__(self) -> None:
        self.items: list[Any] = []

    async def record(self, event: Any) -> Any:
        self.items.append(event)
        return event

    def publish(self, event: str, data: Any) -> None:
        self.items.append((event, data))

    def inc(self, name: str, labels: Mapping[str, str] | None = None, value: float = 1.0) -> None:
        self.items.append(("inc", name, dict(labels or {})))

    def observe_overhead(self, phase: str, seconds: float) -> None:
        self.items.append(("overhead", phase, seconds))


class FakeSessions:
    def __init__(self) -> None:
        self.store: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        return self.store.setdefault(session_id, SessionState(session_id=session_id))

    def all(self) -> list[SessionState]:
        return list(self.store.values())


class FakeControls:
    class _C:
        def __init__(self, cid: str) -> None:
            self.id, self.name = cid, NAMES.get(cid, cid)

    def get(self, control_id: str) -> Any:
        return self._C(control_id) if control_id in NAMES else None

    def all(self) -> list[Any]:
        return [self._C(c) for c in NAMES]


class FakeFeed:
    serial = 3


class FakeApprovals:
    pass


class FakeRuntime:
    def __init__(self, snap: PolicySnapshot | None = None) -> None:
        self.policy = FakePolicy(snap if snap is not None else make_snapshot())
        self.org = FakeOrg()
        self.pipeline = FakePipeline()
        self.redactor = FakeRedactor()
        self.ledger = FakeLedger()
        self.audit = Recorder()
        self.bus = Recorder()
        self.metrics = Recorder()
        self.sessions = FakeSessions()
        self.controls = FakeControls()
        self.feed = FakeFeed()
        self.approvals = FakeApprovals()


@pytest.fixture
def rt() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "project"
    p.mkdir()
    return p
