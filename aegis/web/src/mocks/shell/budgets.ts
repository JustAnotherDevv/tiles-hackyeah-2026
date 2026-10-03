// BudgetsResponse / BudgetHistoryResponse mocks (amounts from docs/seed-fixes/policy.yaml budgets.limits).
// Owner: dashboard-shell (B16).
import type { BudgetHistoryResponse, BudgetScopeView, BudgetState, BudgetStatus, BudgetsResponse } from '@/api/types';
import { diurnal, mulberry32 } from './rng';

function endOfDay(): string {
  const d = new Date();
  d.setHours(24, 0, 0, 0);
  return d.toISOString();
}

function stateFor(pct: number): BudgetState {
  return pct >= 100 ? 'hard' : pct >= 80 ? 'soft' : 'ok';
}

function status(scope: string, scope_type: BudgetStatus['scope_type'], limit: number, used: number, window: BudgetStatus['window'] = 'day', label: string | null = null): BudgetStatus {
  const pct = limit > 0 ? (used / limit) * 100 : 0;
  return { scope, scope_type, dimension: 'usd', window, limit, used, reserved: 0, pct, state: stateFor(pct), resets_at: window === 'day' ? endOfDay() : null, label };
}

function view(scope: string, scope_type: BudgetStatus['scope_type'], name: string, parent: string | null, limits: BudgetStatus[]): BudgetScopeView {
  const worst = limits.reduce<BudgetState>((acc, l) => (l.state === 'hard' || acc === 'hard' ? 'hard' : l.state === 'soft' || acc === 'soft' ? 'soft' : 'ok'), 'ok');
  return { scope, scope_type, name, parent, state: worst, limits };
}

export function mockBudgets(): BudgetsResponse {
  return {
    generated_at: new Date().toISOString(),
    currency: 'USD',
    pricing_version: '2026-10-01',
    scopes: [
      view('org:acme-capital', 'org', 'Acme Capital', null, [status('org:acme-capital', 'org', 150, 62.4), status('org:acme-capital', 'org', 3000, 1184.2, 'month')]),
      view('team:trading', 'team', 'Trading', 'org:acme-capital', [status('team:trading', 'team', 60, 51.3)]),
      view('team:research', 'team', 'Research', 'org:acme-capital', [status('team:research', 'team', 15, 3.9)]),
      view('team:platform', 'team', 'Platform', 'org:acme-capital', [status('team:platform', 'team', 50, 7.2)]),
      view('agent:claude-code@platform', 'agent', 'claude-code@platform', 'team:platform', [status('agent:claude-code@platform', 'agent', 30, 6.42)]),
      view('agent:trading-copilot@trading', 'agent', 'trading-copilot@trading', 'team:trading', [status('agent:trading-copilot@trading', 'agent', 20, 16.9)]),
      view('agent:research-agent@research', 'agent', 'research-agent@research', 'team:research', [status('agent:research-agent@research', 'agent', 2, 0.38)]),
      view('agent:chaos-agent@platform', 'agent', 'chaos-agent@platform', 'team:platform', [status('agent:chaos-agent@platform', 'agent', 0.5, 0.47)]),
    ],
    kill_switch: { global: false, teams: [], members: [], agents: [], sessions: [] },
  };
}

/** Cumulative spend today in 15-minute points (only up to now). */
export function mockBudgetHistory(scope = 'org:acme-capital', limit = 150, usedNow = 62.4): BudgetHistoryResponse {
  const r = mulberry32(777);
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const step = 15 * 60_000;
  const now = Date.now();
  const n = Math.max(2, Math.floor((now - start.getTime()) / step) + 1);
  const weights: number[] = [];
  for (let i = 0; i < n; i++) weights.push(diurnal((i * 15) / 60) * (0.7 + r() * 0.6));
  const total = weights.reduce((a, b) => a + b, 0);
  let acc = 0;
  const points = weights.map((w, i) => {
    acc += (w / total) * usedNow;
    return { ts: new Date(start.getTime() + i * step).toISOString(), used: +acc.toFixed(2), limit };
  });
  return { scope, dimension: 'usd', points };
}
