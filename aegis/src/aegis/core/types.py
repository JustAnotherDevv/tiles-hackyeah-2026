"""Aegis core types. FROZEN: materialized verbatim from docs/CONTRACTS.md section 3.1.

Do not edit. Need a field? Use the `meta` / `labels` / `data` escape hatches and request
the change in your report.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------- enums (Literal aliases)
Action = Literal["allow", "log", "redact", "require_approval", "block"]
ACTION_PRECEDENCE: dict[str, int] = {
    "allow": 0, "log": 1, "redact": 2, "require_approval": 3, "block": 4,
}
Kind = Literal["model_call", "tool_call", "mcp", "egress", "a2a", "config_change"]
Direction = Literal["in", "out"]  # out = toward the destination (request/args); in = coming back
DestClass = Literal["local", "remote", "third_party"]
Role = Literal["owner", "admin", "member", "agent"]
ROLE_RANK: dict[str, int] = {"agent": 0, "member": 1, "admin": 2, "owner": 3}
Severity = Literal["info", "low", "medium", "high", "critical"]
DataClass = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "SECRET"]
Mode = Literal["enforce", "monitor", "off"]
FailMode = Literal["closed", "open", "deterministic_only"]
ControlKind = Literal["deterministic", "semantic", "hybrid", "stateful"]
Surface = Literal[
    "prompt.user",      # user prompt entering an agent (Claude Code UserPromptSubmit, playground)
    "model.request",    # agent -> model request body
    "model.response",   # model -> agent response
    "model.admin",      # model management (Ollama /api/pull|create|push|delete|copy)
    "tool.input",       # agent -> tool call arguments (PreToolUse, /v1/guard)
    "tool.output",      # tool -> agent result (PostToolUse)
    "artifact.file",    # model / package artifact bytes (SIG-02)
    "mcp.init",         # MCP initialize / server launch command
    "mcp.list",         # MCP tools/list (and prompts/resources list) result
    "mcp.call",         # MCP tools/call request
    "mcp.result",       # MCP tools/call result
    "egress.request",   # third-party HTTP request
    "egress.response",  # third-party HTTP response
    "a2a.message",      # agent -> peer agent
    "a2a.result",       # peer agent -> agent
    "config.change",    # policy / config change proposal
]
Source = Literal[
    "proxy", "mcp", "hook", "guard", "egress", "playground", "dashboard", "selftest", "test",
]
SegmentRole = Literal[
    "system", "user", "assistant", "tool_args", "tool_result", "tool_description",
    "document", "header", "url", "other",
]
ApproverLevel = Literal["auto", "self", "admin", "owner", "deny"]
APPROVER_RANK: dict[str, int] = {"auto": 0, "self": 1, "admin": 2, "owner": 3, "deny": 99}
ApprovalKind = Literal["action", "config_change", "budget_raise", "mcp_pin"]
ApprovalStatus = Literal["pending", "approved", "denied", "expired", "cancelled"]
BudgetDimension = Literal["usd", "tokens", "compute_s", "requests", "tool_calls", "spend_usd"]
BudgetWindow = Literal["hour", "day", "week", "month", "session", "total"]
BudgetState = Literal["ok", "soft", "hard", "killed"]
AuditEventType = Literal[
    "decision",
    "approval.created", "approval.decided", "approval.expired", "approval.executed",
    "policy.applied", "policy.rejected", "policy.rollback",
    "feed.updated", "feed.rejected",
    "budget.threshold", "budget.exceeded", "killswitch.toggled",
    "org.changed", "mcp.tool_changed", "system",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Time-sortable id: '<prefix>_' + 12 hex chars of epoch-ms + 14 random hex chars.
    Prefixes: req dec int apr evt res ses (see CONTRACTS section 3.4)."""
    return f"{prefix}_{int(time.time() * 1000):012x}{os.urandom(7).hex()}"


# ---------------------------------------------------------------- identity & org
class Identity(BaseModel):
    """Who is acting. For agents: agent_id is the service identity, member_id its owning human."""

    org_id: str = "default"
    team_id: str | None = None
    member_id: str | None = None
    agent_id: str | None = None
    role: Role = "agent"
    display_name: str | None = None
    authenticated: bool = False

    @property
    def principal(self) -> str:
        if self.agent_id:
            return f"agent:{self.agent_id}"
        return f"member:{self.member_id or 'anonymous'}"


class Org(BaseModel):
    id: str
    name: str


class Team(BaseModel):
    id: str
    org_id: str
    name: str
    description: str | None = None
    color: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Member(BaseModel):
    id: str
    org_id: str
    team_id: str | None = None
    name: str
    email: str | None = None
    role: Literal["owner", "admin", "member"] = "member"
    title: str | None = None
    avatar_url: str | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    meta: dict[str, Any] = Field(default_factory=dict)  # e.g. teams, locale, avatar_color


class Agent(BaseModel):
    id: str
    org_id: str
    team_id: str | None = None
    owner_member_id: str | None = None  # the sponsoring human ("self" approver)
    name: str
    kind: Literal["claude-code", "scripted", "sdk", "mcp-client", "other"] = "other"
    description: str | None = None
    profile: str | None = None  # per-agent strictness profile override; "local" = local-only agent
    allowed_models: list[str] = Field(default_factory=lambda: ["*"])
    allowed_tools: list[str] = Field(default_factory=lambda: ["*"])
    denied_tools: list[str] = Field(default_factory=list)
    max_destination: DestClass | None = None  # most-remote destination class allowed
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    last_seen: datetime | None = None
    meta: dict[str, Any] = Field(default_factory=dict)  # e.g. data_grants, action_types


# ---------------------------------------------------------------- interactions
class Destination(BaseModel):
    name: str = "unknown"  # "anthropic" | "ollama" | "mcp:corpdb" | "egress:api.stripe.com" | "aegis"
    dest_class: DestClass = "remote"
    provider: str | None = None
    host: str | None = None
    url: str | None = None


class TextSegment(BaseModel):
    """One inspectable piece of text inside a payload. `path` locates it in the raw body."""

    path: str  # e.g. "messages[2].content[0].text", "params.arguments.sql", "tool_input.command"
    text: str
    role: SegmentRole = "user"
    trusted: bool = True  # False for tool results, web pages, MCP descriptions, A2A replies
    redactable: bool = True  # False for e.g. Anthropic thinking blocks


class AppliesTo(BaseModel):
    """Which interactions a control looks at. Empty set = any."""

    kinds: set[Kind] = Field(default_factory=set)
    surfaces: set[Surface] = Field(default_factory=set)
    directions: set[Direction] = Field(default_factory=set)
    destinations: set[DestClass] = Field(default_factory=set)

    def matches(self, i: Interaction) -> bool:
        return (
            (not self.kinds or i.kind in self.kinds)
            and (not self.surfaces or i.surface in self.surfaces)
            and (not self.directions or i.direction in self.directions)
            and (not self.destinations or i.destination.dest_class in self.destinations)
        )


class Interaction(BaseModel):
    """Normalized unit the pipeline evaluates (one per request or response hop)."""

    id: str = ""
    kind: Kind
    surface: Surface
    direction: Direction = "out"
    destination: Destination = Field(default_factory=Destination)
    model: str | None = None
    tool_name: str | None = None  # normalized: built-in "Bash"; MCP "<server>.<tool>"
    tool_args: dict[str, Any] | None = None
    mcp_server: str | None = None
    mcp_method: str | None = None
    http_method: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)  # outbound headers (lower-case keys)
    segments: list[TextSegment] = Field(default_factory=list)
    raw: Any = Field(default=None, exclude=True)  # original body; never serialized or logged
    action_type: str | None = None  # governed action, e.g. "spend.subscription", "db.read"
    amount_usd: float | None = None
    resource: str | None = None  # e.g. "db:customers", "api.stripe.com"
    labels: dict[str, str] = Field(default_factory=dict)  # e.g. {"env": "prod"}
    est_input_tokens: int | None = None
    max_output_tokens: int | None = None
    parent_id: str | None = None  # request interaction id when this is a response
    meta: dict[str, Any] = Field(default_factory=dict)

    def text(self) -> str:
        return "\n".join(s.text for s in self.segments)


# ---------------------------------------------------------------- findings & decisions
class Span(BaseModel):
    """Detector output (character offsets into the scanned text)."""

    start: int
    end: int
    entity: str  # canonical entity name, see CONTRACTS section 3.4
    data_class: DataClass
    detector_id: str
    score: float = 1.0
    category: str = "pii"  # pii | pci | secret | metadata


class Finding(BaseModel):
    control_id: str
    detector: str  # e.g. "pii.pesel", "secret.aws_access_key", "inj.sig.ignore_previous"
    category: str = "other"  # pii|pci|secret|metadata|injection|exfil|command|scope|taint|mcp|
    #                          budget|loop|signature|governance|content|model|approval
    entity: str | None = None
    data_class: DataClass | None = None
    severity: Severity = "medium"
    score: float = 1.0
    segment_index: int | None = None  # index into Interaction.segments
    start: int | None = None
    end: int | None = None
    excerpt: str | None = None  # MUST already be masked (rt.redactor.mask_for_log)
    replacement: str | None = None  # explicit replacement; None + redact => vault placeholder
    meta: dict[str, Any] = Field(default_factory=dict)


class Mutation(BaseModel):
    """Structural change applied by the pipeline when the final action is redact/allow."""

    target: Literal["body", "header", "route"] = "body"
    op: Literal["set", "remove"] = "set"
    path: str  # body: dotted path with [i] ("max_tokens", "result.tools[3]"); header: name;
    #            route: "model" | "provider"
    value: Any = None
    reason: str | None = None


class ApprovalDraft(BaseModel):
    """Attached to a require_approval Decision; the pipeline turns it into an ApprovalRequest."""

    kind: ApprovalKind = "action"
    action_type: str
    title: str
    summary: str | None = None
    amount_usd: float | None = None
    resource: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)  # redacted details / config proposal


class Decision(BaseModel):
    """One control's verdict on one interaction."""

    action: Action = "allow"
    control_id: str
    reason: str = ""
    score: float | None = None
    threshold: float | None = None
    approval_id: str | None = None
    mode: Literal["enforce", "monitor"] = "enforce"
    severity: Severity = "medium"
    findings: list[Finding] = Field(default_factory=list)
    mutations: list[Mutation] = Field(default_factory=list)
    approval: ApprovalDraft | None = None
    http_status: int | None = None  # override: 402 budget, 429 rate limit
    error_type: str | None = None  # policy_blocked|budget_exceeded|rate_limited|killed|...
    retry_after_s: int | None = None
    degraded: bool = False
    latency_ms: float = 0.0
    owasp: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class Redaction(BaseModel):
    segment_index: int
    path: str
    start: int  # offsets in the ORIGINAL segment text
    end: int
    entity: str
    data_class: DataClass | None = None
    placeholder: str  # "[PESEL_1]" (reversible) or "[REDACTED:SECRET]" (irreversible)
    control_id: str
    reversible: bool = True


# ---------------------------------------------------------------- approvals
class ApprovalVote(BaseModel):
    member_id: str
    role: Role
    decision: Literal["approve", "deny"]
    comment: str | None = None
    ts: datetime = Field(default_factory=utcnow)


class ApprovalRoute(BaseModel):
    required_role: ApproverLevel
    two_person: bool = False
    rule_id: str | None = None
    ttl_s: int = 900
    max_uses: int = 1


class ApprovalRequest(BaseModel):
    id: str  # "apr_..."
    org_id: str = "default"
    team_id: str | None = None
    kind: ApprovalKind = "action"
    action_type: str
    title: str
    summary: str | None = None
    requester: Identity
    amount_usd: float | None = None
    resource: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)  # redacted; never raw secrets/PII
    fingerprint: str
    required_role: ApproverLevel
    two_person: bool = False
    rule_id: str | None = None
    votes: list[ApprovalVote] = Field(default_factory=list)
    status: ApprovalStatus = "pending"
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by: list[str] = Field(default_factory=list)  # member ids
    request_id: str | None = None
    decision_id: str | None = None
    control_id: str | None = None
    uses: int = 0
    max_uses: int = 1
    execution: dict[str, Any] | None = None  # executor result, e.g. {"policy_version": 12}


# ---------------------------------------------------------------- usage, budgets
class Usage(BaseModel):
    input_tokens: int = 0  # total input incl. cache reads
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    compute_s: float = 0.0  # local model compute seconds
    requests: int = 1
    tool_calls: int = 0
    cost_usd: float = 0.0  # AI cost (priced via config/pricing.yaml)
    spend_usd: float = 0.0  # real money moved by agent actions (purchases)
    estimated: bool = True


class BudgetStatus(BaseModel):
    scope: str  # "org:acme" | "team:research" | "member:maya" | "agent:analyst-bot" | "session:x"
    scope_type: Literal["org", "team", "member", "agent", "session", "model", "tool"]
    dimension: BudgetDimension
    window: BudgetWindow
    limit: float
    used: float
    reserved: float = 0.0
    pct: float = 0.0  # (used + reserved) / limit * 100
    state: BudgetState = "ok"
    resets_at: datetime | None = None
    label: str | None = None


class Reservation(BaseModel):
    id: str
    scopes: list[str]
    estimate: Usage
    created_at: datetime = Field(default_factory=utcnow)
    meta: dict[str, Any] = Field(default_factory=dict)


class BudgetDenial(BaseModel):
    scope: str
    dimension: BudgetDimension
    window: BudgetWindow
    limit: float
    used: float
    requested: float
    action: Literal["block", "require_approval", "downgrade"] = "block"
    message: str = ""
    resets_at: datetime | None = None


# ---------------------------------------------------------------- pipeline results
class Verdict(BaseModel):
    """Combined result of one pipeline evaluation."""

    id: str  # decision id "dec_..."
    request_id: str
    interaction_id: str
    action: Action
    primary: Decision | None = None  # the decision that determined `action`
    decisions: list[Decision] = Field(default_factory=list)
    segments: list[TextSegment] = Field(default_factory=list)  # after redaction
    redactions: list[Redaction] = Field(default_factory=list)
    mutations: list[Mutation] = Field(default_factory=list)
    approval: ApprovalRequest | None = None
    policy_version: int = 0
    feed_serial: int | None = None
    latency_ms: float = 0.0
    degraded: bool = False
    dry_run: bool = False
    ts: datetime = Field(default_factory=utcnow)


class Outcome(BaseModel):
    """What happened after an allowed interaction was executed (for settle / on_complete)."""

    status_code: int = 200
    usage: Usage = Field(default_factory=Usage)
    upstream_ms: float | None = None
    error: str | None = None
    provider: str | None = None
    model_used: str | None = None
    response_verdict_id: str | None = None


class RequestContext(BaseModel):
    """Per-request context shared by every control evaluation of that request."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str
    trace_id: str = ""
    session_id: str = "default"
    identity: Identity = Field(default_factory=Identity)
    source: Source = "proxy"
    started_at: datetime = Field(default_factory=utcnow)
    t0: float = 0.0  # time.perf_counter() at ingress
    policy_version: int = 0
    feed_serial: int | None = None
    approval_token: str | None = None  # X-Aegis-Approval
    wait_for_approval_s: float = 0.0
    dry_run: bool = False
    client_ip: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)  # inbound, lower-case, secrets removed
    state: dict[str, Any] = Field(default_factory=dict)  # scratch shared across controls
    timings: dict[str, float] = Field(default_factory=dict)  # stage -> ms (Server-Timing)
    policy: Any = Field(default=None, exclude=True)  # PolicySnapshot pinned at ingress


class ControlHit(BaseModel):
    control_id: str
    action: Action
    mode: Literal["enforce", "monitor"] = "enforce"
    score: float | None = None
    latency_ms: float = 0.0
    degraded: bool = False


class DecisionSummary(BaseModel):
    """Row of the live feed (SSE `decision`) and of GET /api/decisions."""

    id: str
    ts: datetime
    request_id: str
    action: Action
    kind: Kind
    surface: Surface
    direction: Direction
    destination: Destination
    model: str | None = None
    tool_name: str | None = None
    action_type: str | None = None
    amount_usd: float | None = None
    identity: Identity
    session_id: str
    source: Source
    control_id: str | None = None
    reason: str = ""
    score: float | None = None
    threshold: float | None = None
    controls: list[ControlHit] = Field(default_factory=list)  # controls that returned non-allow
    redaction_count: int = 0
    entities: list[str] = Field(default_factory=list)
    approval_id: str | None = None
    latency_ms: float = 0.0
    upstream_ms: float | None = None
    policy_version: int = 0
    feed_serial: int | None = None
    degraded: bool = False
    cost_usd: float | None = None
    tokens: int | None = None
    preview: str = ""  # masked/redacted text, <= 160 chars
    dry_run: bool = False


class WireView(BaseModel):
    """Before/after view for the drill-down. Held IN MEMORY ONLY (never persisted)."""

    decision_id: str
    original: list[TextSegment] = Field(default_factory=list)  # raw (local display only)
    outbound: list[TextSegment] = Field(default_factory=list)  # what actually left
    response_raw: str | None = None  # upstream response (placeholders intact)
    response_local: str | None = None  # rehydrated text shown to the local user
    upstream_request_preview: dict[str, Any] | None = None  # redacted outbound JSON


class DecisionDetail(DecisionSummary):
    decisions: list[Decision] = Field(default_factory=list)
    redactions: list[Redaction] = Field(default_factory=list)
    mutations: list[Mutation] = Field(default_factory=list)
    usage: Usage | None = None
    wire: WireView | None = None
    audit_seq: int | None = None
    audit_hash: str | None = None


# ---------------------------------------------------------------- audit, events, misc
class AuditEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default="aegis.audit/1", alias="schema")
    event_id: str
    seq: int = 0  # assigned by the audit log
    ts: datetime = Field(default_factory=utcnow)
    event_type: AuditEventType
    actor: Identity | None = None
    request_id: str | None = None
    decision_id: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    kind: Kind | None = None
    surface: Surface | None = None
    direction: Direction | None = None
    destination: Destination | None = None
    model: str | None = None
    tool_name: str | None = None
    action_type: str | None = None
    amount_usd: float | None = None
    resource: str | None = None
    action: Action | None = None
    control_id: str | None = None
    reason: str | None = None
    score: float | None = None
    threshold: float | None = None
    controls: list[ControlHit] = Field(default_factory=list)
    redactions: list[Redaction] = Field(default_factory=list)
    usage: Usage | None = None
    latency_ms: float | None = None
    policy_version: int | None = None
    feed_serial: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)  # event-specific, already redacted
    prev_hash: str = ""
    hash: str = ""


class AuditVerifyResult(BaseModel):
    ok: bool
    records: int = 0
    head_hash: str = ""
    broken_at_seq: int | None = None
    files: int = 0
    checked_at: datetime = Field(default_factory=utcnow)
    message: str = ""


class BusMessage(BaseModel):
    id: int
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=utcnow)


class ScoreResult(BaseModel):
    score: float  # 0..1 probability of the positive (malicious / unsafe / violating) class
    label: str = ""
    model: str = "heuristic"
    latency_ms: float = 0.0
    degraded: bool = False  # True when a fallback (heuristic) replaced the configured model
    categories: list[str] = Field(default_factory=list)
    reason: str | None = None


class FeedStatus(BaseModel):
    feed_id: str = "aegis-threat-intel"
    url: str | None = None
    status: Literal["ok", "stale", "rejected", "unreachable", "disabled", "seed"] = "disabled"
    serial: int | None = None
    version: str | None = None
    published: datetime | None = None
    expires: datetime | None = None
    key_id: str | None = None
    signatures_total: int = 0
    signatures_active: int = 0
    signatures_monitor: int = 0
    signatures_quarantined: int = 0
    last_check: datetime | None = None
    last_update: datetime | None = None
    last_error: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)


class SessionState(BaseModel):
    """Per-session mutable state for stateful controls. Namespace keys by owner: data["taint"]."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    identity: Identity | None = None
    created_at: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)
    data: dict[str, Any] = Field(default_factory=dict)
