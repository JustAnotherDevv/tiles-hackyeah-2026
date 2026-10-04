// Seeded StatsResponse / StatsTick mocks with diurnal curves (prototype view-overview.js).
// Owner: dashboard-shell (B16).
import type { Action, StatsBucket, StatsResponse, StatsTick } from '@/api/types';
import { diurnal, liveRand, mulberry32 } from './rng';

type Win = StatsResponse['window'];

const ACTIONS: Action[] = ['allow', 'log', 'redact', 'require_approval', 'block'];

const WINDOW_CFG: Record<Win, { buckets: number; stepMs: number; total: number }> = {
  '1h': { buckets: 60, stepMs: 60_000, total: 1840 },
  '24h': { buckets: 96, stepMs: 15 * 60_000, total: 48_216 },
  '7d': { buckets: 56, stepMs: 3 * 3600_000, total: 301_400 },
};

export function mockStats(window: Win = '24h'): StatsResponse {
  const cfg = WINDOW_CFG[window];
  const r = mulberry32(424242 + cfg.buckets);
  const now = Date.now();
  const end = Math.floor(now / cfg.stepMs) * cfg.stepMs;
  const raw: number[] = [];
  for (let i = cfg.buckets - 1; i >= 0; i--) {
    const t = new Date(end - i * cfg.stepMs);
    const h = t.getHours() + t.getMinutes() / 60;
    raw.push(diurnal(h) * (0.88 + r() * 0.24));
  }
  const sum = raw.reduce((a, b) => a + b, 0);
  const timeseries: StatsBucket[] = raw.map((c, idx) => {
    const req = Math.max(1, Math.round((cfg.total * c) / sum));
    const redact = Math.round(req * 0.081 * (0.8 + r() * 0.4));
    const block = Math.round(req * 0.0266 * (0.7 + r() * 0.5) * (idx >= cfg.buckets - 6 ? 1.7 : 1));
    const approval = Math.max(0, Math.round(req * 0.0012 * (0.4 + r() * 1.4)));
    const log = Math.round(req * 0.05 * (0.7 + r() * 0.6));
    const allow = Math.max(0, req - redact - block - approval - log);
    return {
      ts: new Date(end - (cfg.buckets - 1 - idx) * cfg.stepMs).toISOString(),
      allow,
      log,
      redact,
      require_approval: approval,
      block,
      spend_usd: +(req * 0.0026 * (0.8 + r() * 0.4)).toFixed(2),
      tokens: req * 1400,
    };
  });
  const tot = (k: Action) => timeseries.reduce((a, b) => a + b[k], 0);
  const requests = ACTIONS.reduce((a, k) => a + tot(k), 0);
  const spend = timeseries.reduce((a, b) => a + b.spend_usd, 0);
  const spendToday = window === '1h' ? 38.6 : window === '24h' ? 62.4 : 61.2;
  return {
    window,
    generated_at: new Date(now).toISOString(),
    kpis: {
      requests,
      allowed: tot('allow'),
      logged: tot('log'),
      redacted: tot('redact'),
      blocked: tot('block'),
      approvals_pending: 2,
      approvals_decided: 17,
      spend_usd: +spend.toFixed(2),
      spend_today_usd: spendToday,
      org_budget_used_pct: (spendToday / 150) * 100,
      tokens: requests * 1400,
      local_compute_s: 5120,
      cost_avoided_usd: window === '7d' ? 1840.2 : window === '24h' ? 312.4 : 18.75,
      active_agents: 4,
      p50_overhead_ms: 0.42,
      p95_overhead_ms: 1.18,
      degraded: false,
    },
    timeseries,
    by_control: [
      { control_id: 'DLP-01', family: 'DLP', hits: Math.round(tot('redact') * 0.71), blocks: 0, redacts: Math.round(tot('redact') * 0.71) },
      { control_id: 'DLP-02', family: 'DLP', hits: Math.round(tot('block') * 0.24), blocks: Math.round(tot('block') * 0.24), redacts: 0 },
      { control_id: 'INJ-02', family: 'INJ', hits: Math.round(tot('block') * 0.21), blocks: Math.round(tot('block') * 0.21), redacts: 0 },
      { control_id: 'DLP-03', family: 'DLP', hits: Math.round(tot('redact') * 0.19), blocks: 0, redacts: Math.round(tot('redact') * 0.19) },
      { control_id: 'EXE-01', family: 'EXE', hits: Math.round(tot('block') * 0.14), blocks: Math.round(tot('block') * 0.14), redacts: 0 },
      { control_id: 'EXE-04', family: 'EXE', hits: Math.round(tot('block') * 0.12), blocks: Math.round(tot('block') * 0.12), redacts: 0 },
      { control_id: 'SIG-01', family: 'SIG', hits: Math.round(tot('block') * 0.09), blocks: Math.round(tot('block') * 0.09), redacts: 0 },
      { control_id: 'ACT-01', family: 'ACT', hits: Math.round(tot('require_approval') * 0.6), blocks: 0, redacts: 0 },
    ],
    by_category: [
      { category: 'pii', count: Math.round(tot('redact') * 0.7) },
      { category: 'secret', count: Math.round(tot('block') * 0.25) },
      { category: 'injection', count: Math.round(tot('block') * 0.22) },
      { category: 'metadata', count: Math.round(tot('redact') * 0.2) },
      { category: 'command', count: Math.round(tot('block') * 0.14) },
      { category: 'loop', count: Math.round(tot('block') * 0.12) },
    ],
    by_destination: [
      { dest_class: 'local', count: Math.round(requests * 0.46), redactions: Math.round(tot('redact') * 0.08) },
      { dest_class: 'remote', count: Math.round(requests * 0.41), redactions: Math.round(tot('redact') * 0.78) },
      { dest_class: 'third_party', count: Math.round(requests * 0.13), redactions: Math.round(tot('redact') * 0.14) },
    ],
    by_entity: [
      { entity: 'PERSON', count: Math.round(tot('redact') * 0.9) },
      { entity: 'EMAIL', count: Math.round(tot('redact') * 0.62) },
      { entity: 'PESEL', count: Math.round(tot('redact') * 0.41) },
      { entity: 'IBAN', count: Math.round(tot('redact') * 0.33) },
      { entity: 'PAN', count: Math.round(tot('redact') * 0.18) },
      { entity: 'PHONE', count: Math.round(tot('redact') * 0.16) },
      { entity: 'AWS_KEY', count: Math.round(tot('block') * 0.08) },
    ],
    top_agents: [
      { agent_id: 'claude-code@platform', requests: Math.round(requests * 0.38), blocks: Math.round(tot('block') * 0.42), spend_usd: +(spendToday * 0.44).toFixed(2) },
      { agent_id: 'trading-copilot@trading', requests: Math.round(requests * 0.27), blocks: Math.round(tot('block') * 0.18), spend_usd: +(spendToday * 0.36).toFixed(2) },
      { agent_id: 'research-agent@research', requests: Math.round(requests * 0.29), blocks: Math.round(tot('block') * 0.16), spend_usd: +(spendToday * 0.05).toFixed(2) },
      { agent_id: 'chaos-agent@platform', requests: Math.round(requests * 0.06), blocks: Math.round(tot('block') * 0.24), spend_usd: +(spendToday * 0.03).toFixed(2) },
    ],
  };
}


let spendTick = 62.4;
export function mockStatsTick(): StatsTick {
  spendTick += liveRand() * 0.04;
  return {
    ts: new Date().toISOString(),
    rps: +(0.6 + liveRand() * 1.4).toFixed(2),
    decisions_1m: {
      allow: 28 + Math.round(liveRand() * 10),
      log: 2 + Math.round(liveRand() * 3),
      redact: 3 + Math.round(liveRand() * 3),
      require_approval: Math.round(liveRand() * 1.2),
      block: 1 + Math.round(liveRand() * 2),
    },
    spend_today_usd: +spendTick.toFixed(2),
    approvals_pending: 2,
    p50_overhead_ms: +(0.38 + liveRand() * 0.08).toFixed(2),
    p95_overhead_ms: +(1.05 + liveRand() * 0.25).toFixed(2),
  };
}
