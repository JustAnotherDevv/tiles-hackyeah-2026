// Performance tab: gateway overhead strip, per-control latency chart, semantic models,
// bench report (aegis.bench/1) with JsonView / empty-state fallbacks.
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { PerfResponse } from '@/api/types';
import { chartTheme, ChartTooltipBox } from '@/components/charts';
import { EmptyState, JsonView } from '@/components/shell';
import { fmtAgo, fmtDateTime, fmtMs, fmtNum } from '@/lib/format';
import { cn } from '@/lib/utils';
import { KIND_COLORS } from '../common/colors';
import type { BenchReport } from '../types';

type ControlRow = PerfResponse['by_control'][number];

export function ControlLatencyChart({ items, height }: { items: ControlRow[]; height?: number }) {
  const rows = [...items].sort((a, b) => b.p95_ms - a.p95_ms).slice(0, 18);
  const h = height ?? Math.max(220, rows.length * 22 + 40);
  const kinds = [...new Set(rows.map((r) => r.kind))].sort();
  if (!rows.length) return <EmptyState icon="Timer" title="No latency samples yet" hint="Per-control timings appear after the first guarded requests." />;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-text-3">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-1.5 w-3 rounded-[1px] bg-[#3B4252]" /> p50
        </span>
        {kinds.map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className="h-1.5 w-3 rounded-[1px]" style={{ background: KIND_COLORS[k] ?? '#818CF8' }} /> p95 · {k}
          </span>
        ))}
        <span className="ml-auto text-text-4">top {rows.length} by p95 · √ scale</span>
      </div>
      <div style={{ height: h }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 0 }} barGap={2}>
          <CartesianGrid horizontal={false} stroke={chartTheme.grid} />
          <XAxis type="number" tick={chartTheme.tick} stroke={chartTheme.axis} tickFormatter={(v: number) => `${v} ms`} scale="sqrt" />
          <YAxis type="category" dataKey="control_id" tick={{ ...chartTheme.tick, fontFamily: 'var(--font-mono, monospace)' }} stroke={chartTheme.axis} width={60} interval={0} />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,.03)' }}
            isAnimationActive={false}
            content={({ active, payload }) => {
              const p = active && payload?.[0] ? (payload[0].payload as ControlRow) : null;
              if (!p) return null;
              return (
                <ChartTooltipBox
                  title={`${p.control_id} · ${p.kind}`}
                  rows={[
                    { label: 'p50', value: fmtMs(p.p50_ms), color: '#64748B' },
                    { label: 'p95', value: fmtMs(p.p95_ms), color: KIND_COLORS[p.kind] ?? '#818CF8' },
                    { label: 'samples', value: fmtNum(p.count), color: 'transparent' },
                  ]}
                />
              );
            }}
          />
          <Bar dataKey="p50_ms" fill="#3B4252" radius={[0, 2, 2, 0]} barSize={7} isAnimationActive={false} />
          <Bar dataKey="p95_ms" radius={[0, 2, 2, 0]} barSize={7} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.control_id} fill={KIND_COLORS[r.kind] ?? '#818CF8'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      </div>
    </div>
  );
}

function StatCell({ label, value, unit, tone }: { label: string; value: string; unit?: string; tone?: 'warn' | 'bad' }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <dt className="truncate text-2xs text-text-3">{label}</dt>
      <dd className={cn('mt-0.5 font-mono text-lg font-medium tabular leading-6', tone === 'bad' ? 'text-block' : tone === 'warn' ? 'text-redact' : 'text-text-1')}>
        {value}
        {unit ? <span className="ml-1 text-xs font-normal text-text-3">{unit}</span> : null}
      </dd>
    </div>
  );
}

const msParts = (ms: number): [string, string] => {
  const [v, u] = fmtMs(ms).split(' ');
  return [v, u ?? ''];
};

/** Gateway overhead (time Aegis adds per decision) + throughput, as one dense strip. */
export function OverheadTiles({ perf }: { perf: PerfResponse }) {
  const o = perf.overhead_ms;
  const cells: { label: string; ms?: number; value?: string; unit?: string; tone?: 'warn' | 'bad' }[] = [
    { label: 'Overhead p50', ms: o.p50 },
    { label: 'Overhead p95', ms: o.p95, tone: o.p95 > 250 ? 'bad' : o.p95 > 50 ? 'warn' : undefined },
    { label: 'Overhead p99', ms: o.p99 },
    { label: 'Decisions measured', value: fmtNum(o.count) },
    { label: 'Throughput (1 min)', value: perf.rps_1m.toFixed(1), unit: 'req/s' },
  ];
  return (
    <section className="rounded-lg border border-border bg-card shadow-card">
      <dl className="grid grid-cols-2 divide-border-subtle sm:grid-cols-3 lg:grid-cols-5 lg:divide-x">
        {cells.map((c) => {
          const [v, u] = c.ms !== undefined ? msParts(c.ms) : [c.value ?? '—', c.unit];
          return <StatCell key={c.label} label={c.label} value={v} unit={u} tone={c.tone} />;
        })}
      </dl>
    </section>
  );
}

export function SemanticModels({ semantic }: { semantic: PerfResponse['semantic'] }) {
  const loaded = semantic.models.filter((m) => m.loaded).length;
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-text-3">
        <span>
          Mode <span className="font-mono text-text-1">{semantic.mode}</span>
        </span>
        <span>·</span>
        <span className="font-mono tabular">
          {loaded}/{semantic.models.length} loaded
        </span>
        {semantic.degraded ? <span className="rounded-[4px] border border-redact/30 bg-redact/10 px-1.5 text-2xs text-redact">degraded</span> : null}
      </div>
      {semantic.degraded ? <p className="mb-2 text-2xs text-text-4">Semantic tier unavailable: deterministic and heuristic controls still run.</p> : null}
      {semantic.models.length ? (
        <table className="w-full text-xs">
          <tbody>
            {[...semantic.models].sort((a, b) => Number(b.loaded) - Number(a.loaded)).map((m) => (
              <tr key={m.name} className="border-b border-border-subtle last:border-0">
                <td className="py-1.5 pr-2">
                  <span className="inline-flex items-center gap-2">
                    <span className={cn('size-1.5 shrink-0 rounded-full', m.loaded ? 'bg-allow' : 'bg-text-4')} />
                    <span className={cn('font-mono', m.loaded ? 'text-text-1' : 'text-text-3')}>{m.name}</span>
                  </span>
                </td>
                <td className="px-2 py-1.5 text-text-3">{m.backend}</td>
                <td className="py-1.5 pl-2 text-right font-mono tabular text-text-2">{m.p50_ms !== null ? `p50 ${fmtMs(m.p50_ms)}` : <span className="text-text-4">{m.loaded ? '—' : 'not loaded'}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="py-2 text-xs text-text-3">No semantic models configured.</p>
      )}
    </div>
  );
}

function isBench(b: unknown): b is BenchReport {
  return !!b && typeof b === 'object' && (b as { schema?: unknown }).schema === 'aegis.bench/1' && Array.isArray((b as { profiles?: unknown }).profiles);
}

export function BenchPanel({ bench }: { bench: PerfResponse['bench'] }) {
  if (!bench) return <EmptyState icon="Gauge" title="No benchmark report yet" hint={<>Run <code className="font-mono text-text-1">make bench</code> to write reports/bench.json.</>} />;
  if (!isBench(bench)) return <JsonView value={bench} collapsed={1} />;
  return (
    <div className="space-y-2">
      <div className="text-xs text-text-3">
        {bench.machine.cpu} · {bench.machine.ram_gb} GB RAM · {bench.machine.os} · Python {bench.machine.python} · <span title={fmtDateTime(bench.generated_at)}>{fmtAgo(bench.generated_at)}</span>
      </div>
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full min-w-[480px] text-xs">
          <thead>
            <tr className="border-b border-border bg-surface-2/50 text-left text-2xs uppercase tracking-[0.06em] text-text-3">
              <th className="px-3 py-2 font-medium">Profile</th>
              <th className="px-2 py-2 text-right font-medium" title="Concurrent clients">Conc.</th>
              <th className="px-2 py-2 text-right font-medium">Req/s</th>
              <th className="px-2 py-2 text-right font-medium">p50</th>
              <th className="px-2 py-2 text-right font-medium">p95</th>
              <th className="px-3 py-2 text-right font-medium">p99</th>
            </tr>
          </thead>
          <tbody>
            {bench.profiles.map((p) => (
              <tr key={p.name} className="border-b border-border-subtle last:border-0">
                <td className="px-3 py-1.5">
                  <div className="font-mono text-text-1">{p.name}</div>
                  {p.description ? <div className="text-2xs text-text-3">{p.description}</div> : null}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 text-right font-mono tabular">{p.concurrency}</td>
                <td className="whitespace-nowrap px-2 py-1.5 text-right font-mono tabular">{fmtNum(p.rps, { dp: 1 })}</td>
                <td className="whitespace-nowrap px-2 py-1.5 text-right font-mono tabular">{fmtMs(p.overhead_ms.p50)}</td>
                <td className="whitespace-nowrap px-2 py-1.5 text-right font-mono tabular">{fmtMs(p.overhead_ms.p95)}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-right font-mono tabular">{fmtMs(p.overhead_ms.p99)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
