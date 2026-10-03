"""Aegis plug-in and service protocols. FROZEN: materialized verbatim from docs/CONTRACTS.md
section 3.2.

Cross-workstream calls go through `rt.<service>` (see RuntimeProto), never through another
workstream's private modules.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

from aegis.core.policy_schema import (
    ApplyResult,
    ControlConfig,
    PatchOp,
    PolicyChange,
    PolicySnapshot,
    PolicyVersionInfo,
    ValidationReport,
    Wire,
)
from aegis.core.types import (
    Agent,
    AppliesTo,
    ApprovalDraft,
    ApprovalKind,
    ApprovalRequest,
    ApprovalRoute,
    ApprovalStatus,
    AuditEvent,
    AuditVerifyResult,
    BudgetDenial,
    BudgetStatus,
    BusMessage,
    ControlKind,
    DataClass,
    Decision,
    Direction,
    FeedStatus,
    Finding,
    Identity,
    Interaction,
    Member,
    Org,
    Outcome,
    Redaction,
    RequestContext,
    Reservation,
    Role,
    ScoreResult,
    SessionState,
    Source,
    Span,
    Team,
    TextSegment,
    Usage,
    Verdict,
    WireView,
)


# ================================================================ plug-ins (auto-discovered)
@runtime_checkable
class Control(Protocol):
    """Discovered from `CONTROLS: list[Control]` in any module under aegis.controls."""

    id: str  # "DLP-01" (must exist in the catalog, CONTRACTS section 4.4)
    family: str  # "DLP"
    name: str
    kind: ControlKind
    applies_to: AppliesTo
    owasp: list[str]
    priority: int  # lower runs first (enrich + deterministic phase); default 100

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        """Return None (or action=allow) when nothing to report. Never raise for 'not applicable'."""
        ...


class BaseControl:
    """Convenience base class. Subclass, set the ClassVars, implement evaluate()."""

    id: ClassVar[str] = ""
    family: ClassVar[str] = ""
    name: ClassVar[str] = ""
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo()
    owasp: ClassVar[list[str]] = []
    priority: ClassVar[int] = 100

    async def enrich(self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig) -> None:
        """Optional phase 1: annotate the interaction (action_type, amount_usd, resource, labels)."""
        return None

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        raise NotImplementedError

    async def on_complete(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        verdict: Verdict,
        outcome: Outcome,
        cfg: ControlConfig,
    ) -> None:
        """Optional: called after an allowed interaction executed (settle budgets, taint, loops)."""
        return None

    def decide(
        self,
        cfg: ControlConfig,
        *,
        action: str | None = None,
        reason: str = "",
        score: float | None = None,
        findings: list[Finding] | None = None,
        **kw: Any,
    ) -> Decision:
        return Decision(
            action=action or cfg.action,  # type: ignore[arg-type]
            control_id=self.id,
            reason=reason,
            score=score,
            threshold=cfg.threshold,
            severity=cfg.severity,
            findings=findings or [],
            owasp=list(cfg.owasp or self.owasp),
            **kw,
        )


@runtime_checkable
class Detector(Protocol):
    """Discovered from `DETECTORS: list[Detector]` in aegis/redaction/detectors/*.py."""

    id: str  # "pii.pesel"
    entity: str  # "PESEL" (canonical entity, CONTRACTS section 3.4)
    data_class: DataClass
    category: str  # pii | pci | secret | metadata
    languages: tuple[str, ...]  # () = language-agnostic

    def detect(self, text: str) -> list[Span]:
        """Pure, synchronous, deterministic, no I/O. Validate checksums before returning spans."""
        ...


@runtime_checkable
class ProviderAdapter(Protocol):
    """Wire-format codec. Discovered from `ADAPTERS: list[ProviderAdapter]` in aegis/proxy/adapters/*.py."""

    wire: Wire

    def parse_request(self, body: dict[str, Any], headers: Mapping[str, str]) -> Interaction:
        """kind=model_call, surface=model.request; fills model, segments, max_output_tokens,
        est_input_tokens. Thinking blocks -> redactable=False; tool_result blocks -> trusted=False."""
        ...

    def parse_response(self, body: dict[str, Any]) -> Interaction:
        """surface=model.response, direction=in."""
        ...

    def apply_segments(self, body: dict[str, Any], segments: list[TextSegment]) -> dict[str, Any]:
        """Write (possibly redacted) segment texts back into a copy of body by segment.path."""
        ...

    def parse_usage(self, body: dict[str, Any]) -> Usage: ...

    def blocked_response(
        self,
        verdict: Verdict,
        *,
        model: str | None,
        stream: bool,
        style: Literal["message", "error"],
    ) -> tuple[int, dict[str, Any] | bytes, dict[str, str]]:
        """(status, body, headers) in this wire's format. style=message => synthetic assistant
        reply '[Aegis] Blocked by <control>: <reason>'; style=error => wire error envelope."""
        ...


# ================================================================ services (on the Runtime)
class EventBus(Protocol):
    def publish(self, event: str, data: Any) -> BusMessage:
        """Non-blocking. `data` is a dict or a pydantic model (dumped with mode="json")."""
        ...

    def subscribe(
        self, events: set[str] | None = None, *, replay: int = 0
    ) -> AsyncIterator[BusMessage]: ...

    def recent(self, n: int = 100, events: set[str] | None = None) -> list[BusMessage]: ...


class PolicyStore(Protocol):
    def snapshot(self) -> PolicySnapshot: ...

    def control_config(self, control_id: str) -> ControlConfig | None: ...

    def current_yaml(self) -> str: ...

    async def validate(self, yaml_text: str) -> ValidationReport: ...

    def diff(self, yaml_text: str) -> list[PolicyChange]: ...

    async def propose(
        self,
        actor: Identity,
        *,
        yaml_text: str | None = None,
        patch: list[PatchOp] | None = None,
        reason: str | None = None,
        base_version: int | None = None,
        source: Source = "dashboard",
    ) -> ApplyResult:
        """Governed change: validate -> diff -> pipeline(config.change) -> apply or pending approval."""
        ...

    async def apply_yaml(
        self,
        yaml_text: str,
        *,
        actor: Identity | None,
        source: str,
        reason: str | None = None,
        base_version: int | None = None,
    ) -> ApplyResult:
        """Ungoverned apply (file watcher, approval executor, startup): validate -> self-test ->
        atomic swap -> persist -> audit policy.applied -> bus policy.applied."""
        ...

    async def apply_patch(
        self, patch: list[PatchOp], *, actor: Identity | None, source: str, reason: str | None = None
    ) -> ApplyResult: ...

    async def rollback(
        self, version: int, *, actor: Identity | None, reason: str | None = None
    ) -> ApplyResult: ...

    def history(self, limit: int = 50) -> list[PolicyVersionInfo]: ...

    def get_version_yaml(self, version: int) -> str | None: ...

    def on_change(self, callback: Callable[[PolicySnapshot], Any]) -> None:
        """Register a callback (sync or async) invoked after each successful swap."""
        ...


class OrgService(Protocol):
    async def resolve_identity(
        self, headers: Mapping[str, str], *, hints: Mapping[str, str] | None = None
    ) -> Identity:
        """Data plane: aegis_* key (Authorization/x-api-key) > X-Aegis-Agent > X-Aegis-Member >
        hints (e.g. {"agent_id": "claude-code@platform"}) > anonymous agent. Never consumes
        non-aegis keys (they are passed through to the upstream untouched)."""
        ...

    async def resolve_viewer(
        self, headers: Mapping[str, str], query: Mapping[str, str] | None = None
    ) -> Identity:
        """Dashboard: X-Aegis-View-As header or ?view_as= query; default = first owner."""
        ...

    async def org(self) -> Org: ...

    async def list_teams(self) -> list[Team]: ...

    async def list_members(self) -> list[Member]: ...

    async def list_agents(self) -> list[Agent]: ...

    async def get_member(self, member_id: str) -> Member | None: ...

    async def get_agent(self, agent_id: str) -> Agent | None: ...

    async def members_with_role(self, min_role: Role, team_id: str | None = None) -> list[Member]: ...

    async def resources(self) -> dict[str, Any]:
        """Seed `resources` inventory: {"databases": [{id, environment, tables: [{name,
        sensitivity, categories}]}], "vendors": [{id, name, approved, host, plans}]}."""
        ...


class BudgetLedger(Protocol):
    def scopes_for(self, identity: Identity, session_id: str) -> list[str]:
        """Budget chain checked with AND semantics, e.g. ['org:acme-capital', 'team:trading',
        'agent:trading-copilot@trading', 'session:ses_1']. `member:<id>` is included only when the
        principal is a human member (agents are budgeted per agent, not per sponsor)."""
        ...

    async def reserve(
        self, ctx: RequestContext, estimate: Usage, scopes: list[str] | None = None
    ) -> Reservation | BudgetDenial:
        """Atomic check-and-reserve across every level (AND). Denial names the scope that tripped."""
        ...

    async def settle(self, reservation: Reservation, actual: Usage) -> list[BudgetStatus]: ...

    async def release(self, reservation: Reservation) -> None: ...

    async def status(self, scope: str | None = None) -> list[BudgetStatus]: ...

    async def reset(self, scope: str | None = None) -> None: ...

    def price(self, model: str | None, usage: Usage) -> float:
        """USD for this usage according to config/pricing.yaml (local models: compute_s shadow price)."""
        ...


ApprovalExecutor = Callable[[ApprovalRequest], Awaitable[dict[str, Any] | None]]


class ApprovalService(Protocol):
    def route(
        self,
        *,
        kind: ApprovalKind,
        action_type: str,
        requester: Identity,
        amount_usd: float | None = None,
        resource: str | None = None,
        labels: Mapping[str, str] | None = None,
        changes: list[PolicyChange] | None = None,
    ) -> ApprovalRoute:
        """First matching rule: approvals.config_rules for kind config_change, approvals.rules for
        every other kind; no match -> defaults.default_config_approver / default_approver."""
        ...

    def can_approve(self, voter: Identity, req: ApprovalRequest) -> tuple[bool, str]: ...

    def fingerprint(self, identity: Identity, interaction: Interaction) -> str:
        """HMAC-SHA256 (aegis.core.crypto.hmac_hex, purpose "approval") over canonical JSON of
        {org, principal, action_type or tool_name, tool_args minus volatile keys, resource, amount}."""
        ...

    async def find_preapproved(
        self, ctx: RequestContext, interaction: Interaction
    ) -> ApprovalRequest | None:
        """Approved, unexpired, uses < max_uses; matched by ctx.approval_token or fingerprint.
        Consumes one use when found; redemptions of the same approval within 30 s count as one use
        (the hook and the MCP proxy both see the same call)."""
        ...

    async def request(
        self, ctx: RequestContext, interaction: Interaction, decision: Decision
    ) -> ApprovalRequest:
        """Create (or reuse the pending one with the same fingerprint) from decision.approval.
        Applies auto/deny routes immediately. Publishes approval.created + audit."""
        ...

    async def wait(self, approval_id: str, timeout_s: float) -> ApprovalRequest: ...

    async def vote(
        self,
        approval_id: str,
        voter: Identity,
        decision: Literal["approve", "deny"],
        comment: str | None = None,
    ) -> ApprovalRequest:
        """Raises PermissionError if the voter may not decide. Runs the executor on approval."""
        ...

    async def cancel(self, approval_id: str, actor: Identity) -> ApprovalRequest: ...

    async def get(self, approval_id: str) -> ApprovalRequest | None: ...

    async def list_requests(
        self,
        *,
        status: ApprovalStatus | None = None,
        kind: ApprovalKind | None = None,
        limit: int = 200,
    ) -> list[ApprovalRequest]: ...

    async def create_manual(self, requester: Identity, draft: ApprovalDraft) -> ApprovalRequest: ...

    def register_executor(self, kind: ApprovalKind, fn: ApprovalExecutor) -> None: ...


class AuditSink(Protocol):
    async def record(self, event: AuditEvent) -> AuditEvent:
        """Assign seq, chain hash, append JSONL, index in SQLite. Must never raise to callers."""
        ...

    async def verify(self) -> AuditVerifyResult: ...

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: Any = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> tuple[list[AuditEvent], str | None]: ...

    def export(self, fmt: Literal["jsonl", "csv", "ocsf"], **filters: Any) -> AsyncIterator[bytes]: ...


class MetricsSink(Protocol):
    def observe_verdict(self, ctx: RequestContext, interaction: Interaction, verdict: Verdict) -> None: ...

    def observe_upstream(
        self, provider: str, model: str | None, seconds: float, usage: Usage | None = None
    ) -> None: ...

    def observe_overhead(self, phase: str, seconds: float) -> None: ...

    def inc(self, name: str, labels: Mapping[str, str] | None = None, value: float = 1.0) -> None: ...

    def set_gauge(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None: ...

    def render(self) -> tuple[bytes, str]:
        """Prometheus exposition bytes + content type (for GET /metrics)."""
        ...


class RedactionEngine(Protocol):
    def detect(
        self, text: str, *, entities: set[str] | None = None, use_ner: bool = False
    ) -> list[Span]: ...

    async def detect_async(
        self, text: str, *, entities: set[str] | None = None, use_ner: bool = True
    ) -> list[Span]: ...

    def apply(
        self, ctx: RequestContext, segments: list[TextSegment], findings: list[Finding]
    ) -> tuple[list[TextSegment], list[Redaction]]:
        """Merge overlapping spans (longest wins), tokenize via the session vault, return new
        segments + redaction records. Non-redactable segments are left untouched."""
        ...

    def rehydrate(self, ctx: RequestContext, text: str) -> str:
        """Replace this session's placeholders with original values (local delivery only)."""
        ...

    def mask_for_log(self, text: str, max_len: int = 160) -> str:
        """Irreversible masking for excerpts/previews/logs (e.g. 411111******1111, [EMAIL])."""
        ...

    def detectors(self) -> list[Detector]: ...


class SemanticEngine(Protocol):
    async def injection_score(self, text: str) -> ScoreResult: ...

    async def moderate(self, text: str) -> ScoreResult: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def similarity(self, text: str, references: list[str]) -> float: ...

    async def judge(self, rule: str, text: str) -> ScoreResult: ...

    def status(self) -> dict[str, Any]:
        """{"mode": "on|off|auto", "degraded": bool, "models": [{"name", "backend", "loaded", "p50_ms"}]}"""
        ...


class FeedManager(Protocol):
    @property
    def serial(self) -> int | None: ...

    def status(self) -> FeedStatus: ...

    async def refresh(self) -> FeedStatus: ...

    def signatures(self) -> list[dict[str, Any]]: ...


class SessionStore(Protocol):
    def get(self, session_id: str) -> SessionState:
        """Get or create."""
        ...

    def all(self) -> list[SessionState]: ...


class ControlRegistry(Protocol):
    def all(self) -> list[Control]: ...

    def get(self, control_id: str) -> Control | None: ...


class Pipeline(Protocol):
    def new_context(
        self,
        *,
        source: Source,
        identity: Identity,
        session_id: str | None = None,
        headers: Mapping[str, str] | None = None,
        approval_token: str | None = None,
        wait_for_approval_s: float = 0.0,
        dry_run: bool = False,
    ) -> RequestContext: ...

    async def evaluate(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        *,
        policy: PolicySnapshot | None = None,
        dry_run: bool = False,
    ) -> Verdict:
        """enrich -> deterministic -> semantic (parallel, timeouts, fail_mode) -> combine ->
        approvals -> redaction/mutations -> audit + metrics + bus `decision`."""
        ...

    async def complete(
        self, ctx: RequestContext, interaction: Interaction, verdict: Verdict, outcome: Outcome
    ) -> None:
        """After execution: on_complete hooks (budget settle, taint, loops), usage audit."""
        ...

    def wire(self, decision_id: str) -> WireView | None: ...

    def attach_response(
        self, decision_id: str, *, response_raw: str | None, response_local: str | None
    ) -> None: ...


class RuntimeProto(Protocol):
    """Service container; core-gateway's aegis.core.runtime.Runtime implements it.
    Obtain with `from aegis.core.runtime import get_runtime` or FastAPI dep `aegis.core.deps.get_rt`."""

    settings: Any
    bus: EventBus
    policy: PolicyStore
    org: OrgService
    ledger: BudgetLedger
    approvals: ApprovalService
    audit: AuditSink
    metrics: MetricsSink
    redactor: RedactionEngine
    semantic: SemanticEngine
    feed: FeedManager
    sessions: SessionStore
    controls: ControlRegistry
    pipeline: Pipeline

    def db(self) -> sqlite3.Connection:
        """New SQLite connection (WAL, row_factory=sqlite3.Row, check_same_thread=False)."""
        ...


__all__ = [
    "ApprovalExecutor", "ApprovalService", "AuditSink", "BaseControl", "BudgetLedger", "Control",
    "ControlRegistry", "Detector", "EventBus", "FeedManager", "MetricsSink", "OrgService",
    "Pipeline", "PolicyStore", "ProviderAdapter", "RedactionEngine", "RuntimeProto",
    "SemanticEngine", "SessionStore",
    # re-exported for convenience
    "Direction", "Redaction", "BudgetDenial", "Reservation",
]
