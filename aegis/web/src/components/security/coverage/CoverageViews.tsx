// Coverage matrix (OWASP LLM 2026 / ASI 2026 / MCP 2025) regenerated live from the policy, and the controls
// catalog table. A disabled control turns its tiles to "disabled" (rose hatch) on the next policy.applied.
import { motion, useReducedMotion } from 'framer-motion';
import { Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import type { ControlView, CoverageResponse } from '@/api/types';
import { ActionBadge } from '@/components/shell';
import { Gauge } from '@/components/charts';
import { fmtMs, fmtNum } from '@/lib/format';
import { cn } from '@/lib/utils';
import { ControlChip, SurfaceTag } from '../common/atoms';
import { KIND_COLORS } from '../common/colors';
import { MiniSelect } from '../live/FeedFilters';

type Status = CoverageResponse['frameworks'][number]['items'][number]['status'];

const TILE: Record<Status, { label: string; cls: string; style?: CSSProperties }> = {
  covered: { label: 'covered', cls: 'border-allow/35 bg-allow/[.07]' },
  partial: { label: 'partial', cls: 'border-redact/35 bg-redact/[.07]' },
  uncovered: { label: 'uncovered', cls: 'border-dashed border-border-strong bg-transparent' },
  disabled: {
    label: 'disabled',
    cls: 'border-block/45',
    style: { backgroundImage: 'repeating-linear-gradient(135deg, rgba(242,85,111,.14) 0 6px, transparent 6px 12px)' },
  },
};
const DOT: Record<Status, string> = { covered: 'bg-allow', partial: 'bg-redact', uncovered: 'bg-text-4', disabled: 'bg-block' };

export function CoverageMatrix({ data }: { data: CoverageResponse }) {
  const reduce = useReducedMotion();
  // remember previous statuses so tiles that changed since the last fetch pulse (F7 "disable DLP-02")
  const prev = useRef<Map<string, Status>>(new Map());
  const [changed, setChanged] = useState<Set<string>>(new Set());
  useEffect(() => {
    const next = new Map<string, Status>();
    const diff = new Set<string>();
    for (const f of data.frameworks)
      for (const it of f.items) {
        const k = `${f.id}:${it.id}`;
        next.set(k, it.status);
        const p = prev.current.get(k);
        if (p && p !== it.status) diff.add(k);
      }
    prev.current = next;
    if (diff.size) {
      setChanged(diff);
      const t = setTimeout(() => setChanged(new Set()), 2600);
      return () => clearTimeout(t);
    }
  }, [data]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4 text-xs text-text-3">
        {(Object.keys(TILE) as Status[]).map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <span className={cn('size-2 rounded-full', DOT[s])} />
            {TILE[s].label}
          </span>
        ))}
      </div>
      {data.frameworks.map((f) => {
        const covered = f.items.filter((i) => i.status === 'covered').length;
        const partial = f.items.filter((i) => i.status === 'partial').length;
        const pct = f.items.length ? ((covered + partial * 0.5) / f.items.length) * 100 : 0;
        return (
          <section key={f.id} className="rounded-xl border border-border bg-card p-4 shadow-card">
            <div className="mb-3 flex items-center gap-4">
              <Gauge value={Math.round(pct)} max={100} label="covered" format={(v) => `${v}%`} size={64} />
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-text-1">{f.name}</h3>
                <div className="text-xs text-text-3">
                  {covered} covered · {partial} partial · {f.items.filter((i) => i.status === 'disabled').length} disabled · {f.items.filter((i) => i.status === 'uncovered').length} uncovered
                </div>
              </div>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-5">
              {f.items.map((it, i) => {
                const k = `${f.id}:${it.id}`;
                const t = TILE[it.status];
                const flash = changed.has(k);
                return (
                  <motion.div
                    key={it.id}
                    initial={reduce ? false : { opacity: 0, y: 6 }}
                    animate={flash && !reduce ? { opacity: 1, y: 0, scale: [1, 1.04, 1] } : { opacity: 1, y: 0 }}
                    transition={{ delay: flash ? 0 : i * 0.02, duration: flash ? 0.6 : 0.3 }}
                    className={cn('relative min-h-[96px] rounded-lg border p-2.5', t.cls, flash && 'ring-2 ring-block/50')}
                    style={t.style}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-2xs text-text-3">{it.id}</span>
                      <span className={cn('rounded-full px-1.5 text-[10px] font-medium uppercase tracking-wide', it.status === 'disabled' ? 'bg-block/20 text-block' : it.status === 'covered' ? 'text-allow' : it.status === 'partial' ? 'text-redact' : 'text-text-4')}>
                        {t.label}
                      </span>
                    </div>
                    <div className={cn('mt-1 text-xs font-medium leading-4', it.status === 'uncovered' ? 'text-text-3' : 'text-text-1')}>{it.name}</div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {it.controls.map((c) => (
                        <ControlChip key={c} id={c} href={`/security/coverage?tab=controls&control=${encodeURIComponent(c)}`} />
                      ))}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}

const MODE_CLS: Record<string, string> = {
  enforce: 'text-allow border-allow/30 bg-allow/10',
  monitor: 'text-sky-300 border-sky-400/30 bg-sky-400/10',
  off: 'text-text-3 border-border bg-surface-2',
};

export function ControlsTable({ items, highlight }: { items: ControlView[]; highlight: string | null }) {
  const [family, setFamily] = useState('');
  const [mode, setMode] = useState('');
  const [q, setQ] = useState('');
  const families = useMemo(() => [...new Set(items.map((c) => c.family))].sort(), [items]);
  const rows = useMemo(
    () =>
      items.filter((c) => {
        if (family && c.family !== family) return false;
        if (mode === 'disabled' ? c.enabled : mode && (c.mode !== mode || !c.enabled)) return false;
        if (q && !`${c.id} ${c.name} ${c.owasp.join(' ')}`.toLowerCase().includes(q.toLowerCase())) return false;
        return true;
      }),
    [items, family, mode, q],
  );
  useEffect(() => {
    if (!highlight) return;
    const t = setTimeout(() => document.getElementById(`ctl-${highlight}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 200);
    return () => clearTimeout(t);
  }, [highlight, items.length]);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-4 py-2.5">
        <label className="flex h-8 min-w-[200px] items-center rounded-md border border-border bg-surface-1 px-2.5">
          <Search className="size-3.5 text-text-3" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search id, name, OWASP…" className="ml-2 w-full bg-transparent text-xs outline-none placeholder:text-text-4" />
        </label>
        <MiniSelect label="Family" value={family} onChange={setFamily} options={families.map((f) => ({ value: f, label: f }))} />
        <MiniSelect label="Mode" value={mode} onChange={setMode} options={['enforce', 'monitor', 'off', 'disabled'].map((m) => ({ value: m, label: m }))} />
        <Link to="/governance/policy" className="ml-auto text-xs text-accent-fg hover:underline">
          Edit in policy →
        </Link>
      </div>
      <div className="max-h-[620px] overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-[1] bg-surface-1/95 backdrop-blur">
            <tr className="border-b border-border text-left text-2xs uppercase tracking-[0.08em] text-text-3">
              <th className="px-4 py-2 font-medium">Control</th>
              <th className="px-2 py-2 font-medium">Kind</th>
              <th className="px-2 py-2 font-medium">Mode</th>
              <th className="px-2 py-2 font-medium">Action</th>
              <th className="px-2 py-2 text-right font-medium">Threshold</th>
              <th className="px-2 py-2 font-medium">OWASP</th>
              <th className="px-2 py-2 font-medium">Surfaces</th>
              <th className="px-2 py-2 text-right font-medium">Hits 24h</th>
              <th className="px-2 py-2 text-right font-medium">Blocks</th>
              <th className="px-4 py-2 text-right font-medium">p95</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr
                key={c.id}
                id={`ctl-${c.id}`}
                className={cn('border-b border-border-subtle transition-colors hover:bg-surface-2/50', !c.enabled && 'opacity-55', highlight === c.id && 'bg-brand/10 shadow-[inset_2px_0_0_var(--accent-fg)]')}
              >
                <td className="px-4 py-1.5">
                  <div className="flex items-center gap-2">
                    <ControlChip id={c.id} kind={c.kind} name={c.name} owner={c.owner} />
                    <span className="truncate text-text-1">{c.name}</span>
                    {!c.implemented ? <span className="rounded-full border border-border px-1.5 text-[10px] text-text-4">planned</span> : null}
                  </div>
                </td>
                <td className="px-2 py-1.5">
                  <span className="inline-flex items-center gap-1 text-text-2">
                    <span className="size-1.5 rounded-full" style={{ background: KIND_COLORS[c.kind] ?? '#64748B' }} />
                    {c.kind}
                  </span>
                </td>
                <td className="px-2 py-1.5">
                  <span className={cn('inline-flex h-5 items-center rounded-full border px-2 text-2xs font-medium', c.enabled ? (MODE_CLS[c.mode] ?? MODE_CLS.off) : 'border-block/30 bg-block/10 text-block')}>
                    {c.enabled ? c.mode : 'disabled'}
                  </span>
                </td>
                <td className="px-2 py-1.5">
                  <ActionBadge action={c.action} size="sm" />
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular text-text-2">{c.threshold ?? '—'}</td>
                <td className="px-2 py-1.5 font-mono text-2xs text-text-3">{c.owasp.slice(0, 2).join(' ')}</td>
                <td className="px-2 py-1.5">
                  <div className="flex max-w-[180px] flex-wrap gap-1">
                    {c.surfaces.slice(0, 2).map((s) => (
                      <SurfaceTag key={s} surface={s} />
                    ))}
                    {c.surfaces.length > 2 ? <span className="text-2xs text-text-3">+{c.surfaces.length - 2}</span> : null}
                  </div>
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular">{fmtNum(c.hits_24h)}</td>
                <td className={cn('px-2 py-1.5 text-right font-mono tabular', c.blocks_24h ? 'text-block' : 'text-text-3')}>{fmtNum(c.blocks_24h)}</td>
                <td className="px-4 py-1.5 text-right font-mono tabular text-text-2">{c.p95_ms !== null ? fmtMs(c.p95_ms) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
