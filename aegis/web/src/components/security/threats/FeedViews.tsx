// Threat-feed views (prototype view-feed.js): rejected banner, status strip with serial flip, update-pipeline
// steps, signature table (new-row glow, ?sig= highlight), signature hits, feed timeline.
import { differenceInSeconds } from 'date-fns';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { Check, CircleDashed, KeyRound, Search, ShieldAlert, SkipForward, X } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import type { DecisionSummary, FeedSignatureView, FeedStatus } from '@/api/types';
import { ActionBadge, TimeAgo, useNow } from '@/components/shell';
import { fmtTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import { SeverityBadge, SurfaceTag } from '../common/atoms';
import type { FeedStep } from '../types';

export interface RejectInfo {
  reason: string;
  serial_attempted: number | null;
  kept_serial: number | null;
  at: number;
}

export function FeedBanner({ info, onDismiss }: { info: RejectInfo; onDismiss: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="relative flex items-start gap-3 overflow-hidden rounded-xl border border-block/40 bg-block/10 px-4 py-3"
    >
      <span className="absolute inset-y-0 left-0 w-1 bg-block" />
      <ShieldAlert className="mt-0.5 size-5 shrink-0 text-block" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-text-1">
          Feed bundle {info.serial_attempted !== null ? `#${info.serial_attempted} ` : ''}rejected — still enforcing #{info.kept_serial ?? '—'}
        </div>
        <div className="mt-0.5 break-words font-mono text-xs text-block">{info.reason}</div>
        <div className="mt-1 text-xs text-text-3">Nothing was applied. A tampered or unsigned bundle can never replace the active signatures.</div>
      </div>
      <button type="button" onClick={onDismiss} className="text-text-3 hover:text-text-1" aria-label="Dismiss">
        <X className="size-4" />
      </button>
    </motion.div>
  );
}

function Cell({ label, children, sub }: { label: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card px-4 py-3 shadow-card">
      <div className="text-2xs uppercase tracking-[0.08em] text-text-3">{label}</div>
      <div className="mt-1 min-w-0 text-lg font-semibold text-text-1">{children}</div>
      {sub ? <div className="mt-0.5 truncate text-xs text-text-3">{sub}</div> : null}
    </div>
  );
}

function Countdown({ to }: { to: string | null }) {
  const now = useNow();
  if (!to) return <span>—</span>;
  const s = differenceInSeconds(new Date(to), new Date(Math.max(now, Date.now())));
  if (s <= 0) return <span className="text-block">expired</span>;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return <span className={cn('tabular', s < 3600 && 'text-redact')}>{h > 0 ? `${h}h ${m}m` : `${m}m ${s % 60}s`}</span>;
}

export function SerialFlip({ serial }: { serial: number | null }) {
  const reduce = useReducedMotion();
  return (
    <span className="relative inline-flex h-7 overflow-hidden align-bottom [perspective:400px]">
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={serial ?? 'none'}
          initial={reduce ? false : { rotateX: -90, opacity: 0 }}
          animate={{ rotateX: 0, opacity: 1 }}
          exit={{ rotateX: 90, opacity: 0 }}
          transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
          className="inline-block font-mono"
        >
          #{serial ?? '—'}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

export function FeedStatusStrip({ status, rejected }: { status: FeedStatus; rejected: boolean }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <Cell label="Active serial" sub={status.version ?? '—'}>
        <span className="inline-flex items-center gap-2">
          <SerialFlip serial={status.serial} />
          <span className={cn('rounded-full border px-1.5 text-2xs font-medium', rejected ? 'border-block/30 bg-block/10 text-block' : status.status === 'ok' ? 'border-allow/30 bg-allow/10 text-allow' : 'border-redact/30 bg-redact/10 text-redact')}>
            {rejected ? 'kept' : status.status}
          </span>
        </span>
      </Cell>
      <Cell label="Signature verified" sub={<span className="font-mono">ed25519 · key {status.key_id ?? '—'}</span>}>
        <span className="inline-flex items-center gap-1.5 text-base">
          <KeyRound className="size-4 text-allow" /> pinned key
        </span>
      </Cell>
      <Cell label="Last update" sub={status.last_check ? <>checked <TimeAgo ts={status.last_check} /></> : undefined}>
        {status.last_update ? <TimeAgo ts={status.last_update} className="text-text-1" /> : '—'}
      </Cell>
      <Cell label="Expires in" sub={status.expires ? fmtTime(status.expires) : undefined}>
        <Countdown to={status.expires} />
      </Cell>
      <Cell label="Signatures" sub={`${status.signatures_monitor} monitor · ${status.signatures_quarantined} quarantined`}>
        <span className="tabular">
          {status.signatures_active}
          <span className="text-sm font-normal text-text-3"> active / {status.signatures_total}</span>
        </span>
      </Cell>
    </div>
  );
}

export function FeedUpdateSteps({ steps }: { steps: FeedStep[] }) {
  return (
    <ol className="space-y-1">
      {steps.map((s, i) => {
        const Icon = s.state === 'ok' ? Check : s.state === 'fail' ? X : s.state === 'skipped' ? SkipForward : CircleDashed;
        return (
          <motion.li
            key={s.key}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.06 }}
            className={cn(
              'flex items-start gap-3 rounded-lg border px-3 py-2',
              s.state === 'fail' ? 'border-block/40 bg-block/10' : s.state === 'skipped' ? 'border-border-subtle opacity-55' : 'border-border-subtle bg-surface-1',
            )}
          >
            <span
              className={cn(
                'mt-0.5 grid size-5 shrink-0 place-items-center rounded-full',
                s.state === 'ok' ? 'bg-allow/15 text-allow' : s.state === 'fail' ? 'bg-block/20 text-block' : 'bg-surface-3 text-text-3',
              )}
            >
              <Icon className="size-3" />
            </span>
            <div className="min-w-0">
              <div className={cn('text-xs font-medium', s.state === 'skipped' ? 'text-text-3 line-through' : 'text-text-1')}>
                {i + 1}. {s.label}
              </div>
              {s.detail ? <div className={cn('mt-0.5 break-words font-mono text-2xs', s.state === 'fail' ? 'text-block' : 'text-text-3')}>{s.detail}</div> : null}
            </div>
          </motion.li>
        );
      })}
    </ol>
  );
}

const STATUS_LABEL: Record<FeedSignatureView['status'], { label: string; cls: string }> = {
  stable: { label: 'active', cls: 'text-allow border-allow/30 bg-allow/10' },
  test: { label: 'test', cls: 'text-text-2 border-border bg-surface-2' },
  experimental: { label: 'monitor', cls: 'text-sky-300 border-sky-400/30 bg-sky-400/10' },
  deprecated: { label: 'deprecated', cls: 'text-text-3 border-border bg-surface-2' },
  withdrawn: { label: 'withdrawn', cls: 'text-text-3 border-border bg-surface-2 line-through' },
  quarantined: { label: 'quarantined', cls: 'text-block border-block/30 bg-block/10' },
};

export function SignatureTable({ items, newIds, highlight }: { items: FeedSignatureView[]; newIds: Set<string>; highlight: string | null }) {
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const maxHits = Math.max(1, ...items.map((s) => s.hits_24h));
  const rows = useMemo(
    () =>
      items.filter((s) => {
        if (status && s.status !== status) return false;
        if (!q) return true;
        const hay = `${s.id} ${s.title} ${s.aliases.join(' ')} ${s.tags.join(' ')}`.toLowerCase();
        return hay.includes(q.toLowerCase());
      }),
    [items, q, status],
  );
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-4 py-2.5">
        <label className="flex h-8 min-w-[220px] items-center rounded-md border border-border bg-surface-1 px-2.5">
          <Search className="size-3.5 text-text-3" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search id, title, CVE…" className="ml-2 w-full bg-transparent text-xs outline-none placeholder:text-text-4" />
        </label>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 rounded-md border border-border bg-surface-1 px-2 text-xs text-text-2 outline-none" aria-label="Status">
          <option value="">all statuses</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v.label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-text-3">{rows.length} signatures</span>
      </div>
      <div className="max-h-[520px] overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-[1] bg-surface-1/95 backdrop-blur">
            <tr className="border-b border-border text-left text-2xs uppercase tracking-[0.08em] text-text-3">
              <th className="px-4 py-2 font-medium">Signature</th>
              <th className="px-2 py-2 font-medium">Severity</th>
              <th className="px-2 py-2 font-medium">Surfaces</th>
              <th className="px-2 py-2 font-medium">Action</th>
              <th className="px-2 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Hits 24h</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const st = STATUS_LABEL[s.status] ?? STATUS_LABEL.stable;
              const isNew = newIds.has(s.id);
              const hl = highlight === s.id;
              return (
                <tr
                  key={s.id}
                  id={`sig-${s.id}`}
                  className={cn('border-b border-border-subtle align-top transition-colors', isNew && 'animate-row-in bg-allow/5', hl && 'bg-brand/10 shadow-[inset_2px_0_0_var(--accent-fg)]')}
                >
                  <td className="max-w-[420px] px-4 py-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11.5px] font-medium text-text-1">{s.id}</span>
                      {isNew ? <span className="rounded-full bg-allow/15 px-1.5 text-[10px] font-medium text-allow">new</span> : null}
                    </div>
                    <div className="mt-0.5 text-text-2">{s.title}</div>
                    {s.aliases.length ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {s.aliases.map((a) => (
                          <span key={a} className="rounded-[4px] border border-border bg-surface-2 px-1 font-mono text-[10px] text-text-3">
                            {a}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-2 py-2">
                    <SeverityBadge severity={s.severity} />
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex max-w-[200px] flex-wrap gap-1">
                      {s.surfaces.slice(0, 3).map((x) => (
                        <SurfaceTag key={x} surface={x} />
                      ))}
                      {s.surfaces.length > 3 ? <span className="text-2xs text-text-3">+{s.surfaces.length - 3}</span> : null}
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <ActionBadge action={s.action} size="sm" />
                  </td>
                  <td className="px-2 py-2">
                    <span className={cn('inline-flex h-5 items-center rounded-full border px-2 text-2xs font-medium', st.cls)}>{st.label}</span>
                  </td>
                  <td className="w-[150px] px-4 py-2">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 flex-1 rounded-full bg-surface-3">
                        <div className="h-full rounded-full bg-block/70" style={{ width: `${(s.hits_24h / maxHits) * 100}%` }} />
                      </div>
                      <span className="w-7 text-right font-mono tabular text-text-2">{s.hits_24h}</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function SignatureHits({ hits, onOpen }: { hits: DecisionSummary[]; onOpen: (d: DecisionSummary) => void }) {
  if (!hits.length) return <div className="px-4 py-8 text-center text-xs text-text-3">No signature hits yet.</div>;
  return (
    <ul className="divide-y divide-border-subtle">
      {hits.slice(0, 20).map((d) => {
        const sig = (d.controls ?? []).find((c) => c.control_id.startsWith('SIG-'));
        return (
          <li key={d.id}>
            <button type="button" onClick={() => onOpen(d)} className="flex w-full items-center gap-2.5 px-4 py-2 text-left text-xs hover:bg-surface-2/70">
              <ActionBadge action={d.action} size="sm" />
              <span className="font-mono text-text-2">{sig?.control_id ?? d.control_id}</span>
              <span className="min-w-0 flex-1 truncate text-text-2" title={d.reason}>
                {d.reason}
              </span>
              <span className="shrink-0 text-text-3">
                <TimeAgo ts={d.ts} short />
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export interface TimelineEvent {
  key: string;
  at: string | number;
  kind: 'applied' | 'rejected';
  title: string;
  detail: string;
}

export function FeedTimeline({ events }: { events: TimelineEvent[] }) {
  if (!events.length) return <div className="px-4 py-6 text-center text-xs text-text-3">No feed events yet.</div>;
  return (
    <ol className="relative ml-2 space-y-3 border-l border-border pl-4">
      {events.map((e) => (
        <li key={e.key} className="relative">
          <span className={cn('absolute -left-[21px] top-1 size-2.5 rounded-full ring-4 ring-card', e.kind === 'applied' ? 'bg-allow' : 'bg-block')} />
          <div className="flex items-center gap-2 text-xs">
            <span className={cn('font-medium', e.kind === 'rejected' ? 'text-block' : 'text-text-1')}>{e.title}</span>
            <span className="text-text-3">
              <TimeAgo ts={e.at} />
            </span>
          </div>
          <div className="mt-0.5 break-words font-mono text-2xs text-text-3">{e.detail}</div>
        </li>
      ))}
    </ol>
  );
}
