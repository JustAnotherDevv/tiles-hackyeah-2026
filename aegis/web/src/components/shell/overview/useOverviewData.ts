// Overview data (docs/plan/15 §2.2 "KPI live overlay"): base numbers from /api/stats (refresh 15 s and on
// policy.applied), decisions newer than stats.generated_at added client-side per action so tiles tick
// instantly, the latest timeseries bucket grows live, `stats` ticks update spend / approvals / overhead.
// Posture inputs come from real endpoints (mock fallback + badge). Owner: dashboard-shell (B16).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useApi, useDecisionBatches, usePendingApprovalsDetail, useStatsTick } from '@/api/hooks';
import type {
  Action,
  AuditVerifyResult,
  BudgetHistoryResponse,
  BudgetStatus,
  BudgetsResponse,
  ControlView,
  DecisionSummary,
  FeedStatus,
  HealthResponse,
  PerfResponse,
  StatsBucket,
  StatsResponse,
} from '@/api/types';
import { computePosture, postureFromServer, type Posture, type PostureResponse } from '@/lib/posture';
import { readString, STORAGE_KEYS, writeString } from '@/lib/storage';
import { mockBudgetHistory, mockBudgets } from '@/mocks/shell/budgets';
import { mockHealth } from '@/mocks/shell/health';
import { mockPerf } from '@/mocks/shell/perf';
import { mockAuditVerify, mockControls, mockFeedStatus } from '@/mocks/shell/posture';
import { mockStats } from '@/mocks/shell/stats';

export type OverviewWindow = StatsResponse['window'];
const WINDOWS: OverviewWindow[] = ['1h', '24h', '7d'];
const ORG_SCOPE = 'org:acme-capital';

type Overlay = Record<Action, number> & { spend: number; entities: number };
const ZERO: Overlay = { allow: 0, log: 0, redact: 0, require_approval: 0, block: 0, spend: 0, entities: 0 };

export function useOverviewWindow(): [OverviewWindow, (w: OverviewWindow) => void] {
  const [win, setWin] = useState<OverviewWindow>(() => {
    const v = readString(STORAGE_KEYS.overviewWindow) as OverviewWindow | null;
    return v && WINDOWS.includes(v) ? v : '24h';
  });
  const set = useCallback((w: OverviewWindow) => {
    setWin(w);
    writeString(STORAGE_KEYS.overviewWindow, w);
  }, []);
  return [win, set];
}

export function orgDayLimit(b: BudgetsResponse | undefined): BudgetStatus | null {
  const org = b?.scopes.find((s) => s.scope_type === 'org') ?? null;
  if (!org) return null;
  return org.limits.find((l) => l.dimension === 'usd' && l.window === 'day') ?? org.limits.find((l) => l.dimension === 'usd') ?? null;
}

export function useOverviewData(win: OverviewWindow) {
  const stats = useApi<StatsResponse>(`/api/stats?window=${win}`, { mock: () => mockStats(win), refreshMs: 15_000, refreshOn: ['policy.applied'] });
  const budgets = useApi<BudgetsResponse>('/api/budgets', { mock: mockBudgets, refreshMs: 20_000, refreshOn: ['budget.updated', 'budget.threshold', 'killswitch'] });
  const orgScope = budgets.data?.scopes.find((s) => s.scope_type === 'org')?.scope ?? ORG_SCOPE;
  const history = useApi<BudgetHistoryResponse>(`/api/budgets/history?scope=${encodeURIComponent(orgScope)}&dimension=usd&window=24h`, {
    mock: () => mockBudgetHistory(orgScope, orgDayLimit(budgets.data)?.limit ?? 150, orgDayLimit(budgets.data)?.used ?? 62.4),
    refreshMs: 30_000,
    refreshOn: ['budget.updated'],
  });
  const controls = useApi<{ items: ControlView[] }>('/api/controls', { mock: mockControls, refreshOn: ['policy.applied'] });
  // A-51: server posture is authoritative; no mock factory → on 404 data stays undefined and the
  // client-side mirror of the formula (lib/posture) is used with a "demo" badge.
  const serverPosture = useApi<PostureResponse>('/api/stats/posture', { refreshMs: 30_000, refreshOn: ['policy.applied', 'feed.updated', 'feed.rejected'] });
  const feed = useApi<FeedStatus>('/api/feed/status', { mock: mockFeedStatus, refreshMs: 60_000, refreshOn: ['feed.updated', 'feed.rejected'] });
  const audit = useApi<AuditVerifyResult>('/api/audit/verify', { mock: mockAuditVerify, refreshMs: 60_000 });
  const health = useApi<HealthResponse>('/healthz', { mock: mockHealth, refreshMs: 15_000 });
  const perf = useApi<PerfResponse>('/api/perf', { mock: mockPerf, refreshMs: 30_000 });
  const tick = useStatsTick();
  const approvals = usePendingApprovalsDetail();

  // ---- live overlay: decisions newer than stats.generated_at
  const [overlay, setOverlay] = useState<Overlay>(ZERO);
  const since = stats.data ? Date.parse(stats.data.generated_at) : Number.POSITIVE_INFINITY;
  const sinceRef = useRef(since);
  sinceRef.current = since;
  useEffect(() => setOverlay(ZERO), [stats.data]);
  const [lastBatch, setLastBatch] = useState<{ n: number; blocked: number; redacted: number }>({ n: 0, blocked: 0, redacted: 0 });
  useDecisionBatches(
    useCallback((batch: DecisionSummary[]) => {
      const fresh = batch.filter((d) => Date.parse(d.ts) > sinceRef.current);
      if (!fresh.length) return;
      setOverlay((o) => {
        const n = { ...o };
        for (const d of fresh) {
          n[d.action] += 1;
          n.spend += d.cost_usd ?? 0;
          n.entities += d.redaction_count ?? 0;
        }
        return n;
      });
      setLastBatch((l) => ({
        n: l.n + 1,
        blocked: fresh.filter((d) => d.action === 'block').length,
        redacted: fresh.filter((d) => d.action === 'redact').length,
      }));
    }, []),
  );

  const view = useMemo(() => {
    const s = stats.data;
    if (!s) return null;
    const add = overlay.allow + overlay.log + overlay.redact + overlay.require_approval + overlay.block;
    const timeseries: StatsBucket[] = s.timeseries.length
      ? s.timeseries.map((b, i) =>
          i === s.timeseries.length - 1
            ? {
                ...b,
                allow: b.allow + overlay.allow,
                log: b.log + overlay.log,
                redact: b.redact + overlay.redact,
                require_approval: b.require_approval + overlay.require_approval,
                block: b.block + overlay.block,
              }
            : b,
        )
      : [];
    const kpis = {
      ...s.kpis,
      requests: s.kpis.requests + add,
      allowed: s.kpis.allowed + overlay.allow,
      logged: s.kpis.logged + overlay.log,
      redacted: s.kpis.redacted + overlay.redact,
      blocked: s.kpis.blocked + overlay.block,
      spend_today_usd: tick ? Math.max(tick.spend_today_usd, s.kpis.spend_today_usd) : s.kpis.spend_today_usd + overlay.spend,
      p50_overhead_ms: tick?.p50_overhead_ms ?? s.kpis.p50_overhead_ms,
      p95_overhead_ms: tick?.p95_overhead_ms ?? s.kpis.p95_overhead_ms,
    };
    const entitiesTotal = s.by_entity.reduce((a, e) => a + e.count, 0) + overlay.entities;
    return { ...s, kpis, timeseries, entitiesTotal };
  }, [stats.data, overlay, tick]);

  const posture: Posture = useMemo(
    () =>
      serverPosture.data && !serverPosture.isMock && typeof serverPosture.data.score === 'number'
        ? postureFromServer(serverPosture.data)
        : computePosture({
        controls: controls.data?.items ?? null,
        feed: feed.data ?? null,
        audit: audit.data ?? null,
        health: health.data ?? null,
        statsDegraded: stats.data?.kpis.degraded ?? null,
        semanticDegraded: perf.data?.semantic.degraded ?? null,
      }),
    [serverPosture.data, serverPosture.isMock, controls.data, feed.data, audit.data, health.data, stats.data, perf.data],
  );
  const postureMock = posture.source === 'client' && (controls.isMock || feed.isMock || audit.isMock || health.isMock);

  return { stats, view, budgets, history, tick, approvals, posture, postureMock, perf, health, lastBatch };
}

export type OverviewData = ReturnType<typeof useOverviewData>;
