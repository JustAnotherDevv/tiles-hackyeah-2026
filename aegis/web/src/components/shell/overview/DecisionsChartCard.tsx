// Row C (8 cols) — stacked decisions over time; toggle Interventions (redact · approval · block) / All
// traffic. Last bucket grows live via the overview overlay. Legend always shown (CVD secondary encoding).
import { useState } from 'react';
import { AreaTimeseries } from '@/components/charts/AreaTimeseries';
import { ACTION_CHART_ORDER, ACTION_COLORS } from '@/lib/colors';
import { fmtNum } from '@/lib/format';
import { Panel } from '../Panel';
import { Segmented } from '../Segmented';
import type { OverviewData } from './useOverviewData';

type Mode = 'interventions' | 'all';
const INTERVENTIONS = new Set(['redact', 'require_approval', 'block']);

function tickFormat(win: string) {
  return (v: string | number) => {
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return String(v);
    if (win === '7d') return d.toLocaleDateString('en-GB', { weekday: 'short', hour: '2-digit' }).replace(',', '');
    return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  };
}

export function DecisionsChartCard({ d, className }: { d: OverviewData; className?: string }) {
  const [mode, setMode] = useState<Mode>('interventions');
  const v = d.view;
  const series = ACTION_CHART_ORDER.filter((a) => mode === 'all' || INTERVENTIONS.has(a)).map((a) => ({ key: a, label: ACTION_COLORS[a].label, color: ACTION_COLORS[a].chart }));
  const k = v?.kpis;
  const interventions = (k?.redacted ?? 0) + (k?.blocked ?? 0) + (v?.timeseries.reduce((a, b) => a + b.require_approval, 0) ?? 0);
  return (
    <Panel
      className={className}
      title="Decisions over time"
      description={
        <>
          <span className="tabular text-text-2">{fmtNum(interventions)}</span> interventions · <span className="tabular text-text-2">{fmtNum(k?.requests ?? 0)}</span> requests in {v?.window ?? '—'}
        </>
      }
      isMock={d.stats.isMock}
      actions={
        <Segmented<Mode>
          ariaLabel="Chart series"
          value={mode}
          onChange={setMode}
          options={[
            { value: 'interventions', label: 'Interventions' },
            { value: 'all', label: 'All traffic' },
          ]}
        />
      }
    >
      <AreaTimeseries
        data={v?.timeseries ?? []}
        xKey="ts"
        kind="bar"
        stacked
        height={232}
        // No bar tween: the last bucket updates on every 2 s stats tick, and recharts' JavascriptAnimate could
        // re-trigger itself under heavy CPU load ("Maximum update depth exceeded" crashed the overview).
        animate={false}
        series={series}
        xFormat={tickFormat(v?.window ?? '24h')}
        tooltipLabel={(x) => new Date(x).toLocaleString('en-GB', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}
        tooltipTotal
        yFormat={(n) => fmtNum(n, { compact: true })}
        legend
        emptyText="No decisions in this window yet"
      />
    </Panel>
  );
}
