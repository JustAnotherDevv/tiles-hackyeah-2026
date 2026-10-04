// Mock budgets (GET /api/budgets, /api/budgets/history, POST /api/budgets/raise, POST /api/killswitch)
// for ?mock=1 / missing endpoints. Limits and the kill switch come from the mock policy YAML, so an
// approved raise (approvals page, shared mock store) rescales the bar exactly like the real flow.
// Usage drifts with wall-clock time so bars move live; chaos-agent@platform runs away to 100 %.
// Owner: B19-dashboard-gov-policy.
import type {
  ApplyResult,
  BudgetDimension,
  BudgetHistoryResponse,
  BudgetScopeView,
  BudgetState,
  BudgetStatus,
  BudgetWindow,
  BudgetsResponse,
  PolicyChange,
} from '@/api/types';
import { getKillSwitch, parseBudgetLimits } from '@/components/governance/lib/yaml-text';
import { TEAMS } from './fixtures';
import { mockPolicyState, mockProposePatch } from './policy';
import { govStore } from './store';

const T0 = Date.now();
const DIMS: BudgetDimension[] = ['usd', 'tokens', 'compute_s', 'requests', 'tool_calls', 'spend_usd'];

/** Baseline usage (at page load) and growth per minute, per scope/window/dimension. */
const USAGE: Record<string, { base: number; perMin: number }> = {
  'org:acme-capital|day|usd': { base: 0, perMin: 0 }, // computed from teams
  'org:acme-capital|day|compute_s': { base: 0, perMin: 0 },
  'org:acme-capital|month|usd': { base: 1840.2, perMin: 0.35 },
  'org:acme-capital|month|spend_usd': { base: 1250, perMin: 0 },
  'team:trading|day|usd': { base: 49.3, perMin: 0.06 },
  'team:trading|day|tokens': { base: 2_910_000, perMin: 3_400 },
  'team:trading|month|usd': { base: 702.4, perMin: 0.06 },
  'team:trading|month|spend_usd': { base: 1170, perMin: 0 },
  'team:research|day|usd': { base: 4.1, perMin: 0.004 },
  'team:research|day|compute_s': { base: 3120, perMin: 6 },
  'team:platform|day|usd': { base: 27.5, perMin: 0.03 },
  'agent:claude-code@platform|day|usd': { base: 18.9, perMin: 0.025 },
  'agent:trading-copilot@trading|day|usd': { base: 13.4, perMin: 0.02 },
  'agent:research-agent@research|day|compute_s': { base: 2950, perMin: 5 },
  'agent:chaos-agent@platform|day|usd': { base: 0.47, perMin: 0.01 },
  'agent:chaos-agent@platform|day|tokens': { base: 88_000, perMin: 2_000 },
  'member:u_piotr|day|usd': { base: 2.1, perMin: 0.002 },
  'member:u_olivia|day|usd': { base: 0.9, perMin: 0.001 },
  'member:u_agnieszka|day|usd': { base: 0.3, perMin: 0 },
  'member:u_tomasz|day|usd': { base: 3.6, perMin: 0.003 },
  'session:ses_cc_7f3a91|session|usd': { base: 1.9, perMin: 0.01 },
  'session:ses_cc_7f3a91|session|tokens': { base: 610_000, perMin: 1_500 },
  'session:ses_chaos_01|session|usd': { base: 0.47, perMin: 0.01 },
  'session:ses_chaos_01|session|tokens': { base: 88_000, perMin: 2_000 },
};

const MEMBER_SCOPES: [string, string][] = [
  ['u_piotr', 'trading'],
  ['u_olivia', 'trading'],
  ['u_agnieszka', 'research'],
  ['u_tomasz', 'platform'],
];
const AGENTS: [string, string, string][] = [
  ['trading-copilot@trading', 'trading', 'Trading Copilot (remote)'],
  ['research-agent@research', 'research', 'Research Agent (local)'],
  ['claude-code@platform', 'platform', 'Claude Code (Platform)'],
  ['chaos-agent@platform', 'platform', 'Chaos Agent (red team)'],
];
const SESSIONS: [string, string][] = [
  ['ses_cc_7f3a91', 'agent:claude-code@platform'],
  ['ses_chaos_01', 'agent:chaos-agent@platform'],
];

function minutes(): number {
  return (Date.now() - T0) / 60_000;
}

function usageOf(scope: string, window: string, dim: string): number {
  const u = USAGE[`${scope}|${window}|${dim}`];
  if (!u) return 0;
  return u.base + u.perMin * minutes();
}

function resetsAt(window: BudgetWindow): string | null {
  const d = new Date();
  if (window === 'day') return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1)).toISOString();
  if (window === 'month') return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)).toISOString();
  return null;
}

function stateFor(pct: number, killed: boolean): BudgetState {
  if (killed) return 'killed';
  if (pct >= 100) return 'hard';
  if (pct >= 80) return 'soft';
  return 'ok';
}

const RANK: Record<BudgetState, number> = { ok: 0, soft: 1, hard: 2, killed: 3 };

export function mockBudgets(): BudgetsResponse {
  const yaml = mockPolicyState().yaml;
  const limits = parseBudgetLimits(yaml);
  const ks = getKillSwitch(yaml);
  const killedAgents = new Set(govStore.getAgents().filter((a) => a.status === 'killed').map((a) => a.id));
  const isKilled = (scope: string): boolean => {
    if (ks.global) return true;
    const [type, id] = [scope.slice(0, scope.indexOf(':')), scope.slice(scope.indexOf(':') + 1)];
    if (type === 'team') return ks.teams.includes(id);
    if (type === 'member') return ks.members.includes(id);
    if (type === 'agent') return ks.agents.includes(id) || killedAgents.has(id);
    if (type === 'session') return ks.sessions.includes(id);
    return false;
  };

  // org day usage = sum of team day usage (consistent tree)
  const teamDay = (dim: string) => TEAMS.reduce((s, t) => s + usageOf(`team:${t.id}`, 'day', dim), 0);

  const scopes: BudgetScopeView[] = [];
  const add = (scope: string, scope_type: BudgetScopeView['scope_type'], name: string, parent: string | null) => {
    // a killed parent (global / team) stops everything below it
    const killed = isKilled(scope) || (parent !== null && scopes.find((s) => s.scope === parent)?.state === 'killed');
    const type = scope_type;
    const entries = limits.filter((l) => l.scope === scope || (l.scope === `${type}:*` && !limits.some((x) => x.scope === scope && x.window === l.window)));
    const statuses: BudgetStatus[] = [];
    for (const e of entries) {
      for (const dim of DIMS) {
        const limit = e.values[dim];
        if (limit === undefined) continue;
        let used = usageOf(scope, e.window, dim);
        if (scope === 'org:acme-capital' && e.window === 'day') used = dim === 'usd' ? teamDay('usd') : dim === 'compute_s' ? teamDay('compute_s') + 1420 : used;
        if (scope === 'agent:chaos-agent@platform' || scope === 'session:ses_chaos_01') used = Math.min(used, limit * 1.04);
        const reserved = dim === 'usd' && used > 0 ? Math.min(limit * 0.04, used * 0.05) : 0;
        const pct = limit > 0 ? (used / limit) * 100 : 0;
        statuses.push({
          scope,
          scope_type: type,
          dimension: dim,
          window: e.window as BudgetWindow,
          limit,
          used: Math.round(used * 10000) / 10000,
          reserved: Math.round(reserved * 10000) / 10000,
          pct: Math.round(pct * 10) / 10,
          state: stateFor(pct, killed),
          resets_at: resetsAt(e.window as BudgetWindow),
          label: e.scope.endsWith(':*') ? `inherited from ${e.scope}` : null,
        });
      }
    }
    const state = statuses.reduce<BudgetState>((s, x) => (RANK[x.state] > RANK[s] ? x.state : s), killed ? 'killed' : 'ok');
    scopes.push({ scope, scope_type: type, name, parent, state, limits: statuses });
  };

  add('org:acme-capital', 'org', 'Acme Capital', null);
  for (const t of TEAMS) add(`team:${t.id}`, 'team', t.name, 'org:acme-capital');
  const members = govStore.getMembers();
  for (const [id, team] of MEMBER_SCOPES) add(`member:${id}`, 'member', members.find((m) => m.id === id)?.name ?? id, `team:${team}`);
  for (const [id, team, name] of AGENTS) add(`agent:${id}`, 'agent', name, `team:${team}`);
  for (const [id, parent] of SESSIONS) add(`session:${id}`, 'session', id, parent);

  return {
    generated_at: new Date().toISOString(),
    currency: 'USD',
    pricing_version: '2026-10-03.1',
    scopes,
    kill_switch: { global: ks.global, teams: ks.teams, members: ks.members, agents: [...new Set([...ks.agents, ...killedAgents])], sessions: ks.sessions },
  };
}

export function mockBudgetHistory(scope: string, dimension: BudgetDimension, window = '24h'): BudgetHistoryResponse {
  const now = Date.now();
  const cur = mockBudgets().scopes.find((s) => s.scope === scope)?.limits.find((l) => l.dimension === dimension && (l.window === 'day' || l.window === 'session'));
  const used = cur?.used ?? 0;
  const limit = cur?.limit ?? 0;
  const dayStart = new Date(now);
  dayStart.setUTCHours(0, 0, 0, 0);
  const start = window === '24h' ? Math.max(dayStart.getTime(), now - 24 * 3600_000) : now - 24 * 3600_000;
  const n = 36;
  const points: BudgetHistoryResponse['points'] = [];
  // deterministic S-curve with office-hours bumps up to the current value
  let seed = scope.length * 7919 + dimension.length * 104729;
  const rnd = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  const weights: number[] = [];
  for (let i = 0; i <= n; i++) {
    const hour = new Date(start + ((now - start) * i) / n).getUTCHours();
    weights.push((hour >= 7 && hour <= 18 ? 1.6 : 0.4) * (0.6 + rnd() * 0.8));
  }
  const total = weights.reduce((a, b) => a + b, 0) || 1;
  let acc = 0;
  for (let i = 0; i <= n; i++) {
    acc += weights[i];
    points.push({ ts: new Date(start + ((now - start) * i) / n).toISOString(), used: Math.round(((used * acc) / total) * 10000) / 10000, limit });
  }
  return { scope, dimension, points };
}

function scopeType(scope: string): string {
  return scope.includes(':') ? scope.slice(0, scope.indexOf(':')) : scope;
}

export function mockRaise(
  body: { scope: string; window: string; dimension: string; new_limit: number; reason: string },
  viewer: { id: string | null; role: 'owner' | 'admin' | 'member' },
): ApplyResult {
  const st = mockBudgets().scopes.find((s) => s.scope === body.scope)?.limits.find((l) => l.window === body.window && l.dimension === body.dimension);
  const before = st?.limit ?? 0;
  const pct = before > 0 ? ((body.new_limit - before) / before) * 100 : 100;
  const raise = body.new_limit > before;
  const winWord = body.window === 'day' ? 'daily' : body.window === 'month' ? 'monthly' : body.window;
  const summary = `${body.scope} ${winWord} ${body.dimension} ${before} → ${body.new_limit} (${pct >= 0 ? '+' : ''}${Math.round(pct)}%)`;
  const path = `budgets.limits[scope=${body.scope},window=${body.window}].${body.dimension}`;
  const change: PolicyChange = {
    kind: raise ? 'budget.raise' : 'budget.lower',
    path,
    before,
    after: body.new_limit,
    control_id: null,
    scope: body.scope,
    dimension: body.dimension,
    increase_pct: Math.round(pct * 10) / 10,
    loosening: raise,
    summary,
  };
  return mockProposePatch({
    patch: [{ op: 'set', path, value: body.new_limit }],
    changes: [change],
    title: `${raise ? 'Raise' : 'Lower'} ${body.scope} ${winWord} ${body.dimension.toUpperCase()} budget ${before} → ${body.new_limit} (${pct >= 0 ? '+' : ''}${Math.round(pct)}%)`,
    reason: body.reason || null,
    viewer,
    resource: `budget:${body.scope}`,
    labels: { scope: body.scope, scope_type: scopeType(body.scope) },
  });
}

export function mockKillSwitch(body: { scope: string; active: boolean; reason: string }, viewer: { id: string | null; role: 'owner' | 'admin' | 'member' }): ApplyResult {
  const type = scopeType(body.scope);
  const id = body.scope.slice(body.scope.indexOf(':') + 1);
  const listKey = ({ team: 'teams', member: 'members', agent: 'agents', session: 'sessions' } as Record<string, string>)[type];
  const patch =
    body.scope === 'global'
      ? [{ op: 'set', path: 'budgets.kill_switch.global', value: body.active }]
      : [{ op: body.active ? 'append' : 'remove', path: `budgets.kill_switch.${listKey}`, value: id }];
  const change: PolicyChange = {
    kind: body.active ? 'killswitch.on' : 'killswitch.off',
    path: body.scope === 'global' ? 'budgets.kill_switch.global' : `budgets.kill_switch.${listKey}`,
    before: !body.active,
    after: body.active,
    control_id: 'EXE-04',
    scope: body.scope,
    dimension: null,
    increase_pct: null,
    loosening: !body.active,
    summary: `kill switch ${body.active ? 'ON' : 'off'} · ${body.scope}`,
  };
  return mockProposePatch({
    patch,
    changes: [change],
    title: `Kill switch ${body.active ? 'ON' : 'off'} for ${body.scope}`,
    reason: body.reason || null,
    viewer,
    resource: body.scope,
    labels: { scope: body.scope },
  });
}
