// Row D (5) — cumulative spend today vs the org daily budget: used line + wash, 80 % soft (downgrade) and
// 100 % hard (block) reference lines, dashed linear forecast to midnight. Single USD axis.
import { useMemo } from 'react';
import { AreaTimeseries } from '@/components/charts/AreaTimeseries';
import { fmtUsd } from '@/lib/format';
import { Panel } from '../Panel';
import { orgDayLimit, type OverviewData } from './useOverviewData';

export function SpendBurnCard({ d, className }: { d: OverviewData; className?: string }) {
  const lim = orgDayLimit(d.budgets.data);
  const limit = lim?.limit ?? d.history.data?.points.at(-1)?.limit ?? 150;
  // One number for the headline, the line end and the KPI row ("Spend today"): the max of the ledger
  // (incl. seeded demo history), the live KPI and the last history bucket (INT-B request 4 / LIVE).
  const liveUsed = Math.max(d.history.data?.points.at(-1)?.used ?? 0, d.view?.kpis.spend_today_usd ?? 0, lim?.used ?? 0);
  const data = useMemo(() => {
    const pts = d.history.data?.points ?? [];
    if (!pts.length) return [];
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const step = 60 * 60_000;
    const now = Date.now();
    // Resample the (irregular) ledger history onto an hourly grid from midnight, so the category x-axis reads
    // as uniform time: each hour shows the cumulative spend at that moment.
    const today = pts.filter((p) => Date.parse(p.ts) >= start.getTime()).sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));
    const rows: { ts: string; used: number | null; forecast: number | null }[] = [];
    let j = 0;
    let acc = 0;
    for (let t = start.getTime(); t < now; t += step) {
      while (j < today.length && Date.parse(today[j].ts) <= t) acc = today[j++].used;
      rows.push({ ts: new Date(t).toISOString(), used: Math.min(acc, liveUsed), forecast: null });
    }
    rows.push({ ts: new Date(now).toISOString(), used: liveUsed, forecast: liveUsed });
    const elapsed = now - start.getTime();
    const rate = elapsed > 0 ? liveUsed / elapsed : 0;
    for (let t = Math.ceil(now / step) * step; t <= start.getTime() + 86_400_000; t += step) {
      rows.push({ ts: new Date(t).toISOString(), used: null, forecast: +(rate * (t - start.getTime())).toFixed(2) });
    }
    return rows;
  }, [d.history.data, liveUsed]);
  const forecast = data.at(-1)?.forecast ?? 0;
  return (
    <Panel
      className={className}
      title="Spend vs budget today"
      description={
        <>
          {fmtUsd(liveUsed, { dp: 2 })} of {fmtUsd(limit, { dp: 0 })} · forecast{' '}
          <span className={forecast >= limit ? 'text-block' : forecast >= limit * 0.8 ? 'text-redact' : 'text-text-2'}>{fmtUsd(forecast, { dp: 0 })}</span> by midnight
        </>
      }
      isMock={d.history.isMock || d.budgets.isMock}
    >
      <AreaTimeseries
        data={data}
        kind="area"
        height={196}
        series={[
          { key: 'used', label: 'Spent', color: '#3B78E6' },
          { key: 'forecast', label: 'Forecast', color: '#7A808C', dashed: true },
        ]}
        yFormat={(n) => fmtUsd(n, { dp: 0 })}
        yDomain={[0, Math.ceil(Math.max(limit * 1.1, forecast * 1.05))]}
        referenceLines={[
          { y: limit * 0.8, label: 'soft 80% · downgrade', color: '#C98500', dashed: true, labelBelow: true },
          { y: limit, label: 'hard 100% · block', color: '#E5446D', dashed: true },
        ]}
        xFormat={(v) => new Date(v).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
        legend={false}
        emptyText="No spend recorded today"
      />
    </Panel>
  );
}
