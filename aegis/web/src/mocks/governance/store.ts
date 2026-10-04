// In-memory governance mock store (UIG-11). Makes approve/deny/cancel, two-person votes, org
// mutations and (via B19's executors) budget raises / policy applies behave consistently in
// `?mock=1` or when the backend endpoints are not there yet. Owner: B18-dashboard-gov-approvals.
//
// State API for other governance mocks (B19 budgets.ts / policy.ts call these):
//   govStore.subscribe(fn) -> unsubscribe        re-render / refetch on any change
//   govStore.version                              monotonically increasing change counter
//   govStore.policyVersion / bumpPolicyVersion()  shared mock policy version (starts at 12)
//   govStore.createApproval(draft)                -> ApprovalRequest (pending; routed by `route()`)
//   govStore.registerExecutor(fn)                 fn(req) runs when an approval becomes `approved`;
//                                                 return an `execution` record (or null to skip)
//   govStore.route(simulateRequest)               -> ApprovalRoute (first-match over mock rules)
//   govStore.ext                                  free-form slot for B19 state (budgets, yaml…)
// Mock errors are thrown as MockApiError (duck-types like the shell's ApiRequestError).
import type {
  Agent,
  ApprovalRequest,
  ApprovalRoute,
  ApprovalSimulateRequest,
  ApprovalStatus,
  ApproverLevel,
  Member,
  PolicyChange,
} from '@/api/types';
import { canVote, isExpired, roleSatisfies } from '@/components/governance/lib/eligibility';
import { MEMBERS, ORG_ID, RULES, seedAgents, seedApprovals } from './fixtures';

export class MockApiError extends Error {
  readonly status: number;
  readonly envelope: { error: { type: string; message: string; required_role?: ApproverLevel | null; approval_id?: string | null } };
  constructor(status: number, type: string, message: string, extra: { required_role?: ApproverLevel | null; approval_id?: string | null } = {}) {
    super(message);
    this.name = 'MockApiError';
    this.status = status;
    this.envelope = { error: { type, message, ...extra } };
  }
  get type(): string {
    return this.envelope.error.type;
  }
}

export type ApprovalExecutor = (req: ApprovalRequest) => Record<string, unknown> | null | undefined;

export interface ApprovalDraftInput {
  kind: ApprovalRequest['kind'];
  action_type: string;
  title: string;
  summary?: string | null;
  requester_member_id?: string | null;
  requester_agent_id?: string | null;
  amount_usd?: number | null;
  resource?: string | null;
  labels?: Record<string, string>;
  payload?: Record<string, unknown>;
  control_id?: string | null;
  /** budget/config routing hints */
  scope_type?: string | null;
  increase_pct?: number | null;
  changes?: PolicyChange[];
  /** force a route (else computed by `route`) */
  required_role?: ApproverLevel;
  rule_id?: string | null;
  two_person?: boolean;
}

type Listener = () => void;

function nowIso(): string {
  return new Date().toISOString();
}

let counter = 0;
function newId(): string {
  counter += 1;
  const t = Date.now().toString(36).toUpperCase();
  return `apr_MOCK${t}${String(counter).padStart(3, '0')}`;
}

// ------------------------------------------------------------------ routing (mock first-match)
interface MockRoute {
  id: string;
  approver: ApproverLevel;
  two_person?: boolean;
  ttl_s?: number;
  match: (r: RouteInput) => boolean;
}
interface RouteInput {
  kind: string;
  action: string;
  amount: number | null;
  labels: Record<string, string>;
  scope_type: string | null;
  increase_pct: number | null;
  resource: string | null;
}
const glob = (pattern: string, s: string) => new RegExp(`^${pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*')}$`).test(s);
const anyGlob = (patterns: string[], s: string) => patterns.some((p) => glob(p, s));
const TABLE_SENSITIVITY: Record<string, string> = {
  'db:customers': 'CONFIDENTIAL',
  'db:payment_cards': 'RESTRICTED',
  'db:trades': 'CONFIDENTIAL',
  'db:positions': 'CONFIDENTIAL',
  'db:research_notes': 'INTERNAL',
  'db:market_prices': 'PUBLIC',
};
const ACTION_ROUTES: MockRoute[] = [
  { id: 'org-owner-grants', approver: 'owner', ttl_s: 3600, match: (r) => ['org.role.promote_owner', 'org.role.demote_owner', 'org.member.create_owner'].includes(r.action) },
  { id: 'org-privileged', approver: 'owner', ttl_s: 3600, match: (r) => anyGlob(['org.role.*', 'org.member.create_admin', 'org.agent.widen_destination'], r.action) },
  { id: 'org-routine', approver: 'admin', match: (r) => anyGlob(['org.member.*', 'org.agent.*'], r.action) },
  { id: 'spend-owner-2p', approver: 'owner', two_person: true, ttl_s: 7200, match: (r) => anyGlob(['spend.*'], r.action) && (r.amount === null || r.amount > 1000) },
  { id: 'spend-owner', approver: 'owner', match: (r) => anyGlob(['spend.*'], r.action) && (r.amount ?? Infinity) > 200 },
  { id: 'spend-admin', approver: 'admin', match: (r) => anyGlob(['spend.*'], r.action) && (r.amount ?? Infinity) > 20 },
  { id: 'spend-self', approver: 'self', match: (r) => anyGlob(['spend.*'], r.action) },
  { id: 'db-restricted', approver: 'deny', match: (r) => anyGlob(['db.*'], r.action) && ['RESTRICTED', 'SECRET'].includes(r.labels.sensitivity ?? '') },
  { id: 'db-prod-ddl', approver: 'deny', match: (r) => r.action === 'db.schema' && r.labels.env === 'prod' },
  { id: 'db-prod-write', approver: 'owner', match: (r) => r.action === 'db.write' && r.labels.env === 'prod' },
  { id: 'db-staging-write', approver: 'self', match: (r) => r.action === 'db.write' && r.labels.env === 'staging' },
  { id: 'db-write', approver: 'admin', match: (r) => ['db.write', 'db.schema'].includes(r.action) },
  { id: 'db-pii-read', approver: 'admin', ttl_s: 3600, match: (r) => r.action === 'db.read' && r.labels.sensitivity === 'CONFIDENTIAL' },
  { id: 'db-internal-read', approver: 'self', match: (r) => r.action === 'db.read' && r.labels.sensitivity === 'INTERNAL' },
  { id: 'db-read', approver: 'auto', match: (r) => r.action === 'db.read' && ['PUBLIC', 'INTERNAL'].includes(r.labels.sensitivity ?? '') },
  { id: 'send-restricted', approver: 'deny', match: (r) => ['email.external', 'egress.post'].includes(r.action) && ['RESTRICTED', 'SECRET'].includes(r.labels.data_class ?? '') },
  { id: 'send-tainted', approver: 'admin', match: (r) => (anyGlob(['email.*'], r.action) || r.action === 'egress.post') && (r.labels.signals ?? '').split(',').includes('lethal_trifecta') },
  { id: 'send-confidential', approver: 'admin', match: (r) => ['email.external', 'egress.post'].includes(r.action) && r.labels.data_class === 'CONFIDENTIAL' },
  { id: 'send-internal', approver: 'auto', match: (r) => r.action === 'email.internal' },
  { id: 'external-send', approver: 'self', match: (r) => ['email.external', 'egress.post'].includes(r.action) },
  { id: 'code-exec-remote-shell', approver: 'admin', match: (r) => r.action === 'code.exec' && r.labels.pattern === 'remote_shell' },
  { id: 'pkg-install', approver: 'self', match: (r) => r.action === 'package.install' },
  { id: 'deploy-prod', approver: 'owner', match: (r) => r.action === 'code.deploy' && r.labels.env === 'prod' },
  { id: 'deploy-mainline', approver: 'admin', match: (r) => r.action === 'code.deploy' && r.labels.env === 'mainline' },
  { id: 'deploy', approver: 'admin', match: (r) => r.action === 'code.deploy' },
  { id: 'budget-override', approver: 'admin', match: (r) => r.kind === 'budget_raise' },
  { id: 'mcp-repin', approver: 'admin', match: (r) => r.kind === 'mcp_pin' },
];
const CONFIG_ROUTES: MockRoute[] = [
  { id: 'approval-rules', approver: 'owner', match: (r) => r.action === 'approval.rule' },
  { id: 'protect-more', approver: 'auto', match: (r) => anyGlob(['control.enable', 'control.add', 'control.*.tighten', 'model.disallow'], r.action) },
  { id: 'disable-control-critical', approver: 'owner', match: (r) => anyGlob(['control.disable', 'control.remove', 'control.mode', 'control.action.loosen'], r.action) && r.labels.control_severity === 'critical' },
  { id: 'disable-control', approver: 'admin', match: (r) => anyGlob(['control.disable', 'control.remove', 'control.mode', 'control.action.loosen'], r.action) },
  { id: 'raise-org-2x', approver: 'owner', two_person: true, match: (r) => r.action === 'budget.raise' && r.scope_type === 'org' && (r.increase_pct ?? 0) > 100 },
  { id: 'raise-org', approver: 'owner', match: (r) => r.action === 'budget.raise' && r.scope_type === 'org' },
  { id: 'raise-large', approver: 'owner', match: (r) => r.action === 'budget.raise' && r.scope_type === 'team' && (r.increase_pct ?? 0) > 100 },
  { id: 'raise-team-small', approver: 'admin', match: (r) => r.action === 'budget.raise' && r.scope_type === 'team' },
  { id: 'raise-agent-large', approver: 'admin', match: (r) => r.action === 'budget.raise' && ['member', 'agent', 'session'].includes(r.scope_type ?? '') && (r.increase_pct ?? 0) > 50 },
  { id: 'raise-small', approver: 'self', match: (r) => r.action === 'budget.raise' && ['member', 'agent', 'session'].includes(r.scope_type ?? '') },
  { id: 'raise-other', approver: 'owner', match: (r) => ['budget.raise', 'budget.remove'].includes(r.action) },
  { id: 'budget-tighten', approver: 'admin', match: (r) => ['budget.lower', 'budget.add'].includes(r.action) },
  { id: 'killswitch-release-global', approver: 'owner', match: (r) => r.action === 'killswitch.off' && r.labels.scope === 'global' },
  { id: 'loosen-threshold', approver: 'admin', match: (r) => ['control.threshold.loosen', 'killswitch.off'].includes(r.action) },
  { id: 'killswitch-own-agent', approver: 'auto', match: (r) => r.action === 'killswitch.on' && r.labels.requester_is_sponsor === 'true' },
  { id: 'tighten', approver: 'admin', match: (r) => r.action === 'killswitch.on' },
  { id: 'model-allow', approver: 'admin', match: (r) => r.action === 'model.allow' },
  { id: 'policy-neutral', approver: 'self', match: (r) => ['control.params', 'other'].includes(r.action) },
];
const CRITICAL_CONTROLS = new Set(['DLP-02', 'EXE-01', 'SIG-01', 'SIG-02']);
const LEVEL_RANK: Record<ApproverLevel, number> = { auto: 0, self: 1, admin: 2, owner: 3, deny: 4 };

function routeOne(input: RouteInput): ApprovalRoute {
  const table = input.kind === 'config_change' ? CONFIG_ROUTES : ACTION_ROUTES;
  const hit = table.find((r) => r.match(input));
  const fallback: ApproverLevel = input.kind === 'config_change' ? RULES.defaults.default_config_approver : RULES.defaults.default_approver;
  return {
    required_role: hit?.approver ?? fallback,
    two_person: hit?.two_person ?? false,
    rule_id: hit?.id ?? null,
    ttl_s: hit?.ttl_s ?? RULES.defaults.ttl_s,
    max_uses: 1,
  };
}

function roleChangeAction(from: Member['role'], to: Member['role']): string {
  if (to === 'owner') return 'org.role.promote_owner';
  if (from === 'owner') return 'org.role.demote_owner';
  if (to === 'admin') return 'org.role.promote_admin';
  return 'org.role.demote_admin';
}
function roleVerb(action: string): string {
  return action.includes('promote') ? 'Promote' : 'Demote';
}

// ------------------------------------------------------------------ store
class GovMockStore {
  approvals: ApprovalRequest[] = [];
  members: Member[] = [];
  agents: Agent[] = [];
  policyVersion = 12;
  version = 0;
  ext: Record<string, unknown> = {};
  private listeners = new Set<Listener>();
  private executors: ApprovalExecutor[] = [];
  private seeded = false;

  private ensure(): void {
    if (this.seeded) return;
    this.seeded = true;
    const now = Date.now();
    this.approvals = seedApprovals(now);
    this.members = MEMBERS.map((m) => ({ ...m, meta: { ...m.meta } }));
    this.agents = seedAgents(now);
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  emit(): void {
    this.version += 1;
    // async so callers can finish their own state updates first
    queueMicrotask(() => this.listeners.forEach((l) => l()));
  }

  // ---------------------------------------------------------------- reads
  getMembers(): Member[] {
    this.ensure();
    return this.members;
  }
  getAgents(): Agent[] {
    this.ensure();
    return this.agents;
  }
  member(id: string | null | undefined): Member | undefined {
    return this.getMembers().find((m) => m.id === id);
  }
  agent(id: string | null | undefined): Agent | undefined {
    return this.getAgents().find((a) => a.id === id);
  }

  /** All approvals with expiry swept (expired ⇒ status expired). */
  getApprovals(): ApprovalRequest[] {
    this.ensure();
    const now = Date.now();
    let changed = false;
    this.approvals = this.approvals.map((a) => {
      if (a.status === 'pending' && isExpired(a, now)) {
        changed = true;
        return { ...a, status: 'expired' as ApprovalStatus, decided_at: a.expires_at };
      }
      return a;
    });
    if (changed) this.emit();
    return this.approvals;
  }

  getApproval(id: string): ApprovalRequest | undefined {
    return this.getApprovals().find((a) => a.id === id);
  }

  viewerOf(viewerId: string | null | undefined): { member_id: string | null; role: Member['role'] } {
    const m = this.member(viewerId) ?? this.getMembers().find((x) => x.role === 'owner');
    return { member_id: m?.id ?? null, role: m?.role ?? 'owner' };
  }

  /** Decorate with can_vote/why_not for a viewer (what the server does per request). */
  forViewer(req: ApprovalRequest, viewerId: string | null | undefined): ApprovalRequest {
    const v = this.viewerOf(viewerId);
    const sponsor = req.requester.agent_id ? this.agent(req.requester.agent_id)?.owner_member_id : null;
    const check = canVote(v, req, Date.now(), { sponsorId: sponsor ?? null });
    return { ...req, can_vote: check.ok, why_not: check.ok ? null : check.reason };
  }

  // ---------------------------------------------------------------- approvals mutations
  vote(id: string, viewerId: string | null | undefined, decision: 'approve' | 'deny', comment: string | null): ApprovalRequest {
    const req = this.getApproval(id);
    if (!req) throw new MockApiError(404, 'not_found', `Approval ${id} not found`);
    const v = this.viewerOf(viewerId);
    const sponsor = req.requester.agent_id ? this.agent(req.requester.agent_id)?.owner_member_id : null;
    const check = canVote(v, req, Date.now(), { sponsorId: sponsor ?? null });
    if (!check.ok) throw new MockApiError(403, 'forbidden', check.reason ?? 'Not allowed', { required_role: req.required_role, approval_id: req.id });
    if (decision === 'deny' && (!comment || comment.trim().length < 3)) {
      throw new MockApiError(400, 'invalid_request', 'A reason (≥ 3 characters) is required to deny.');
    }
    const ts = nowIso();
    const votes = [...req.votes, { member_id: v.member_id as string, role: v.role, decision, comment: comment?.trim() || null, ts }];
    let next: ApprovalRequest = { ...req, votes };
    if (decision === 'deny') {
      next = { ...next, status: 'denied', decided_at: ts, decided_by: [...req.decided_by, v.member_id as string] };
    } else {
      const approvals = votes.filter((x) => x.decision === 'approve');
      const needed = req.two_person ? 2 : 1;
      const levelOk = approvals.some((x) => roleSatisfies(x.role, req.required_role));
      if (approvals.length >= needed && levelOk) {
        next = { ...next, status: 'approved', decided_at: ts, decided_by: approvals.map((x) => x.member_id) };
        next = { ...next, execution: this.execute(next) };
      }
    }
    this.replace(next);
    return this.forViewer(next, viewerId);
  }

  cancel(id: string, viewerId: string | null | undefined): ApprovalRequest {
    const req = this.getApproval(id);
    if (!req) throw new MockApiError(404, 'not_found', `Approval ${id} not found`);
    if (req.status !== 'pending') throw new MockApiError(409, 'conflict', `Approval is already ${req.status}`);
    const v = this.viewerOf(viewerId);
    const own = req.requester.member_id === v.member_id;
    if (!own && !roleSatisfies(v.role, 'admin')) {
      throw new MockApiError(403, 'forbidden', 'Only the requester (or their sponsor) or an admin can cancel a request.');
    }
    const next: ApprovalRequest = { ...req, status: 'cancelled', decided_at: nowIso(), decided_by: [v.member_id as string] };
    this.replace(next);
    return this.forViewer(next, viewerId);
  }

  route(req: ApprovalSimulateRequest & { labels?: Record<string, string>; scope_type?: string | null; increase_pct?: number | null; changes?: PolicyChange[] }): ApprovalRoute {
    const labels: Record<string, string> = { ...(req.labels ?? {}) };
    if (req.resource && TABLE_SENSITIVITY[req.resource] && !labels.sensitivity) labels.sensitivity = TABLE_SENSITIVITY[req.resource];
    if (req.resource?.startsWith('db:') && !labels.env) labels.env = 'prod';
    const one = (action: string, extra: Partial<RouteInput> = {}) =>
      routeOne({ kind: req.kind, action, amount: req.amount_usd ?? null, labels, scope_type: req.scope_type ?? null, increase_pct: req.increase_pct ?? null, resource: req.resource ?? null, ...extra });
    if (req.kind === 'config_change' && req.changes && req.changes.length > 0) {
      // multi-change proposals take the highest level (two_person OR-ed, shortest TTL)
      const routes = req.changes.map((c) => {
        const scopeType = c.scope ? c.scope.split(':')[0] : (req.scope_type ?? null);
        const l = { ...labels };
        if (c.control_id && CRITICAL_CONTROLS.has(c.control_id)) l.control_severity = 'critical';
        return one(c.kind, { scope_type: scopeType, increase_pct: c.increase_pct ?? req.increase_pct ?? null, labels: l });
      });
      return routes.reduce((a, b) => ({
        required_role: LEVEL_RANK[b.required_role] > LEVEL_RANK[a.required_role] ? b.required_role : a.required_role,
        rule_id: LEVEL_RANK[b.required_role] > LEVEL_RANK[a.required_role] ? b.rule_id : a.rule_id,
        two_person: a.two_person || b.two_person,
        ttl_s: Math.min(a.ttl_s, b.ttl_s),
        max_uses: 1,
      }));
    }
    return one(req.action_type);
  }

  createApproval(draft: ApprovalDraftInput): ApprovalRequest {
    this.ensure();
    const agent = draft.requester_agent_id ? this.agent(draft.requester_agent_id) : undefined;
    const human = this.member(draft.requester_member_id ?? agent?.owner_member_id ?? null);
    const route =
      draft.required_role !== undefined
        ? { required_role: draft.required_role, rule_id: draft.rule_id ?? null, two_person: draft.two_person ?? false, ttl_s: RULES.defaults.ttl_s, max_uses: 1 }
        : this.route({
            kind: draft.kind,
            action_type: draft.action_type,
            amount_usd: draft.amount_usd ?? null,
            resource: draft.resource ?? null,
            requester_member_id: human?.id ?? null,
            requester_agent_id: agent?.id ?? null,
            labels: draft.labels,
            scope_type: draft.scope_type,
            increase_pct: draft.increase_pct,
            changes: draft.changes,
          });
    const now = Date.now();
    const id = newId();
    const req: ApprovalRequest = {
      id,
      org_id: ORG_ID,
      team_id: agent?.team_id ?? human?.team_id ?? null,
      kind: draft.kind,
      action_type: draft.action_type,
      title: draft.title,
      summary: draft.summary ?? null,
      requester: agent
        ? { org_id: ORG_ID, team_id: agent.team_id, member_id: agent.owner_member_id, agent_id: agent.id, role: 'agent', display_name: agent.id, authenticated: true }
        : { org_id: ORG_ID, team_id: human?.team_id ?? null, member_id: human?.id ?? null, agent_id: null, role: human?.role ?? 'member', display_name: human?.name ?? null, authenticated: true },
      amount_usd: draft.amount_usd ?? null,
      resource: draft.resource ?? null,
      labels: draft.labels ?? {},
      payload: { ...(draft.payload ?? {}), ...(draft.changes ? { changes: draft.changes } : {}) },
      fingerprint: `fp_${id.slice(4)}`,
      required_role: route.required_role,
      two_person: route.two_person,
      rule_id: route.rule_id,
      votes: [],
      status: route.required_role === 'auto' ? 'approved' : route.required_role === 'deny' ? 'denied' : 'pending',
      created_at: new Date(now).toISOString(),
      expires_at: new Date(now + route.ttl_s * 1000).toISOString(),
      decided_at: route.required_role === 'auto' || route.required_role === 'deny' ? new Date(now).toISOString() : null,
      decided_by: [],
      request_id: null,
      decision_id: null,
      control_id: draft.control_id ?? null,
      uses: 0,
      max_uses: route.max_uses,
      execution: null,
    };
    const final = req.status === 'approved' ? { ...req, execution: this.execute(req) } : req;
    this.approvals = [final, ...this.getApprovals()];
    this.emit();
    return final;
  }

  registerExecutor(fn: ApprovalExecutor): () => void {
    this.executors.push(fn);
    return () => {
      this.executors = this.executors.filter((f) => f !== fn);
    };
  }

  bumpPolicyVersion(): number {
    this.policyVersion += 1;
    this.emit();
    return this.policyVersion;
  }

  private execute(req: ApprovalRequest): Record<string, unknown> | null {
    if (req.action_type.startsWith('org.')) return this.executeOrgChange(req);
    for (const fn of this.executors) {
      try {
        const r = fn(req);
        if (r) return r;
      } catch (err) {
        console.warn('[gov-mock] executor failed', err);
      }
    }
    if (req.kind === 'config_change' || req.kind === 'budget_raise') {
      const prev = this.policyVersion;
      const v = this.bumpPolicyVersion();
      return { status: 'applied', policy_version: v, previous_version: prev, latency_ms: 140 + Math.round(Math.random() * 60) };
    }
    if (req.kind === 'mcp_pin') return { status: 'repinned' };
    return { granted: true, max_uses: req.max_uses, grant_expires_at: new Date(Date.now() + 900_000).toISOString() };
  }

  private replace(next: ApprovalRequest): void {
    this.approvals = this.getApprovals().map((a) => (a.id === next.id ? next : a));
    this.emit();
  }

  // ---------------------------------------------------------------- org mutations
  patchMember(id: string, patch: { role?: Member['role']; team_id?: string | null; active?: boolean }, viewerId: string | null | undefined): Member {
    const target = this.member(id);
    if (!target) throw new MockApiError(404, 'not_found', `Member ${id} not found`);
    const v = this.viewerOf(viewerId);
    if (!roleSatisfies(v.role, 'admin')) throw new MockApiError(403, 'forbidden', 'Managing members requires an admin.', { required_role: 'admin' });
    const roleChange = patch.role !== undefined && patch.role !== target.role;
    const touchesOwner = roleChange && (patch.role === 'owner' || target.role === 'owner');
    if (touchesOwner && v.role !== 'owner') throw new MockApiError(403, 'forbidden', 'Only owners can grant or remove the owner role.', { required_role: 'owner' });
    if (roleChange && target.id === v.member_id) {
      throw new MockApiError(403, 'forbidden', 'You cannot change your own role (separation of duties).');
    }
    if (roleChange && target.role === 'owner' && this.members.filter((m) => m.role === 'owner').length <= 1) {
      throw new MockApiError(409, 'conflict', 'The organization needs at least one owner.');
    }
    if (roleChange && patch.role) {
      // Governed change (CONTRACTS A-37): route org.role.* like the server; below the level → approval.
      const action = roleChangeAction(target.role, patch.role);
      const route = routeOne({ kind: 'action', action, amount: null, labels: {}, scope_type: null, increase_pct: null, resource: `member:${id}` });
      if (!roleSatisfies(v.role, route.required_role) || route.two_person) {
        const pending = this.getApprovals().find(
          (a) => a.status === 'pending' && a.resource === `member:${id}` && (a.payload as { patch?: { role?: string } }).patch?.role === patch.role,
        );
        const apr =
          pending ??
          this.createApproval({
            kind: 'action',
            action_type: action,
            title: `${roleVerb(action)} ${target.name} to ${patch.role}`,
            summary: `Role change requested by ${this.member(v.member_id)?.name ?? v.member_id}`,
            requester_member_id: v.member_id,
            resource: `member:${id}`,
            labels: { category: 'org', op: action.replace(/^org\./, ''), to_role: patch.role },
            payload: {
              org_change_id: `och_${Date.now().toString(36)}`,
              op: 'member.update',
              target: { type: 'member', id, name: target.name },
              patch: { role: patch.role },
              before: { role: target.role },
            },
          });
        throw new MockApiError(403, 'approval_required', `${roleVerb(action)} ${target.name} to ${patch.role} needs ${route.required_role} approval (rule ${route.rule_id ?? 'default'}).`, {
          required_role: route.required_role,
          approval_id: apr.id,
        });
      }
    }
    const next: Member = { ...target, ...patch };
    this.members = this.members.map((m) => (m.id === id ? next : m));
    this.emit();
    return next;
  }

  private executeOrgChange(req: ApprovalRequest): Record<string, unknown> | null {
    const p = req.payload as { target?: { type?: string; id?: string }; patch?: Partial<Member> };
    if (p.target?.type !== 'member' || !p.target.id || !p.patch) return null;
    const id = p.target.id;
    const patch = p.patch;
    this.members = this.members.map((m) => (m.id === id ? { ...m, ...patch } : m));
    return { status: 'applied', org_change_id: (req.payload as { org_change_id?: string }).org_change_id ?? null };
  }

  patchAgent(id: string, patch: { active?: boolean }, viewerId: string | null | undefined): Agent {
    const target = this.agent(id);
    if (!target) throw new MockApiError(404, 'not_found', `Agent ${id} not found`);
    const v = this.viewerOf(viewerId);
    if (!roleSatisfies(v.role, 'admin')) throw new MockApiError(403, 'forbidden', 'Changing agents requires an admin.', { required_role: 'admin' });
    const next: Agent = { ...target, ...patch, status: patch.active === false ? 'killed' : patch.active === true ? 'active' : target.status };
    this.agents = this.agents.map((a) => (a.id === id ? next : a));
    this.emit();
    return next;
  }

  /** Reset to the seed (demo helper; also exposed as window.__aegisGovMock in dev). */
  reset(): void {
    this.seeded = false;
    this.ensure();
    this.policyVersion = 12;
    this.ext = {};
    this.emit();
  }
}

export const govStore = new GovMockStore();

if (import.meta.env?.DEV && typeof window !== 'undefined') {
  (window as unknown as { __aegisGovMock?: GovMockStore }).__aegisGovMock = govStore;
}
