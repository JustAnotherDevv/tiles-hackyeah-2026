// Aegis dashboard API types. FROZEN: materialized verbatim from docs/CONTRACTS.md section 5.5.
// Mirrors the backend JSON exactly (snake_case, ISO-8601 UTC strings for datetimes).
// Do not edit; request changes in your report. Page-local view types belong next to the page.

export type ISODate = string;
export type Action = 'allow' | 'log' | 'redact' | 'require_approval' | 'block';
export type Kind = 'model_call' | 'tool_call' | 'mcp' | 'egress' | 'a2a' | 'config_change';
export type Direction = 'in' | 'out';
export type DestClass = 'local' | 'remote' | 'third_party';
export type Role = 'owner' | 'admin' | 'member' | 'agent';
export type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical';
export type DataClass = 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED' | 'SECRET';
export type Mode = 'enforce' | 'monitor' | 'off';
export type Surface =
  | 'prompt.user' | 'model.request' | 'model.response' | 'model.admin'
  | 'tool.input' | 'tool.output' | 'artifact.file'
  | 'mcp.init' | 'mcp.list' | 'mcp.call' | 'mcp.result'
  | 'egress.request' | 'egress.response'
  | 'a2a.message' | 'a2a.result'
  | 'config.change';
export type Source =
  | 'proxy' | 'mcp' | 'hook' | 'guard' | 'egress' | 'playground' | 'dashboard' | 'selftest' | 'test';
export type ApproverLevel = 'auto' | 'self' | 'admin' | 'owner' | 'deny';
export type ApprovalKind = 'action' | 'config_change' | 'budget_raise' | 'mcp_pin';
export type ApprovalStatus = 'pending' | 'approved' | 'denied' | 'expired' | 'cancelled';
export type BudgetDimension = 'usd' | 'tokens' | 'compute_s' | 'requests' | 'tool_calls' | 'spend_usd';
export type BudgetWindow = 'hour' | 'day' | 'week' | 'month' | 'session' | 'total';
export type BudgetState = 'ok' | 'soft' | 'hard' | 'killed';

export const ACTION_ORDER: Action[] = ['allow', 'log', 'redact', 'require_approval', 'block'];
export const ROLE_RANK: Record<Role, number> = { agent: 0, member: 1, admin: 2, owner: 3 };

// ------------------------------------------------------------------ core
export interface Identity {
  org_id: string;
  team_id: string | null;
  member_id: string | null;
  agent_id: string | null;
  role: Role;
  display_name?: string | null;
  authenticated?: boolean;
}

export interface Destination {
  name: string;
  dest_class: DestClass;
  provider?: string | null;
  host?: string | null;
  url?: string | null;
}

export interface TextSegment {
  path: string;
  text: string;
  role: string;
  trusted: boolean;
  redactable: boolean;
}

export interface Finding {
  control_id: string;
  detector: string;
  category: string;
  entity?: string | null;
  data_class?: DataClass | null;
  severity: Severity;
  score: number;
  segment_index?: number | null;
  start?: number | null;
  end?: number | null;
  excerpt?: string | null;
  replacement?: string | null;
  meta?: Record<string, unknown>;
}

export interface Mutation {
  target: 'body' | 'header' | 'route';
  op: 'set' | 'remove';
  path: string;
  value?: unknown;
  reason?: string | null;
}

export interface Decision {
  action: Action;
  control_id: string;
  reason: string;
  score: number | null;
  threshold: number | null;
  approval_id: string | null;
  mode: 'enforce' | 'monitor';
  severity: Severity;
  findings: Finding[];
  mutations: Mutation[];
  http_status?: number | null;
  error_type?: string | null;
  degraded: boolean;
  latency_ms: number;
  owasp: string[];
  meta?: Record<string, unknown>;
}

export interface Redaction {
  segment_index: number;
  path: string;
  start: number;
  end: number;
  entity: string;
  data_class: DataClass | null;
  placeholder: string;
  control_id: string;
  reversible: boolean;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  compute_s: number;
  requests: number;
  tool_calls: number;
  cost_usd: number;
  spend_usd: number;
  estimated: boolean;
}

export interface ControlHit {
  control_id: string;
  action: Action;
  mode: 'enforce' | 'monitor';
  score: number | null;
  latency_ms: number;
  degraded: boolean;
}

/** SSE `decision` payload and GET /api/decisions item. */
export interface DecisionSummary {
  id: string;
  ts: ISODate;
  request_id: string;
  action: Action;
  kind: Kind;
  surface: Surface;
  direction: Direction;
  destination: Destination;
  model: string | null;
  tool_name: string | null;
  action_type: string | null;
  amount_usd: number | null;
  identity: Identity;
  session_id: string;
  source: Source;
  control_id: string | null;
  reason: string;
  score: number | null;
  threshold: number | null;
  controls: ControlHit[];
  redaction_count: number;
  entities: string[];
  approval_id: string | null;
  latency_ms: number;
  upstream_ms: number | null;
  policy_version: number;
  feed_serial: number | null;
  degraded: boolean;
  cost_usd: number | null;
  tokens: number | null;
  preview: string;
  dry_run: boolean;
}

export interface WireView {
  decision_id: string;
  original: TextSegment[];
  outbound: TextSegment[];
  response_raw: string | null;
  response_local: string | null;
  upstream_request_preview: Record<string, unknown> | null;
}

/** GET /api/decisions/{id} */
export interface DecisionDetail extends DecisionSummary {
  decisions: Decision[];
  redactions: Redaction[];
  mutations: Mutation[];
  usage: Usage | null;
  wire: WireView | null;
  audit_seq: number | null;
  audit_hash: string | null;
}

export interface Verdict {
  id: string;
  request_id: string;
  interaction_id: string;
  action: Action;
  primary: Decision | null;
  decisions: Decision[];
  segments: TextSegment[];
  redactions: Redaction[];
  mutations: Mutation[];
  approval: ApprovalRequest | null;
  policy_version: number;
  feed_serial: number | null;
  latency_ms: number;
  degraded: boolean;
  dry_run: boolean;
  ts: ISODate;
}

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}

/** Standard error envelope for every non-model endpoint. */
export interface ApiError {
  error: {
    type: string;
    message: string;
    control_id?: string | null;
    decision_id?: string | null;
    approval_id?: string | null;
    required_role?: ApproverLevel | null;
    expires_at?: ISODate | null;
    scope?: string | null;
    retry_after_s?: number | null;
  };
}

// ------------------------------------------------------------------ stats & perf
export interface StatsKpis {
  requests: number;
  allowed: number;
  logged: number;
  redacted: number;
  blocked: number;
  approvals_pending: number;
  approvals_decided: number;
  spend_usd: number;
  spend_today_usd: number;
  org_budget_used_pct: number;
  tokens: number;
  local_compute_s: number;
  cost_avoided_usd: number;
  active_agents: number;
  p50_overhead_ms: number;
  p95_overhead_ms: number;
  degraded: boolean;
}

export interface StatsBucket {
  ts: ISODate;
  allow: number;
  log: number;
  redact: number;
  require_approval: number;
  block: number;
  spend_usd: number;
  tokens: number;
}

/** GET /api/stats?window=1h|24h|7d */
export interface StatsResponse {
  window: '1h' | '24h' | '7d';
  generated_at: ISODate;
  kpis: StatsKpis;
  timeseries: StatsBucket[];
  by_control: { control_id: string; family: string; hits: number; blocks: number; redacts: number }[];
  by_category: { category: string; count: number }[];
  by_destination: { dest_class: DestClass; count: number; redactions: number }[];
  by_entity: { entity: string; count: number }[];
  top_agents: { agent_id: string; requests: number; blocks: number; spend_usd: number }[];
}

/** SSE `stats` payload, every ~2 s. */
export interface StatsTick {
  ts: ISODate;
  rps: number;
  decisions_1m: Record<Action, number>;
  spend_today_usd: number;
  approvals_pending: number;
  p50_overhead_ms: number;
  p95_overhead_ms: number;
}

/** GET /api/perf */
export interface PerfResponse {
  generated_at: ISODate;
  overhead_ms: { p50: number; p95: number; p99: number; count: number };
  by_control: { control_id: string; kind: string; p50_ms: number; p95_ms: number; count: number }[];
  upstream_ms: { provider: string; model: string | null; p50: number; p95: number; count: number }[];
  rps_1m: number;
  semantic: {
    mode: string;
    degraded: boolean;
    models: { name: string; backend: string; loaded: boolean; p50_ms: number | null }[];
  };
  bench: Record<string, unknown> | null;
}

// ------------------------------------------------------------------ budgets
export interface BudgetStatus {
  scope: string;
  scope_type: 'org' | 'team' | 'member' | 'agent' | 'session' | 'model' | 'tool';
  dimension: BudgetDimension;
  window: BudgetWindow;
  limit: number;
  used: number;
  reserved: number;
  pct: number;
  state: BudgetState;
  resets_at: ISODate | null;
  label: string | null;
}

export interface BudgetScopeView {
  scope: string;
  scope_type: BudgetStatus['scope_type'];
  name: string;
  parent: string | null;
  state: BudgetState;
  limits: BudgetStatus[];
}

export interface KillSwitch {
  global: boolean;
  teams: string[];
  members: string[];
  agents: string[];
  sessions: string[];
}

/** GET /api/budgets */
export interface BudgetsResponse {
  generated_at: ISODate;
  currency: 'USD';
  pricing_version: string;
  scopes: BudgetScopeView[];
  kill_switch: KillSwitch;
}

/** GET /api/budgets/history?scope=&dimension=&window=24h */
export interface BudgetHistoryResponse {
  scope: string;
  dimension: BudgetDimension;
  points: { ts: ISODate; used: number; limit: number }[];
}

/** POST /api/budgets/raise, POST /api/killswitch, POST /api/policy/apply|rollback */
export interface ApplyResult {
  status: 'applied' | 'pending_approval' | 'rejected' | 'conflict' | 'noop';
  version: number | null;
  previous_version: number | null;
  approval: ApprovalRequest | null;
  decision_id: string | null;
  errors: ValidationIssue[];
  changes: PolicyChange[];
  latency_ms: number;
  message: string;
}

// ------------------------------------------------------------------ org
export interface Org { id: string; name: string }
export interface Team {
  id: string;
  org_id: string;
  name: string;
  description?: string | null;
  color?: string | null;
  meta?: Record<string, unknown>;
}

export interface Member {
  id: string;
  org_id: string;
  team_id: string | null;
  name: string;
  email: string | null;
  role: 'owner' | 'admin' | 'member';
  title: string | null;
  avatar_url: string | null;
  active: boolean;
  created_at: ISODate;
  meta: Record<string, unknown>;
  agents?: string[];
}

export interface Agent {
  id: string;
  org_id: string;
  team_id: string | null;
  owner_member_id: string | null;
  name: string;
  kind: 'claude-code' | 'scripted' | 'sdk' | 'mcp-client' | 'other';
  description: string | null;
  profile: string | null;
  allowed_models: string[];
  allowed_tools: string[];
  denied_tools: string[];
  max_destination: DestClass | null;
  active: boolean;
  created_at: ISODate;
  last_seen: ISODate | null;
  meta: Record<string, unknown>;
  status?: 'active' | 'killed' | 'idle';
  spend_today_usd?: number;
}

/** GET /api/org */
export interface OrgResponse {
  org: Org;
  teams: (Team & { member_count: number; agent_count: number })[];
  counts: { members: number; agents: number; teams: number };
}

export interface Permissions {
  can_apply_policy: 'yes' | 'approval' | 'no';
  can_manage_members: boolean;
  can_killswitch: boolean;
  can_export_audit: boolean;
  approver_levels: ApproverLevel[]; // levels this viewer satisfies
}

/** GET /api/whoami */
export interface WhoAmI {
  identity: Identity;
  member: Member | null;
  permissions: Permissions;
}

// ------------------------------------------------------------------ approvals
export interface ApprovalVote {
  member_id: string;
  role: Role;
  decision: 'approve' | 'deny';
  comment: string | null;
  ts: ISODate;
}

export interface ApprovalRequest {
  id: string;
  org_id: string;
  team_id: string | null;
  kind: ApprovalKind;
  action_type: string;
  title: string;
  summary: string | null;
  requester: Identity;
  amount_usd: number | null;
  resource: string | null;
  labels: Record<string, string>;
  payload: Record<string, unknown>;
  fingerprint: string;
  required_role: ApproverLevel;
  two_person: boolean;
  rule_id: string | null;
  votes: ApprovalVote[];
  status: ApprovalStatus;
  created_at: ISODate;
  expires_at: ISODate | null;
  decided_at: ISODate | null;
  decided_by: string[];
  request_id: string | null;
  decision_id: string | null;
  control_id: string | null;
  uses: number;
  max_uses: number;
  execution: Record<string, unknown> | null;
  can_vote?: boolean; // present when fetched by a viewer
  why_not?: string | null;
}

/** GET /api/approvals */
export interface ApprovalsResponse {
  items: ApprovalRequest[];
  counts: Record<ApprovalStatus, number>;
}

export interface ApprovalRuleView {
  id: string;
  set: 'rules' | 'config_rules';
  description: string | null;
  when: string; // human readable condition
  approver: ApproverLevel;
  two_person: boolean;
  ttl_s: number | null;
}

/** GET /api/approvals/rules */
export interface ApprovalRulesResponse {
  rules: ApprovalRuleView[];
  config_rules: ApprovalRuleView[];
  defaults: { ttl_s: number; default_approver: ApproverLevel; default_config_approver: ApproverLevel };
}

/** POST /api/approvals/simulate */
export interface ApprovalSimulateRequest {
  kind: ApprovalKind;
  action_type: string;
  amount_usd?: number | null;
  resource?: string | null;
  requester_member_id?: string | null;
  requester_agent_id?: string | null;
}
export interface ApprovalRoute {
  required_role: ApproverLevel;
  two_person: boolean;
  rule_id: string | null;
  ttl_s: number;
  max_uses: number;
}

// ------------------------------------------------------------------ policy
export interface ValidationIssue {
  path: string;
  line: number | null;
  col: number | null;
  message: string;
  severity: 'error' | 'warning';
}

export interface PolicyChange {
  kind: string; // ChangeKind, e.g. "budget.raise", "control.disable"
  path: string;
  before: unknown;
  after: unknown;
  control_id: string | null;
  scope: string | null;
  dimension: string | null;
  increase_pct: number | null;
  loosening: boolean;
  summary: string;
}

export interface SelfTestResult {
  name: string;
  control: string | null;
  expect: Action;
  got: Action;
  got_control: string | null;
  passed: boolean;
  latency_ms: number;
}

/** POST /api/policy/validate */
export interface ValidationReport {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  selftest: SelfTestResult[];
  selftest_passed: boolean;
  changes: PolicyChange[];
  required_role: ApproverLevel | null;
}

/** GET /api/policy */
export interface PolicyResponse {
  version: number;
  yaml: string;
  sha256: string;
  applied_at: ISODate;
  applied_by: string | null;
  source: string;
  profile: string;
  controls_count: number;
}

/** POST /api/policy/diff */
export interface PolicyDiffResponse {
  changes: PolicyChange[];
  unified: string;
  required_role: ApproverLevel | null;
}

export interface PolicyVersionInfo {
  version: number;
  sha256: string;
  applied_at: ISODate;
  applied_by: string | null;
  source: string;
  reason: string | null;
  changes_count: number;
  summary: string;
}

/** GET /api/controls item */
export interface ControlView {
  id: string;
  family: string;
  name: string;
  kind: 'deterministic' | 'semantic' | 'hybrid' | 'stateful';
  owner: string;
  enabled: boolean;
  mode: Mode;
  action: Action;
  threshold: number | null;
  severity: Severity;
  owasp: string[];
  surfaces: Surface[];
  implemented: boolean;
  hits_24h: number;
  blocks_24h: number;
  p95_ms: number | null;
}

/** GET /api/coverage */
export interface CoverageResponse {
  frameworks: {
    id: string; // "OWASP-LLM-2026" | "OWASP-ASI-2026" | "OWASP-MCP-2025"
    name: string;
    items: {
      id: string;
      name: string;
      status: 'covered' | 'partial' | 'uncovered' | 'disabled';
      controls: string[];
    }[];
  }[];
}

// ------------------------------------------------------------------ feed
/** GET /api/feed/status */
export interface FeedStatus {
  feed_id: string;
  url: string | null;
  status: 'ok' | 'stale' | 'rejected' | 'unreachable' | 'disabled' | 'seed';
  serial: number | null;
  version: string | null;
  published: ISODate | null;
  expires: ISODate | null;
  key_id: string | null;
  signatures_total: number;
  signatures_active: number;
  signatures_monitor: number;
  signatures_quarantined: number;
  last_check: ISODate | null;
  last_update: ISODate | null;
  last_error: string | null;
  history: { serial: number; version: string; applied_at: ISODate; added: number; removed: number; modified: number }[];
}

/** GET /api/feed/signatures item */
export interface FeedSignatureView {
  id: string;
  title: string;
  severity: Severity;
  status: 'experimental' | 'test' | 'stable' | 'deprecated' | 'withdrawn' | 'quarantined';
  aliases: string[];
  tags: string[];
  surfaces: Surface[];
  action: Action;
  hits_24h: number;
}

// ------------------------------------------------------------------ audit
export interface AuditEvent {
  schema: 'aegis.audit/1';
  event_id: string;
  seq: number;
  ts: ISODate;
  event_type: string;
  actor: Identity | null;
  request_id: string | null;
  decision_id: string | null;
  action: Action | null;
  control_id: string | null;
  reason: string | null;
  policy_version: number | null;
  feed_serial: number | null;
  data: Record<string, unknown>;
  prev_hash: string;
  hash: string;
  [k: string]: unknown;
}

/** GET /api/audit/verify */
export interface AuditVerifyResult {
  ok: boolean;
  records: number;
  head_hash: string;
  broken_at_seq: number | null;
  files: number;
  checked_at: ISODate;
  message: string;
}

// ------------------------------------------------------------------ playground
/** POST /api/playground */
export interface PlaygroundRequest {
  text: string;
  kind?: Kind;
  surface?: Surface;
  destination?: DestClass | string; // dest class or provider name ("ollama", "anthropic", "mock")
  model?: string | null;
  agent_id?: string | null;
  tool_name?: string | null;
  tool_args?: Record<string, unknown> | null;
  send?: boolean; // actually call the model when allowed
}

export interface PlaygroundResponse {
  decision_id: string;
  verdict: Verdict;
  original: string;
  outbound: string;
  redactions: Redaction[];
  response: { raw: string; local: string; model: string; provider: string } | null;
  timings: { total_ms: number; controls: { control_id: string; ms: number }[] };
}

// ------------------------------------------------------------------ MCP
export interface McpToolView {
  name: string;
  description_preview: string;
  hash: string;
  status: 'approved' | 'pending' | 'quarantined' | 'changed';
  reasons: string[];
  first_seen: ISODate;
  last_seen: ISODate;
}

/** GET /api/mcp/servers item */
export interface McpServerView {
  name: string;
  transport: 'http' | 'stdio';
  url: string | null;
  destination: DestClass;
  status: 'registered' | 'unknown' | 'blocked' | 'unreachable';
  tools: McpToolView[];
}

// ------------------------------------------------------------------ health
/** GET /healthz */
export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  uptime_s: number;
  policy_version: number;
  feed_serial: number | null;
  components: Record<string, 'ok' | 'degraded' | 'down' | 'off' | 'stale'>;
}

// ------------------------------------------------------------------ SSE
export interface SseEventMap {
  decision: DecisionSummary;
  'approval.created': ApprovalRequest;
  'approval.updated': ApprovalRequest;
  'budget.updated': { statuses: BudgetStatus[] };
  'budget.threshold': { scope: string; dimension: BudgetDimension; window: BudgetWindow; pct: number; state: BudgetState };
  'policy.applied': { version: number; previous_version: number | null; source: string; actor: Identity | null; changes: PolicyChange[]; latency_ms: number };
  'policy.rejected': { source: string; errors: ValidationIssue[]; kept_version: number };
  'feed.updated': FeedStatus & { added: number; removed: number; modified: number };
  'feed.rejected': { reason: string; serial_attempted: number | null; kept_serial: number | null };
  killswitch: { scope: string; active: boolean; actor: Identity | null };
  'mcp.tool': { server: string; tool: string; status: McpToolView['status']; reason: string };
  'org.updated': { member?: Member; agent?: Agent };
  stats: StatsTick;
  system: { level: 'info' | 'warning' | 'error'; message: string; component?: string };
  heartbeat: { ts: ISODate };
}
export type SseEventName = keyof SseEventMap;
