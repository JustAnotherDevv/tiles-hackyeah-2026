// /system/perf — "Proof" (flow F10): gateway overhead p50/p95/p99, overhead share of upstream, live
// p50/p95 from SSE stats ticks, per-control p95, upstream by provider/model, semantic models, bench.json
// headline (A-54) and a "how we measure" note. Refresh 5 s. Owner: dashboard-shell (B16).
import { useEffect, useState } from 'react';
import { useApi, useStatsTick } from '@/api/hooks';
import type { PerfResponse } from '@/api/types';
import { AreaTimeseries } from '@/components/charts/AreaTimeseries';
import { BarList } from '@/components/charts/BarList';
import { JsonView, KpiTile, PageHeader, Panel, StatusDot } from '@/components/shell';
import { EmptyState } from '@/components/shell/EmptyState';
import { fmtMs, fmtNum, fmtPct } from '@/lib/format';
import type { PageMeta } from '@/lib/page';
import { cn } from '@/lib/utils';
import { mockPerf } from '@/mocks/shell/perf';

export const meta: PageMeta = {
  path: '/system/perf',
  title: 'Performance',
  icon: 'Timer',
  section: 'System',
  order: 10,
  shortcut: 'g m',
  description: 'Gateway overhead p50/p95/p99, per-control latency, upstream share',
};

const KIND_TINT: Record<string, string> = { deterministic: '#3987E5', semantic: '#8B5CF6', stateful: '#0891B2', model: '#8B5CF6' };

type Headline = Partial<Record<'det_overhead_p50_ms' | 'det_overhead_p95_ms' | 'sem_overhead_p50_ms' | 'sem_overhead_p95_ms' | 'rps_det' | 'overhead_share_pct' | 'reload_p95_ms' | 'detection_rate_balanced' | 'fpr_balanced' | 'obfuscation_coverage', number | null>>;

function useLiveOverhead() {
  const tick = useStatsTick();
  const [pts, setPts] = useState<{ ts: string; p50: number; p95: number }[]>([]);
  useEffect(() => {
    if (!tick) return;
    setPts((p) => [...p, { ts: tick.ts, p50: tick.p50_overhead_ms, p95: tick.p95_overhead_ms }].slice(-60));
  }, [tick]);
  return pts;
}

function headlineRows(h: Headline): { label: string; value: string }[] {
  const ms = (v: number | null | undefined) => (typeof v === 'number' ? fmtMs(v) : 'not measured');
  const pct = (v: number | null | undefined, ratio = false) => (typeof v === 'number' ? fmtPct(ratio ? v * 100 : v, 1) : 'not measured');
  return [
    { label: 'Deterministic overhead p50 / p95', value: `${ms(h.det_overhead_p50_ms)} / ${ms(h.det_overhead_p95_ms)}` },
    { label: 'Semantic overhead p50 / p95', value: `${ms(h.sem_overhead_p50_ms)} / ${ms(h.sem_overhead_p95_ms)}` },
    { label: 'Throughput (deterministic)', value: typeof h.rps_det === 'number' ? `${fmtNum(h.rps_det, { dp: 0 })} rps` : 'not measured' },
    { label: 'Overhead share of upstream', value: pct(h.overhead_share_pct) },
    { label: 'Policy hot-reload p95', value: ms(h.reload_p95_ms) },
    { label: 'Detection rate (balanced)', value: pct(h.detection_rate_balanced, (h.detection_rate_balanced ?? 2) <= 1) },
    { label: 'False-positive rate (balanced)', value: pct(h.fpr_balanced, (h.fpr_balanced ?? 2) <= 1) },
    { label: 'Obfuscation coverage', value: pct(h.obfuscation_coverage, (h.obfuscation_coverage ?? 2) <= 1) },
  ];
}

export default function PerfPage() {
  const perf = useApi<PerfResponse>('/api/perf', { mock: mockPerf, refreshMs: 5000 });
  const live = useLiveOverhead();
  const p = perf.data;
  const o = p?.overhead_ms;
  const realUp = (p?.upstream_ms ?? []).filter((u) => u.provider !== 'mock');
  const upCount = realUp.reduce((a, u) => a + u.count, 0);
  const upP50 = upCount ? realUp.reduce((a, u) => a + u.p50 * u.count, 0) / upCount : null;
  const share = o && upP50 ? (o.p50 / upP50) * 100 : null;
  const bench = (p?.bench ?? null) as (Record<string, unknown> & { headline?: Headline }) | null;
  const controls = (p?.by_control ?? []).slice().sort((a, b) => b.p95_ms - a.p95_ms);

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="Performance" icon="Timer" subtitle="What Aegis adds on top of every call — measured in-process on this machine, not estimated" />
      <div className="grid grid-cols-5 gap-3 max-[1360px]:grid-cols-3 max-[760px]:grid-cols-1">
        <KpiTile label="Overhead p50" icon="Gauge" tone="good" loading={!o} value={o ? fmtMs(o.p50) : '—'} hint={`${fmtNum(o?.count ?? 0, { compact: true })} requests sampled`} right={perf.isMock ? <span className="text-[10.5px] text-text-4">demo</span> : null} />
        <KpiTile label="Overhead p95" icon="Gauge" loading={!o} value={o ? fmtMs(o.p95) : '—'} hint="incl. semantic guards when warm" />
        <KpiTile label="Overhead p99" icon="Gauge" loading={!o} value={o ? fmtMs(o.p99) : '—'} hint="tail latency" />
        <KpiTile label="Throughput" icon="Activity" loading={!p} value={p ? `${p.rps_1m.toFixed(2)}` : '—'} suffix="rps" hint="last minute, live traffic" />
        <KpiTile
          label="Share of upstream"
          icon="Percent"
          tone={share !== null && share < 1 ? 'good' : 'neutral'}
          loading={!p}
          value={share !== null ? fmtPct(share, 2) : '—'}
          hint={share !== null && o && upP50 ? `${fmtMs(o.p50)} of ${fmtMs(upP50)} model latency` : 'no upstream calls yet'}
        />
      </div>

      <div className="grid grid-cols-12 gap-3">
        <Panel className="col-span-7 max-[1180px]:col-span-12" title="Live overhead" description="p50 / p95 from the gateway's 2 s stats ticks (last 2 min)" isMock={perf.isMock && live.length === 0}>
          {live.length < 2 ? (
            <EmptyState icon="Activity" title="Waiting for stats ticks…" hint="The gateway publishes a `stats` event every ~2 s over SSE." className="h-[220px]" />
          ) : (
            <AreaTimeseries
              data={live}
              kind="line"
              height={220}
              series={[
                { key: 'p50', label: 'p50', color: '#3987E5' },
                { key: 'p95', label: 'p95', color: '#DB2777' },
              ]}
              yFormat={(n) => fmtMs(n)}
              xFormat={(v) => new Date(v).toLocaleTimeString('en-GB', { minute: '2-digit', second: '2-digit' })}
              legend
            />
          )}
        </Panel>
        <Panel className="col-span-5 max-[1180px]:col-span-12" title="Per-control latency" description="p95 per control · colour = kind" isMock={perf.isMock}>
          <BarList
            items={controls.map((c) => ({
              key: c.control_id,
              label: <span className="font-mono text-[12px]">{c.control_id}</span>,
              hint: `${c.kind} · p50 ${fmtMs(c.p50_ms)} · ${fmtNum(c.count, { compact: true })}×`,
              value: c.p95_ms,
              color: KIND_TINT[c.kind] ?? '#5B6475',
            }))}
            limit={9}
            valueFormat={(n) => fmtMs(n)}
            labelWidth={150}
            emptyText="No control timings yet"
          />
        </Panel>
      </div>

      <div className="grid grid-cols-12 gap-3">
        <Panel className="col-span-5 max-[1180px]:col-span-12" title="Upstream latency" description="Model / provider time — what Aegis' overhead is compared against" isMock={perf.isMock} flush>
          <table className="mt-2 w-full border-t border-border-subtle text-[12.5px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-[0.06em] text-text-4">
                <th className="px-4 py-2 font-medium">Provider · model</th>
                <th className="px-2 py-2 text-right font-medium">p50</th>
                <th className="px-2 py-2 text-right font-medium">p95</th>
                <th className="px-4 py-2 text-right font-medium">calls</th>
              </tr>
            </thead>
            <tbody>
              {(p?.upstream_ms ?? []).map((u) => (
                <tr key={`${u.provider}:${u.model}`} className="border-t border-border-subtle">
                  <td className="px-4 py-2">
                    <span className="text-text-1">{u.provider}</span>
                    <span className="ml-2 font-mono text-[11.5px] text-text-3">{u.model ?? '—'}</span>
                  </td>
                  <td className="px-2 py-2 text-right tabular text-text-2">{fmtMs(u.p50)}</td>
                  <td className="px-2 py-2 text-right tabular text-text-2">{fmtMs(u.p95)}</td>
                  <td className="px-4 py-2 text-right tabular text-text-3">{fmtNum(u.count, { compact: true })}</td>
                </tr>
              ))}
              {p && p.upstream_ms.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-text-3">
                    No upstream calls yet
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </Panel>
        <Panel className="col-span-4 max-[1180px]:col-span-7 max-[760px]:col-span-12" title="Local models" description={p ? `mode ${p.semantic.mode}${p.semantic.degraded ? ' · degraded → deterministic fallback' : ''}` : undefined} isMock={perf.isMock} flush>
          <div className="mt-2 border-t border-border-subtle">
            {(p?.semantic.models ?? []).map((m) => (
              <div key={m.name} className="flex items-center gap-2.5 border-b border-border-subtle px-4 py-2.5 text-[12.5px] last:border-b-0">
                <StatusDot status={m.loaded ? 'ok' : 'off'} pulse={m.loaded} />
                <span className="min-w-0 flex-1 truncate text-text-1">{m.name}</span>
                <span className="rounded border border-border bg-surface-2 px-1.5 font-mono text-[10.5px] text-text-3">{m.backend}</span>
                <span className="w-14 text-right tabular text-text-2">{m.p50_ms !== null ? fmtMs(m.p50_ms) : '—'}</span>
              </div>
            ))}
            {p && p.semantic.models.length === 0 ? <EmptyState icon="Cpu" title="No local models loaded" hint="Deterministic controls still enforce." /> : null}
          </div>
        </Panel>
        <Panel className="col-span-3 max-[1180px]:col-span-5 max-[760px]:col-span-12" title="How we measure">
          <div className="flex flex-col gap-2 text-[12.5px] leading-[18px] text-text-2">
            <p>Every response carries a <span className="font-mono text-text-1">Server-Timing</span> header; overhead = total − upstream, measured with a monotonic clock inside the gateway.</p>
            <pre className="overflow-x-auto rounded-md border border-border bg-surface-2 p-2 font-mono text-[11px] text-text-3">
              {'Server-Timing: aegis;dur=0.41,\n  upstream;dur=812.3,\n  ctl-INJ-02;dur=0.62'}
            </pre>
            <p className="text-text-3">
              Bench: <span className="font-mono">make bench</span> → <span className="font-mono">reports/bench.json</span>
            </p>
          </div>
        </Panel>
      </div>

      <Panel title="Benchmark report" description="reports/bench.json (aegis.bench/1) — missing numbers print “not measured”, never a guess" isMock={perf.isMock}>
        {bench ? (
          <div className="grid grid-cols-12 gap-4">
            <div className="col-span-5 max-[1180px]:col-span-12">
              {headlineRows(bench.headline ?? {}).map((r) => (
                <div key={r.label} className="flex items-center gap-3 border-b border-border-subtle py-[7px] text-[12.5px] last:border-b-0">
                  <span className="text-text-3">{r.label}</span>
                  <span className={cn('ml-auto tabular', r.value === 'not measured' ? 'text-text-4' : 'text-text-1')}>{r.value}</span>
                </div>
              ))}
            </div>
            <div className="col-span-7 max-[1180px]:col-span-12">
              <JsonView value={bench} collapsed={1} maxHeight={300} />
            </div>
          </div>
        ) : (
          <EmptyState icon="FileBarChart" title="No benchmark report yet" hint="Run `make bench` to produce reports/bench.json — it appears here automatically." />
        )}
      </Panel>
    </div>
  );
}
