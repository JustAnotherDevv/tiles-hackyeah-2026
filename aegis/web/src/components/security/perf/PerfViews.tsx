// Performance tab: overhead tiles, per-control latency chart (exported for /system/perf), semantic models,
// bench report (aegis.bench/1) with JsonView / empty-state fallbacks.
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { PerfResponse } from '@/api/types';
import { chartTheme, ChartTooltipBox } from '@/components/charts';
import { EmptyState, JsonView, KpiTile } from '@/components/shell';
import { fmtMs, fmtNum } from '@/lib/format';
import { cn } from '@/lib/utils';
import { KIND_COLORS } from '../common/colors';
import type { BenchReport } from '../types';

type ControlRow = PerfResponse['by_control'][number];

export function ControlLatencyChart({ items, height }: { items: ControlRow[]; height?: number }) {
  const rows = [...items].sort((a, b) => b.p95_ms - a.p95_ms).slice(0, 18);
  const h = height ?? Math.max(220, rows.length * 24 + 40);
  return (
    <div style={{ height: h }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }} barGap={2}>
          <CartesianGrid horizontal={false} stroke={chartTheme.grid} />
          <XAxis type="number" tick={chartTheme.tick} stroke={chartTheme.axis} tickFormatter={(v: number) => `${v} ms`} scale="sqrt" />
          <YAxis type="category" dataKey="control_id" tick={{ ...chartTheme.tick, fontFamily: 'var(--font-mono, monospace)' }} stroke={chartTheme.axis} width={64} />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,.03)' }}
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
          <Bar dataKey="p50_ms" fill="#3B4252" radius={[0, 3, 3, 0]} barSize={7} animationDuration={chartTheme.animationMs} />
          <Bar dataKey="p95_ms" radius={[0, 3, 3, 0]} barSize={7} animationDuration={chartTheme.animationMs}>
            {rows.map((r) => (
              <Cell key={r.control_id} fill={KIND_COLORS[r.kind] ?? '#818CF8'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function OverheadTiles({ perf }: { perf: PerfResponse }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <KpiTile label="Overhead p50" value={fmtMs(perf.overhead_ms.p50)} icon="Timer" tone="good" />
      <KpiTile label="Overhead p95" value={fmtMs(perf.overhead_ms.p95)} icon="Timer" tone={perf.overhead_ms.p95 > 50 ? 'warn' : 'good'} />
      <KpiTile label="Overhead p99" value={fmtMs(perf.overhead_ms.p99)} icon="Timer" />
      <KpiTile label="Decisions measured" value={perf.overhead_ms.count} icon="Hash" />
      <KpiTile label="Requests / s (1 min)" value={perf.rps_1m.toFixed(1)} icon="Activity" />
    </div>
  );
}

export function SemanticModels({ semantic }: { semantic: PerfResponse['semantic'] }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs text-text-3">
        mode <span className="font-mono text-text-1">{semantic.mode}</span>
        {semantic.degraded ? <span className="rounded-full border border-redact/30 bg-redact/10 px-1.5 text-2xs text-redact">degraded</span> : null}
      </div>
      <ul className="divide-y divide-border-subtle">
        {semantic.models.map((m) => (
          <li key={m.name} className="flex items-center gap-3 py-2 text-xs">
            <span className={cn('size-2 rounded-full', m.loaded ? 'bg-allow' : 'bg-text-4')} />
            <span className="font-mono text-text-1">{m.name}</span>
            <span className="text-text-3">{m.backend}</span>
            <span className="ml-auto font-mono tabular text-text-2">{m.p50_ms !== null ? `p50 ${fmtMs(m.p50_ms)}` : m.loaded ? '—' : 'not loaded'}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function isBench(b: unknown): b is BenchReport {
  return !!b && typeof b === 'object' && (b as { schema?: unknown }).schema === 'aegis.bench/1' && Array.isArray((b as { profiles?: unknown }).profiles);
}

export function BenchPanel({ bench }: { bench: PerfResponse['bench'] }) {
  if (!bench) return <EmptyState icon="Gauge" title="No benchmark report yet" hint={<>Run <code className="font-mono text-text-1">make bench</code> to produce reports/bench.json.</>} />;
  if (!isBench(bench)) return <JsonView value={bench} collapsed={1} />;
  return (
    <div className="space-y-2">
      <div className="text-xs text-text-3">
        {bench.machine.cpu} · {bench.machine.ram_gb} GB · {bench.machine.os} · Python {bench.machine.python} · {new Date(bench.generated_at).toLocaleString()}
      </div>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-surface-2/50 text-left text-2xs uppercase tracking-[0.08em] text-text-3">
              <th className="px-3 py-2 font-medium">Profile</th>
              <th className="px-2 py-2 text-right font-medium">Conc.</th>
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
                <td className="px-2 py-1.5 text-right font-mono tabular">{p.concurrency}</td>
                <td className="px-2 py-1.5 text-right font-mono tabular">{fmtNum(p.rps, { dp: 1 })}</td>
                <td className="px-2 py-1.5 text-right font-mono tabular">{fmtMs(p.overhead_ms.p50)}</td>
                <td className="px-2 py-1.5 text-right font-mono tabular">{fmtMs(p.overhead_ms.p95)}</td>
                <td className="px-3 py-1.5 text-right font-mono tabular">{fmtMs(p.overhead_ms.p99)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
