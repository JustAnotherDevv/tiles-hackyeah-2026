// Burn-down chart for the selected scope (UIG-15): used vs limit over the last 24 h from
// GET /api/budgets/history, plus a client-side linear forecast to the end of the day (labelled).
// Owner: B19-dashboard-gov-policy.
import { useMemo } from 'react';
import { useApi } from '@/api/hooks';
import type { BudgetDimension, BudgetHistoryResponse } from '@/api/types';
import { AreaTimeseries } from '@/components/charts';
import { fmtDimension } from '@/components/governance/lib/format-gov';
import { policyMocks, policyPaths, useMockStoreRefresh } from '@/components/governance/policy/policy-api';

interface Row {
  ts: string;
  used: number | null;
  forecast: number | null;
  limit: number;
}

export function BudgetHistoryChart({ scope, dimension, height = 180 }: { scope: string; dimension: BudgetDimension; height?: number }) {
  const res = useApi<BudgetHistoryResponse>(policyPaths.budgetHistory(scope, dimension), {
    mock: policyMocks.budgetHistory(scope, dimension),
    refreshOn: ['budget.updated', 'policy.applied'],
    refreshMs: 15000,
  });
  useMockStoreRefresh(res.refresh, res.isMock);

  const { rows, limit, exceedsAt } = useMemo(() => {
    const pts = res.data?.points ?? [];
    const out: Row[] = pts.map((p) => ({ ts: p.ts, used: p.used, forecast: null, limit: p.limit }));
    const last = pts[pts.length - 1];
    let exceeds: string | null = null;
    if (pts.length >= 4 && last) {
      // slope over the last ~third of the window
      const k = Math.max(0, pts.length - Math.ceil(pts.length / 3));
      const a = pts[k];
      const dt = new Date(last.ts).getTime() - new Date(a.ts).getTime();
      const slope = dt > 0 ? (last.used - a.used) / dt : 0; // per ms
      const end = new Date(last.ts);
      end.setUTCHours(24, 0, 0, 0);
      const span = end.getTime() - new Date(last.ts).getTime();
      if (span > 0 && slope > 0) {
        out[out.length - 1] = { ...out[out.length - 1], forecast: last.used };
        const steps = 6;
        for (let i = 1; i <= steps; i++) {
          const t = new Date(last.ts).getTime() + (span * i) / steps;
          const v = last.used + slope * (t - new Date(last.ts).getTime());
          out.push({ ts: new Date(t).toISOString(), used: null, forecast: Math.round(v * 10000) / 10000, limit: last.limit });
        }
        if (last.limit > 0 && last.used < last.limit) {
          const tHit = new Date(last.ts).getTime() + (last.limit - last.used) / slope;
          if (tHit <= end.getTime()) exceeds = new Date(tHit).toISOString();
        }
      }
    }
    return { rows: out, limit: last?.limit ?? 0, exceedsAt: exceeds };
  }, [res.data]);

  return (
    <div>
      <AreaTimeseries<Row>
        data={rows}
        height={height}
        series={[
          { key: 'used', label: 'Used', color: '#4A7FE0' },
          { key: 'forecast', label: 'Forecast (linear)', color: '#7A808C', dashed: true },
        ]}
        referenceLines={limit > 0 ? [{ y: limit, label: `limit ${fmtDimension(dimension, limit)}`, color: '#E5446D', dashed: true }] : []}
        yFormat={(v) => fmtDimension(dimension, v)}
        legend
        emptyText="No usage history for this scope yet"
      />
      <div className="mt-1 text-2xs text-text-3">
        {exceedsAt ? (
          <span className="text-redact">
            Forecast reaches the limit at {new Date(exceedsAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.
          </span>
        ) : (
          'Forecast: linear projection of recent usage to end of day (UTC), computed client-side.'
        )}
      </div>
    </div>
  );
}
