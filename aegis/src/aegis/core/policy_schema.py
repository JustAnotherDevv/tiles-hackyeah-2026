"""Aegis policy file schema (config/policy.yaml). FROZEN: materialized verbatim from
docs/CONTRACTS.md section 4.2. Loading/validation/hot-reload logic lives in aegis.policy
(policy-engine); this module is only the shape.

Top level forbids unknown keys (typo detection for judges' live edits); every section allows
extra keys (forward compatible, reported as warnings by the validator).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aegis.core.types import (
    Action,
    ApprovalKind,
    ApprovalRequest,
    ApproverLevel,
    BudgetWindow,
    DataClass,
    DestClass,
    FailMode,
    Kind,
    Mode,
    Severity,
    Surface,
    utcnow,
)

Wire = Literal["anthropic", "openai", "ollama"]
Profile = Literal["permissive", "balanced", "strict", "paranoid"]


class _Section(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ---------------------------------------------------------------- controls
class ControlScope(_Section):
    orgs: list[str] = Field(default_factory=lambda: ["*"])
    teams: list[str] = Field(default_factory=lambda: ["*"])
    members: list[str] = Field(default_factory=lambda: ["*"])
    agents: list[str] = Field(default_factory=lambda: ["*"])
    kinds: list[Kind] = Field(default_factory=list)  # empty = control's own applies_to
    surfaces: list[Surface] = Field(default_factory=list)
    destinations: list[DestClass] = Field(default_factory=list)


class PolicyTest(_Section):
    """Inline golden test, run by the self-test gate before a policy version is applied."""

    name: str
    control: str | None = None  # expected deciding control id (attribution); None = any
    expect: Action
    kind: Kind = "model_call"
    surface: Surface = "model.request"
    destination: DestClass = "remote"
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    amount_usd: float | None = None
    agent: str | None = None  # agent id to evaluate as (default: "selftest")


class ControlConfig(_Section):
    id: str  # e.g. "DLP-01"
    name: str | None = None
    enabled: bool = True
    mode: Mode = "enforce"
    action: Action = "block"
    threshold: float | None = None  # semantic score that triggers `action`
    adherence_pct: float | None = None  # topic adherence minimum (INJ-03)
    severity: Severity = "medium"
    fail_mode: FailMode = "closed"
    timeout_ms: int = 250
    scope: ControlScope = Field(default_factory=ControlScope)
    params: dict[str, Any] = Field(default_factory=dict)  # control-specific, validated by owner
    owasp: list[str] = Field(default_factory=list)
    tests: list[PolicyTest] = Field(default_factory=list)


# ---------------------------------------------------------------- global sections
class PolicyMetadata(_Section):
    name: str = "aegis-policy"
    description: str | None = None
    owner: str | None = None


class Defaults(_Section):
    mode: Mode = "enforce"
    fail_mode: FailMode = "closed"
    semantic_timeout_ms: int = 400
    stream_mode: Literal["buffered", "holdback", "passthrough"] = "buffered"
    block_response: Literal["message", "error"] = "message"  # model proxies: synthetic reply or error
    require_auth: bool = False  # demo: identity may come from X-Aegis-* headers
    audit_content: bool = False  # never store raw content unless explicitly enabled
    rehydrate_responses: bool = True
    max_body_bytes: int = 8_000_000


def _default_matrix() -> dict[str, dict[str, str]]:
    return {
        "PUBLIC": {"local": "allow", "remote": "allow", "third_party": "allow"},
        "INTERNAL": {"local": "allow", "remote": "redact", "third_party": "redact"},
        "CONFIDENTIAL": {"local": "allow", "remote": "redact", "third_party": "redact"},
        "RESTRICTED": {"local": "redact", "remote": "redact", "third_party": "block"},
        "SECRET": {"local": "log", "remote": "block", "third_party": "block"},
    }


class DestinationsSection(_Section):
    matrix: dict[DataClass, dict[DestClass, Action]] = Field(default_factory=_default_matrix)
    local_tools: list[str] = Field(
        default_factory=lambda: ["Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "LS",
                                 "NotebookEdit", "Bash", "TodoWrite"])
    third_party_tools: list[str] = Field(default_factory=lambda: ["WebFetch", "WebSearch"])
    internal_domains: list[str] = Field(
        default_factory=lambda: ["*.corp.local", "*.internal", "*.acme.test"])
    allowed_link_domains: list[str] = Field(default_factory=list)
    egress_allowlist: list[str] = Field(default_factory=list)  # empty = rely on controls


class ProviderConfig(_Section):
    wire: Wire
    base_url: str
    destination: DestClass = "remote"
    api_key_env: str | None = None
    passthrough_auth: bool = False  # forward client Authorization/x-api-key (Claude Code login)
    enabled_if_env: str | None = None
    timeout_s: float = 120.0


class ModelRoute(_Section):
    match: str  # glob over the requested model name
    provider: str  # key of `providers`
    wire: Wire | None = None  # only for requests arriving on this wire (None = any)


class DowngradeRule(_Section):
    from_: str = Field(alias="from")
    to: str


class ModelsSection(_Section):
    allowed: list[str] = Field(default_factory=lambda: ["*"])
    denied: list[str] = Field(default_factory=list)
    routes: list[ModelRoute] = Field(default_factory=list)  # first match wins
    downgrade: list[DowngradeRule] = Field(default_factory=list)
    default_local: str | None = None


# ---------------------------------------------------------------- budgets
class BudgetLimit(_Section):
    scope: str  # org:<id> | team:<id> | member:<id> | agent:<id> | session:<id>|session:* |
    #             model:<glob> | tool:<glob>
    window: BudgetWindow = "day"
    usd: float | None = None
    tokens: int | None = None
    compute_s: float | None = None
    requests: int | None = None
    tool_calls: int | None = None
    spend_usd: float | None = None
    soft_pct: float | None = None
    on_soft: Literal["warn", "downgrade", "require_approval"] | None = None
    on_hard: Literal["block", "require_approval", "downgrade"] | None = None
    label: str | None = None


class BudgetDefaults(_Section):
    soft_pct: float = 80.0
    on_soft: Literal["warn", "downgrade", "require_approval"] = "warn"
    on_hard: Literal["block", "require_approval", "downgrade"] = "block"
    local_concurrency: int = 1
    max_output_tokens: int | None = 4096  # clamp (mutation) when a request asks for more


class LoopConfig(_Section):
    repeat: int = 3  # identical tool call fingerprint occurrences within `window`
    window: int = 20
    cycle_k: int = 3
    error_streak: int = 5
    max_steps_per_session: int = 200
    ladder: list[Literal["tool_error", "block", "kill"]] = Field(
        default_factory=lambda: ["tool_error", "block", "kill"])


class RateConfig(_Section):
    requests_per_min: int | None = 120
    tool_calls_per_min: int | None = 60


class KillSwitch(_Section):
    global_: bool = Field(default=False, alias="global")
    teams: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    sessions: list[str] = Field(default_factory=list)


class BudgetsSection(_Section):
    defaults: BudgetDefaults = Field(default_factory=BudgetDefaults)
    limits: list[BudgetLimit] = Field(default_factory=list)
    loops: LoopConfig = Field(default_factory=LoopConfig)
    rate: RateConfig = Field(default_factory=RateConfig)
    kill_switch: KillSwitch = Field(default_factory=KillSwitch)


# ---------------------------------------------------------------- governed actions & approvals
class ActionRule(_Section):
    """Classifies tool / MCP / egress calls into governed action types (used by GOV-04)."""

    id: str  # action type, e.g. "spend.subscription", "db.read", "db.write", "email.external"
    category: Literal["spend", "data_read", "data_write", "external_send", "code_exec",
                      "config", "other"] = "other"
    tools: list[str] = Field(default_factory=list)  # globs; MCP tools match "<server>.<tool>"
    surfaces: list[Surface] = Field(default_factory=list)
    args_match: dict[str, str] = Field(default_factory=dict)  # arg path -> RE2 regex (all must match)
    args_not_match: dict[str, str] = Field(default_factory=dict)  # arg path -> RE2 regex (none may match)
    url_hosts: list[str] = Field(default_factory=list)  # egress host globs
    amount_arg: str | None = None  # dotted path in tool_args -> USD amount
    resource_arg: str | None = None  # dotted path in tool_args -> resource string
    resource_regex: str | None = None  # first capture group of this regex applied to resource_arg
    resource_prefix: str = ""  # prepended to the resource, e.g. "db:" -> "db:customers"
    labels: dict[str, str] = Field(default_factory=dict)
    title: str | None = None  # "{agent} wants to spend ${amount} on {args.vendor}"


class ApprovalWhen(_Section):
    kind: list[ApprovalKind] | None = None
    action: list[str] | None = None  # globs over action_type (action rules) or change kind (config)
    amount_usd_gt: float | None = None
    amount_usd_lte: float | None = None
    resource_in: list[str] | None = None  # globs
    labels: dict[str, str] | None = None
    teams: list[str] | None = None
    agents: list[str] | None = None
    scope_type: list[str] | None = None  # budget changes: org|team|member|agent|session
    increase_pct_gt: float | None = None
    increase_pct_lte: float | None = None


class ApprovalRule(_Section):
    id: str
    description: str | None = None
    when: ApprovalWhen = Field(default_factory=ApprovalWhen)
    approver: ApproverLevel = "admin"
    two_person: bool = False
    ttl_s: int | None = None
    max_uses: int = 1


class ApprovalDefaults(_Section):
    ttl_s: int = 900
    on_timeout: Literal["deny"] = "deny"
    max_pending: int = 50
    default_approver: ApproverLevel = "admin"  # action requests matching no rule
    default_config_approver: ApproverLevel = "owner"  # config changes matching no rule
    hold_s: dict[str, float] = Field(default_factory=lambda: {
        "hook": 60, "mcp": 30, "egress": 15, "guard": 0, "proxy": 0,
        "playground": 0, "dashboard": 0})


class ApprovalsSection(_Section):
    defaults: ApprovalDefaults = Field(default_factory=ApprovalDefaults)
    rules: list[ApprovalRule] = Field(default_factory=list)  # first match wins
    config_rules: list[ApprovalRule] = Field(default_factory=list)  # first match wins


# ---------------------------------------------------------------- MCP & feeds
class McpServerConfig(_Section):
    transport: Literal["http", "stdio"] = "http"
    url: str | None = None  # upstream for transport=http
    command: list[str] | None = None  # exact launch command for transport=stdio
    destination: DestClass = "third_party"
    allowed_tools: list[str] = Field(default_factory=lambda: ["*"])
    pinned: bool = True
    package: str | None = None  # "name@version" (launch check, SIG-03)
    headers_env: dict[str, str] = Field(default_factory=dict)  # header -> env var (cred injection)
    description: str | None = None


class McpSection(_Section):
    servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    unknown_server_action: Action = "block"
    on_tool_change: Action = "block"
    max_description_len: int = 1024


class FeedSource(_Section):
    id: str = "aegis-threat-intel"
    url: str = "http://127.0.0.1:8790"
    pubkey_file: str = "config/feeds/feed_pubkey.b64"
    seed_bundle: str | None = "config/feeds/seed_bundle.json"
    poll_s: float = 10.0
    sse: bool = True
    enabled: bool = True
    max_age_s: int = 86400


class FeedOverride(_Section):
    enabled: bool | None = None
    action: Action | None = None
    mode: Mode | None = None
    justification: str | None = None


class FeedsSection(_Section):
    sources: list[FeedSource] = Field(default_factory=lambda: [FeedSource()])
    overrides: dict[str, FeedOverride] = Field(default_factory=dict)  # signature id -> override


# ---------------------------------------------------------------- the document
class PolicyDoc(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    version: int = 1  # schema version (the runtime policy_version is assigned by the store)
    metadata: PolicyMetadata = Field(default_factory=PolicyMetadata)
    profile: Profile = "balanced"
    defaults: Defaults = Field(default_factory=Defaults)
    destinations: DestinationsSection = Field(default_factory=DestinationsSection)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    models: ModelsSection = Field(default_factory=ModelsSection)
    budgets: BudgetsSection = Field(default_factory=BudgetsSection)
    actions: list[ActionRule] = Field(default_factory=list)
    approvals: ApprovalsSection = Field(default_factory=ApprovalsSection)
    mcp: McpSection = Field(default_factory=McpSection)
    feeds: FeedsSection = Field(default_factory=FeedsSection)
    controls: list[ControlConfig] = Field(default_factory=list)
    tests: list[PolicyTest] = Field(default_factory=list)


# ---------------------------------------------------------------- change management
ChangeKind = Literal[
    "budget.raise", "budget.lower", "budget.add", "budget.remove",
    "control.enable", "control.disable", "control.add", "control.remove",
    "control.mode", "control.action.loosen", "control.action.tighten",
    "control.threshold.loosen", "control.threshold.tighten", "control.params",
    "model.allow", "model.disallow", "route.change", "provider.change",
    "approval.rule", "killswitch.on", "killswitch.off",
    "mcp.server", "feed.override", "profile.change", "other",
]


class PolicyChange(BaseModel):
    kind: ChangeKind
    path: str  # dotted path in the policy doc
    before: Any = None
    after: Any = None
    control_id: str | None = None
    scope: str | None = None  # budget scope, e.g. "team:research"
    dimension: str | None = None  # budget dimension, e.g. "usd"
    increase_pct: float | None = None  # budget.raise: (after - before) / before * 100
    loosening: bool = False  # True if the change weakens protection
    summary: str = ""  # human-readable, e.g. "team:research daily usd 10 -> 25 (+150%)"


class PatchOp(BaseModel):
    op: Literal["set", "remove", "append"] = "set"
    path: str  # dotted; list items by index [3] or by key match [id=DLP-01] / [scope=team:x,window=day]
    value: Any = None


class ValidationIssue(BaseModel):
    path: str = ""
    line: int | None = None
    col: int | None = None
    message: str
    severity: Literal["error", "warning"] = "error"


class SelfTestResult(BaseModel):
    name: str
    control: str | None = None
    expect: Action
    got: Action
    got_control: str | None = None
    passed: bool
    latency_ms: float = 0.0


class ValidationReport(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    selftest: list[SelfTestResult] = Field(default_factory=list)
    selftest_passed: bool = True
    changes: list[PolicyChange] = Field(default_factory=list)
    required_role: ApproverLevel | None = None


class ApplyResult(BaseModel):
    status: Literal["applied", "pending_approval", "rejected", "conflict", "noop"]
    version: int | None = None
    previous_version: int | None = None
    approval: ApprovalRequest | None = None
    decision_id: str | None = None
    errors: list[ValidationIssue] = Field(default_factory=list)
    changes: list[PolicyChange] = Field(default_factory=list)
    latency_ms: float = 0.0
    message: str = ""


class PolicyVersionInfo(BaseModel):
    version: int
    sha256: str
    applied_at: datetime
    applied_by: str | None = None
    source: str = "startup"  # startup | file | api | approval | rollback
    reason: str | None = None
    changes_count: int = 0
    summary: str = ""


class PolicySnapshot(BaseModel):
    """Immutable, applied policy version. Pinned on RequestContext.policy at ingress."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    version: int
    sha256: str
    doc: PolicyDoc
    controls: dict[str, ControlConfig] = Field(default_factory=dict)  # effective (profile-merged)
    applied_at: datetime = Field(default_factory=utcnow)
    applied_by: str | None = None
    source: str = "startup"
    compiled: dict[str, Any] = Field(default_factory=dict, exclude=True)  # owner caches, keyed
    #                                                                        "<workstream>:<name>"

    def control(self, control_id: str) -> ControlConfig | None:
        return self.controls.get(control_id)
