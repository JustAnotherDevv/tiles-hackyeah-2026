// Coverage matrix (OWASP LLM 2026 / ASI 2026 / MCP 2025) regenerated live from the policy, and the controls
// catalog table. A disabled control turns its tiles to "disabled" (hatched red) on the next policy.applied.
import { Search } from '@/components/icons';
import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import type { ControlView, CoverageResponse } from '@/api/types';
import { ActionBadge, EmptyState } from '@/components/shell';
import { fmtMs, fmtNum } from '@/lib/format';
import { cn } from '@/lib/utils';
import { ControlChip, SurfaceTag } from '../common/atoms';
import { KIND_COLORS } from '../common/colors';
import { MiniSelect } from '../live/FeedFilters';

type Status = CoverageResponse['frameworks'][number]['items'][number]['status'];
const STATUSES: Status[] = ['covered', 'partial', 'disabled', 'uncovered'];

// status meanings mirror aegis.policy.views.coverage(): an item takes the best state of its mapped controls
const TILE: Record<Status, { label: string; meaning: string; cls: string; text: string; dot: string; style?: CSSProperties }> = {
  covered: { label: 'Covered', meaning: 'at least one mapped control enforces', cls: 'border-border bg-surface-1', text: 'text-allow', dot: 'bg-allow' },
  partial: {
    label: 'Partial',
    meaning: 'mapped controls only monitor (log, no enforcement)',
    cls: 'border-redact/40 bg-redact/[.06]',
    text: 'text-redact',
    dot: 'bg-redact',
  },
  disabled: {
    label: 'Disabled',
    meaning: 'every mapped control is switched off',
    cls: 'border-block/50',
    text: 'text-block',
    dot: 'bg-block',
    style: { backgroundImage: 'repeating-linear-gradient(135deg, rgba(229,68,109,.10) 0 5px, transparent 5px 10px)' },
  },
  uncovered: { label: 'Uncovered', meaning: 'no control maps to this risk', cls: 'border-dashed border-border-strong bg-transparent', text: 'text-text-3', dot: 'bg-text-4' },
};

function tally(items: CoverageResponse['frameworks'][number]['items']) {
  const c: Record<Status, number> = { covered: 0, partial: 0, disabled: 0, uncovered: 0 };
  for (const i of items) c[i.status] += 1;
  const total = items.length;
  return { ...c, total, pct: total ? Math.round(((c.covered + c.partial * 0.5) / total) * 100) : 0 };
}

/** Stacked status bar: covered / partial / disabled / uncovered share of a framework's items. */
function StatusBar({ t, className }: { t: ReturnType<typeof tally>; className?: string }) {
  return (
    <div className={cn('flex h-1.5 overflow-hidden rounded-full bg-surface-3', className)} aria-hidden>
      {STATUSES.filter((s) => s !== 'uncovered').map((s) => (t[s] ? <span key={s} className={TILE[s].dot} style={{ width: `${(t[s] / t.total) * 100}%` }} /> : null))}
    </div>
  );
}

function statusMap(d: CoverageResponse): Map<string, Status> {
  const m = new Map<string, Status>();
  for (const f of d.frameworks) for (const it of f.items) m.set(`${f.id}:${it.id}`, it.status);
  return m;
}

export function CoverageMatrix({ data }: { data: CoverageResponse }) {
  // tiles whose status changed since the previous fetch get a ring for 2.6 s (demo: disable DLP-02).
  // Derived during render from the previous payload (no setState-in-effect).
  const [snap, setSnap] = useState<{ data: CoverageResponse; changed: Set<string> }>({ data, changed: new Set() });
  if (snap.data !== data) {
    const before = statusMap(snap.data);
    const diff = new Set<string>();
    for (const [k, st] of statusMap(data)) if (before.has(k) && before.get(k) !== st) diff.add(k);
    setSnap({ data, changed: diff });
  }
  const changed = snap.changed;
  useEffect(() => {
    if (!changed.size) return;
    const t = setTimeout(() => setSnap((s) => ({ ...s, changed: new Set() })), 2600);
    return () => clearTimeout(t);
  }, [changed]);
  const tallies = useMemo(() => data.frameworks.map((f) => ({ f, t: tally(f.items) })), [data]);

  if (!data.frameworks.length) {
    return (
      <section className="rounded-lg border border-border bg-card shadow-card">
        <EmptyState icon="ShieldCheck" title="No frameworks configured" hint="The coverage endpoint returned no OWASP frameworks." />
      </section>
    );
  }

  return (
    <div className="space-y-4">
      {/* summary: one row per framework */}
      <section className="min-w-0 rounded-lg border border-border bg-card shadow-card">
        <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-border-subtle px-4 py-3">
          <h2 className="text-[13px] font-[550] leading-[18px] text-text-1">Framework coverage</h2>
          <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {STATUSES.map((s) => (
              <div key={s} className="inline-flex items-center gap-1.5" title={TILE[s].meaning}>
                <span className={cn('size-2 rounded-[2px]', TILE[s].dot)} />
                <dt className="text-text-2">{TILE[s].label}</dt>
                <dd className="text-text-3">— {TILE[s].meaning}</dd>
              </div>
            ))}
          </dl>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-xs">
            <thead>
              <tr className="border-b border-border-subtle text-left text-2xs uppercase tracking-[0.06em] text-text-3">
                <th className="px-4 py-2 font-medium">Framework</th>
                <th className="px-2 py-2 text-right font-medium">Covered</th>
                <th className="px-2 py-2 text-right font-medium">Partial</th>
                <th className="px-2 py-2 text-right font-medium">Disabled</th>
                <th className="px-2 py-2 text-right font-medium">Uncovered</th>
                <th className="w-[28%] px-4 py-2 font-medium">Score</th>
              </tr>
            </thead>
            <tbody>
              {tallies.map(({ f, t }) => (
                <tr key={f.id} className="border-b border-border-subtle last:border-0">
                  <td className="px-4 py-2">
                    <a href={`#fw-${f.id}`} className="text-text-1 hover:underline">
                      {f.name}
                    </a>
                    <div className="font-mono text-2xs text-text-4">{f.id}</div>
                  </td>
                  <td className="px-2 py-2 text-right font-mono tabular text-text-1">{t.covered}</td>
                  <td className={cn('px-2 py-2 text-right font-mono tabular', t.partial ? 'text-redact' : 'text-text-4')}>{t.partial}</td>
                  <td className={cn('px-2 py-2 text-right font-mono tabular', t.disabled ? 'text-block' : 'text-text-4')}>{t.disabled}</td>
                  <td className={cn('px-2 py-2 text-right font-mono tabular', t.uncovered ? 'text-text-2' : 'text-text-4')}>{t.uncovered}</td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-3">
                      <StatusBar t={t} className="flex-1" />
                      <span className="w-10 text-right font-mono tabular text-text-1">{t.pct}%</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="border-t border-border-subtle px-4 py-2 text-2xs text-text-4">Score = (covered + ½ partial) / items. Regenerated on every policy change.</p>
      </section>

      {tallies.map(({ f, t }) => (
        <section key={f.id} id={`fw-${f.id}`} className="min-w-0 scroll-mt-20 rounded-lg border border-border bg-card shadow-card">
          <header className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-3.5">
            <h3 className="min-w-0 flex-1 text-[13px] font-[550] leading-[18px] text-text-1">{f.name}</h3>
            <span className="font-mono text-xs tabular text-text-3">
              {t.covered}/{t.total} covered{t.partial ? ` · ${t.partial} partial` : ''}
              {t.disabled ? ` · ${t.disabled} disabled` : ''} · <span className="text-text-1">{t.pct}%</span>
            </span>
          </header>
          <ul className="grid grid-cols-1 gap-2 p-4 min-[480px]:grid-cols-2 md:grid-cols-3 xl:grid-cols-5">
            {f.items.map((it) => {
              const k = `${f.id}:${it.id}`;
              const tile = TILE[it.status];
              const flash = changed.has(k);
              return (
                <li
                  key={it.id}
                  className={cn('flex min-h-[88px] flex-col rounded-md border p-2.5 transition-shadow duration-150', tile.cls, flash && 'ring-2 ring-block/60')}
                  style={tile.style}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-2xs text-text-3">{it.id}</span>
                    <span className={cn('inline-flex items-center gap-1 text-[10.5px] font-medium', tile.text)}>
                      <span className={cn('size-1.5 rounded-full', tile.dot)} />
                      {tile.label}
                    </span>
                  </div>
                  <div className={cn('mt-1 text-xs font-medium leading-4', it.status === 'uncovered' ? 'text-text-3' : 'text-text-1')}>{it.name}</div>
                  {it.controls.length ? (
                    <div className="mt-auto flex flex-wrap gap-1 pt-2">
                      {it.controls.map((c) => (
                        <ControlChip key={c} id={c} href={`/security/coverage?tab=controls&control=${encodeURIComponent(c)}`} />
                      ))}
                    </div>
                  ) : (
                    <div className="mt-auto pt-2 text-2xs text-text-4">No mapped control</div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

const MODE_CLS: Record<string, string> = {
  enforce: 'text-allow border-allow/30 bg-allow/10',
  monitor: 'text-redact border-redact/30 bg-redact/10',
  off: 'text-text-3 border-border bg-surface-2',
};
const TH = 'whitespace-nowrap px-2 py-2 text-left text-2xs font-medium uppercase tracking-[0.06em] text-text-3';
const TD = 'whitespace-nowrap px-2 py-1.5 max-md:py-2.5';

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
    const t = setTimeout(() => document.getElementById(`ctl-${highlight}`)?.scrollIntoView({ block: 'center' }), 200);
    return () => clearTimeout(t);
  }, [highlight, items.length]);
  const filtered = Boolean(family || mode || q);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-4 py-2.5">
        <label className="flex h-8 min-w-0 flex-1 items-center rounded-md border border-border bg-surface-1 px-2.5 focus-within:border-accent-fg/60 sm:max-w-[280px] max-md:h-9 max-md:basis-full">
          <Search className="size-3.5 shrink-0 text-text-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search id, name, OWASP id"
            aria-label="Search controls"
            className="ml-2 w-full min-w-0 bg-transparent text-xs text-text-1 outline-none placeholder:text-text-4"
          />
        </label>
        <MiniSelect label="Family" value={family} onChange={setFamily} className="max-md:h-9" options={families.map((f) => ({ value: f, label: f }))} />
        <MiniSelect label="Mode" value={mode} onChange={setMode} className="max-md:h-9" options={['enforce', 'monitor', 'off', 'disabled'].map((m) => ({ value: m, label: m }))} />
        <span className="font-mono text-xs tabular text-text-3">
          {rows.length}/{items.length}
        </span>
        <Link to="/governance/policy" className="ml-auto inline-flex h-8 items-center text-xs text-accent-fg hover:underline max-md:h-9">
          Edit in policy →
        </Link>
      </div>
      {rows.length === 0 ? (
        <EmptyState
          icon="SearchX"
          title={filtered ? 'No controls match these filters' : 'No controls in the catalog'}
          action={
            filtered ? (
              <button
                type="button"
                onClick={() => {
                  setQ('');
                  setFamily('');
                  setMode('');
                }}
                className="h-8 rounded-md border border-border px-3 text-xs text-text-2 hover:border-border-strong hover:text-text-1"
              >
                Clear filters
              </button>
            ) : undefined
          }
        />
      ) : (
        <div className="max-h-[620px] overflow-auto overscroll-contain">
          <table className="w-full min-w-[1040px] text-xs">
            <thead className="sticky top-0 z-[1] bg-surface-1">
              <tr className="border-b border-border">
                <th className={cn(TH, 'pl-4')}>Control</th>
                <th className={TH}>Kind</th>
                <th className={TH}>Mode</th>
                <th className={TH}>Action</th>
                <th className={cn(TH, 'text-right')}>Threshold</th>
                <th className={TH}>OWASP</th>
                <th className={TH}>Surfaces</th>
                <th className={cn(TH, 'text-right')}>Hits 24 h</th>
                <th className={cn(TH, 'text-right')}>Blocks 24 h</th>
                <th className={cn(TH, 'pr-4 text-right')}>p95</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr
                  key={c.id}
                  id={`ctl-${c.id}`}
                  className={cn(
                    'border-b border-border-subtle hover:bg-surface-2/50',
                    !c.enabled && 'opacity-60',
                    highlight === c.id && 'bg-accent-fg/10 shadow-[inset_2px_0_0_var(--accent-fg)]',
                  )}
                >
                  <td className={cn(TD, 'max-w-[340px] pl-4')}>
                    <div className="flex items-center gap-2">
                      <ControlChip id={c.id} kind={c.kind} name={c.name} owner={c.owner} />
                      <span className="truncate text-text-1" title={c.name}>
                        {c.name}
                      </span>
                      {!c.implemented ? <span className="rounded-[4px] border border-dashed border-border-strong px-1.5 text-[10.5px] text-text-3">planned</span> : null}
                    </div>
                  </td>
                  <td className={TD}>
                    <span className="inline-flex items-center gap-1.5 text-text-2">
                      <span className="size-1.5 rounded-full" style={{ background: KIND_COLORS[c.kind] ?? '#64748B' }} />
                      {c.kind}
                    </span>
                  </td>
                  <td className={TD}>
                    <span className={cn('inline-flex h-5 items-center rounded-[4px] border px-1.5 text-2xs font-medium', c.enabled ? (MODE_CLS[c.mode] ?? MODE_CLS.off) : 'border-block/30 bg-block/10 text-block')}>
                      {c.enabled ? c.mode : 'disabled'}
                    </span>
                  </td>
                  <td className={TD}>
                    <ActionBadge action={c.action} size="sm" />
                  </td>
                  <td className={cn(TD, 'text-right font-mono tabular text-text-2')}>{c.threshold ?? '—'}</td>
                  <td className={cn(TD, 'font-mono text-2xs text-text-3')} title={c.owasp.join(' ')}>
                    {c.owasp.slice(0, 2).join(' ')}
                    {c.owasp.length > 2 ? <span className="text-text-4"> +{c.owasp.length - 2}</span> : null}
                  </td>
                  <td className={TD}>
                    <div className="flex max-w-[200px] flex-wrap gap-1">
                      {c.surfaces.slice(0, 2).map((s) => (
                        <SurfaceTag key={s} surface={s} />
                      ))}
                      {c.surfaces.length > 2 ? <span className="text-2xs text-text-3" title={c.surfaces.join(', ')}>+{c.surfaces.length - 2}</span> : null}
                    </div>
                  </td>
                  <td className={cn(TD, 'text-right font-mono tabular')}>{fmtNum(c.hits_24h)}</td>
                  <td className={cn(TD, 'text-right font-mono tabular', c.blocks_24h ? 'text-block' : 'text-text-3')}>{fmtNum(c.blocks_24h)}</td>
                  <td className={cn(TD, 'pr-4 text-right font-mono tabular text-text-2')}>{c.p95_ms !== null ? fmtMs(c.p95_ms) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
