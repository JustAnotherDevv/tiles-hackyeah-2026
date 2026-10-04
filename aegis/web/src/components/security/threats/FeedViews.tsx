// Threat-feed views: feed health banner (rejected / unreachable / expired / disabled), status strip with serial
// change, update pipeline, signature table (new-row highlight, ?sig= deep link), signature hits, feed history.
import { differenceInSeconds } from 'date-fns';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { useMemo, useState, type ReactNode } from 'react';
import type { DecisionSummary, FeedSignatureView, FeedStatus, Severity } from '@/api/types';
import { Check, CircleDashed, CloudOff, ExternalLink, Info, Search, ShieldCheck, ShieldX, SkipForward, X, type LucideIcon } from '@/components/icons';
import { ActionBadge, TimeAgo, useNow } from '@/components/shell';
import { fmtTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import { SurfaceTag } from '../common/atoms';
import type { FeedStep } from '../types';

/** What the banner reports. `rejected` = a bundle failed verification; the others are availability states. */
export type FeedIssueKind = 'rejected' | 'unreachable' | 'stale' | 'disabled';

export interface RejectInfo {
  reason: string;
  serial_attempted: number | null;
  kept_serial: number | null;
  at: number;
  /** Feed server could not be reached (not a rejected bundle). Kept for callers that only set this flag. */
  unreachable?: boolean;
  kind?: FeedIssueKind;
}

export function issueKind(info: RejectInfo): FeedIssueKind {
  if (info.kind) return info.kind;
  if (info.unreachable || /^unreachable/i.test(info.reason)) return 'unreachable';
  return 'rejected';
}

const ISSUE: Record<FeedIssueKind, { icon: LucideIcon; box: string; fg: string; title: (i: RejectInfo) => string; body: string }> = {
  rejected: {
    icon: ShieldX,
    box: 'border-block/40 bg-block/[.07]',
    fg: 'text-block',
    title: (i) => `Bundle ${i.serial_attempted !== null ? `#${i.serial_attempted} ` : ''}rejected · still enforcing #${i.kept_serial ?? '—'}`,
    body: 'Nothing was applied. A bundle that fails verification never replaces the active signatures.',
  },
  unreachable: {
    icon: CloudOff,
    box: 'border-redact/40 bg-redact/[.07]',
    fg: 'text-redact',
    title: (i) => `Feed server unreachable · still enforcing #${i.kept_serial ?? '—'}`,
    body: 'No bundle was received, so nothing was verified or rejected. The last verified bundle stays active and the gateway keeps polling.',
  },
  stale: {
    icon: Info,
    box: 'border-redact/40 bg-redact/[.07]',
    fg: 'text-redact',
    title: (i) => `Active bundle #${i.kept_serial ?? '—'} has expired`,
    body: 'The publisher has not issued a newer bundle. The expired signatures remain enforced until one arrives.',
  },
  disabled: {
    icon: Info,
    box: 'border-border bg-surface-1',
    fg: 'text-text-2',
    title: () => 'Feed updates are disabled',
    body: 'The gateway enforces its bundled signatures only. Configure a feed URL and pinned public key to receive updates.',
  },
};

export function FeedBanner({ info, onDismiss }: { info: RejectInfo; onDismiss: () => void }) {
  const kind = issueKind(info);
  const c = ISSUE[kind];
  const Icon = c.icon;
  return (
    <div role={kind === 'rejected' ? 'alert' : 'status'} className={cn('flex items-start gap-3 rounded-lg border py-3 pl-4 pr-2', c.box)}>
      <Icon className={cn('mt-0.5 size-4 shrink-0', c.fg)} />
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold text-text-1">{c.title(info)}</div>
        {info.reason && kind !== 'disabled' ? <div className={cn('mt-0.5 break-words font-mono text-xs', c.fg)}>{info.reason}</div> : null}
        {kind === 'disabled' && info.reason ? <div className="mt-0.5 break-words font-mono text-xs text-text-3">{info.reason}</div> : null}
        <div className="mt-1 text-xs text-text-3">{c.body}</div>
      </div>
      <button type="button" onClick={onDismiss} className="grid size-9 shrink-0 place-items-center rounded-md text-text-3 hover:bg-surface-2 hover:text-text-1" aria-label="Dismiss">
        <X className="size-4" />
      </button>
    </div>
  );
}

function Cell({ label, children, sub, className }: { label: string; children: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={cn('min-w-0 bg-card px-4 py-3', className)}>
      <div className="text-xs text-text-3">{label}</div>
      <div className="mt-1 flex min-h-7 min-w-0 items-center text-lg font-semibold tracking-[-0.01em] text-text-1">{children}</div>
      {sub ? <div className="mt-0.5 truncate text-xs text-text-3">{sub}</div> : null}
    </div>
  );
}

function Countdown({ to }: { to: string | null }) {
  const now = useNow();
  if (!to) return <span>—</span>;
  const s = differenceInSeconds(new Date(to), new Date(now));
  if (s <= 0) return <span className="text-block">Expired</span>;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return <span className={cn('tabular', s < 3600 && 'text-redact')}>{h > 0 ? `${h}h ${m}m` : `${m}m ${s % 60}s`}</span>;
}

/** Serial number; swaps with a short fade when a new bundle is applied. */
export function SerialFlip({ serial }: { serial: number | null }) {
  const reduce = useReducedMotion();
  return (
    <span className="relative inline-flex overflow-hidden">
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={serial ?? 'none'}
          initial={reduce ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.15, ease: 'easeOut' }}
          className="inline-block font-mono tabular"
        >
          #{serial ?? '—'}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

const SERIAL_STATE: Record<string, { label: string; cls: string }> = {
  ok: { label: 'Current', cls: 'border-allow/30 bg-allow/10 text-allow' },
  seed: { label: 'Seed bundle', cls: 'border-border bg-surface-2 text-text-2' },
  stale: { label: 'Expired', cls: 'border-redact/30 bg-redact/10 text-redact' },
  rejected: { label: 'Last good', cls: 'border-redact/30 bg-redact/10 text-redact' },
  unreachable: { label: 'Last good', cls: 'border-redact/30 bg-redact/10 text-redact' },
  disabled: { label: 'Updates off', cls: 'border-border bg-surface-2 text-text-3' },
};

export function FeedStatusStrip({ status, issue }: { status: FeedStatus; issue: FeedIssueKind | null }) {
  const st = SERIAL_STATE[issue ?? status.status] ?? SERIAL_STATE.ok;
  const keyed = Boolean(status.key_id) && status.serial !== null;
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border shadow-card lg:grid-cols-5">
      <Cell label="Active serial" sub={<span className="font-mono">{status.version ?? '—'}</span>}>
        <span className="inline-flex items-center gap-2">
          <SerialFlip serial={status.serial} />
          <span className={cn('inline-flex h-5 items-center rounded-sm border px-1.5 text-2xs font-medium', st.cls)}>{st.label}</span>
        </span>
      </Cell>
      <Cell label="Signature" sub={<span className="font-mono">ed25519 · key {status.key_id ?? '—'}</span>}>
        {keyed ? (
          <span className="inline-flex items-center gap-1.5 text-base">
            <ShieldCheck className="size-4 text-allow" /> Verified
          </span>
        ) : (
          <span className="text-base text-text-3">No verified bundle</span>
        )}
      </Cell>
      <Cell label="Last update" sub={status.last_check ? <>Checked <TimeAgo ts={status.last_check} /></> : undefined}>
        {status.last_update ? <TimeAgo ts={status.last_update} className="text-text-1" /> : '—'}
      </Cell>
      <Cell label="Expires in" sub={status.expires ? fmtTime(status.expires) : undefined}>
        <Countdown to={status.expires} />
      </Cell>
      <Cell label="Signatures" className="col-span-2 lg:col-span-1" sub={`${status.signatures_monitor} monitor · ${status.signatures_quarantined} quarantined`}>
        <span className="tabular">
          {status.signatures_active}
          <span className="text-sm font-normal text-text-3"> active of {status.signatures_total}</span>
        </span>
      </Cell>
    </div>
  );
}

const STEP_ICON: Record<FeedStep['state'], LucideIcon> = { ok: Check, fail: X, skipped: SkipForward, pending: CircleDashed };

export function FeedUpdateSteps({ steps }: { steps: FeedStep[] }) {
  return (
    <ol className="divide-y divide-border-subtle">
      {steps.map((s, i) => {
        const Icon = STEP_ICON[s.state];
        return (
          <li key={s.key} className={cn('flex items-start gap-3 py-2', s.state === 'fail' && '-mx-2 rounded-md bg-block/[.07] px-2')}>
            <span
              className={cn(
                'mt-px grid size-4 shrink-0 place-items-center rounded-full',
                s.state === 'ok' ? 'bg-allow/15 text-allow' : s.state === 'fail' ? 'bg-block/20 text-block' : 'bg-surface-3 text-text-3',
              )}
            >
              <Icon className="size-2.5" weight="bold" />
            </span>
            <div className="min-w-0 flex-1">
              <div className={cn('text-xs', s.state === 'skipped' ? 'text-text-3' : s.state === 'fail' ? 'font-medium text-block' : 'text-text-1')}>
                <span className="mr-1.5 font-mono tabular text-text-4">{i + 1}</span>
                {s.label}
              </div>
              {s.detail ? <div className={cn('mt-0.5 break-words font-mono text-2xs', s.state === 'fail' ? 'text-block' : 'text-text-3')}>{s.detail}</div> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

const STATUS_LABEL: Record<FeedSignatureView['status'], { label: string; cls: string }> = {
  stable: { label: 'Active', cls: 'text-allow border-allow/30 bg-allow/10' },
  test: { label: 'Test', cls: 'text-text-2 border-border bg-surface-2' },
  experimental: { label: 'Monitor', cls: 'text-text-2 border-border bg-surface-2' },
  deprecated: { label: 'Deprecated', cls: 'text-text-3 border-border bg-surface-2' },
  withdrawn: { label: 'Withdrawn', cls: 'text-text-3 border-border bg-surface-2 line-through' },
  quarantined: { label: 'Quarantined', cls: 'text-block border-block/30 bg-block/10' },
};

const SEVERITY: Record<Severity, { label: string; dot: string }> = {
  critical: { label: 'Critical', dot: 'bg-block' },
  high: { label: 'High', dot: 'bg-block/60' },
  medium: { label: 'Medium', dot: 'bg-redact' },
  low: { label: 'Low', dot: 'bg-text-3' },
  info: { label: 'Info', dot: 'bg-text-4' },
};

function SeverityLabel({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity] ?? SEVERITY.info;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-text-2">
      <span className={cn('size-1.5 rounded-full', s.dot)} />
      {s.label}
    </span>
  );
}

/** CVE / GHSA ids link to their advisories; everything else is plain mono text. */
function AliasRef({ id }: { id: string }) {
  const href = /^CVE-\d{4}-\d+$/i.test(id)
    ? `https://nvd.nist.gov/vuln/detail/${id.toUpperCase()}`
    : /^GHSA-/i.test(id)
      ? `https://github.com/advisories/${id}`
      : null;
  const cls = 'inline-flex h-5 items-center gap-1 rounded-sm border border-border bg-surface-2 px-1.5 font-mono text-[10.5px] text-text-2';
  if (!href) return <span className={cls}>{id}</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer" className={cn(cls, 'hover:border-border-strong hover:text-text-1')} title={`Open ${id} advisory`}>
      {id}
      <ExternalLink className="size-2.5 text-text-4" />
    </a>
  );
}

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
      <div className="flex flex-wrap items-center gap-2 border-y border-border-subtle px-4 py-2.5">
        <label className="flex h-9 min-w-0 flex-1 items-center rounded-md border border-border bg-surface-1 px-2.5 focus-within:border-border-strong sm:h-8 sm:max-w-72">
          <Search className="size-3.5 shrink-0 text-text-3" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search id, title, CVE, tag" className="ml-2 w-full min-w-0 bg-transparent text-xs outline-none placeholder:text-text-4" aria-label="Search signatures" />
        </label>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="h-9 rounded-md border border-border bg-surface-1 px-2 text-xs text-text-2 outline-none sm:h-8" aria-label="Filter by status">
          <option value="">All statuses</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v.label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs tabular text-text-3">
          {rows.length === items.length ? `${items.length} signatures` : `${rows.length} of ${items.length}`}
        </span>
      </div>
      <div className="max-h-[560px] overflow-auto">
        <table className="w-full min-w-[720px] text-xs">
          <thead className="sticky top-0 z-[1] bg-card">
            <tr className="border-b border-border text-left text-2xs font-medium text-text-3">
              <th className="px-4 py-2 font-medium">Signature</th>
              <th className="px-2 py-2 font-medium">Severity</th>
              <th className="px-2 py-2 font-medium">Surfaces</th>
              <th className="px-2 py-2 font-medium">Action</th>
              <th className="px-2 py-2 font-medium">Status</th>
              <th className="px-4 py-2 text-right font-medium">Hits · 24 h</th>
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
                  className={cn('border-b border-border-subtle align-top', isNew && 'animate-row-in bg-allow/5', hl && 'bg-brand/10 shadow-[inset_2px_0_0_var(--accent-fg)]')}
                >
                  <td className="max-w-[440px] px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11.5px] font-medium text-text-1">{s.id}</span>
                      {isNew ? <span className="inline-flex h-4 items-center rounded-sm bg-allow/15 px-1 text-[10px] font-medium text-allow">New</span> : null}
                    </div>
                    <div className="mt-0.5 text-text-2">{s.title}</div>
                    {s.aliases.length || s.tags.length ? (
                      <div className="mt-1.5 flex flex-wrap items-center gap-1">
                        {s.aliases.map((a) => (
                          <AliasRef key={a} id={a} />
                        ))}
                        {s.tags.length ? <span className="font-mono text-[10.5px] text-text-4">{s.tags.join(' · ')}</span> : null}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-2 py-2.5">
                    <SeverityLabel severity={s.severity} />
                  </td>
                  <td className="px-2 py-2.5">
                    <div className="flex max-w-[200px] flex-wrap gap-1">
                      {s.surfaces.slice(0, 3).map((x) => (
                        <SurfaceTag key={x} surface={x} />
                      ))}
                      {s.surfaces.length > 3 ? (
                        <span className="inline-flex h-5 items-center text-2xs text-text-3" title={s.surfaces.slice(3).join(', ')}>
                          +{s.surfaces.length - 3}
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-2 py-2.5">
                    <ActionBadge action={s.action} size="sm" />
                  </td>
                  <td className="px-2 py-2.5">
                    <span className={cn('inline-flex h-5 items-center whitespace-nowrap rounded-sm border px-1.5 text-2xs font-medium', st.cls)}>{st.label}</span>
                  </td>
                  <td className="w-[140px] px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="h-1 flex-1 rounded-full bg-surface-3">
                        {s.hits_24h > 0 ? <div className="h-full rounded-full bg-text-3" style={{ width: `${Math.max(4, (s.hits_24h / maxHits) * 100)}%` }} /> : null}
                      </div>
                      <span className={cn('w-8 text-right font-mono tabular', s.hits_24h ? 'text-text-1' : 'text-text-4')}>{s.hits_24h}</span>
                    </div>
                  </td>
                </tr>
              );
            })}
            {!rows.length ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-xs text-text-3">
                  {items.length ? 'No signatures match the current filter.' : 'The active bundle contains no signatures.'}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function SignatureHits({ hits, onOpen }: { hits: DecisionSummary[]; onOpen: (d: DecisionSummary) => void }) {
  if (!hits.length) return <div className="px-4 py-8 text-center text-xs text-text-3">No signature matches in the last 24 h.</div>;
  return (
    <ul className="divide-y divide-border-subtle border-t border-border-subtle">
      {hits.slice(0, 20).map((d) => {
        const sig = (d.controls ?? []).find((c) => c.control_id.startsWith('SIG-'));
        return (
          <li key={d.id}>
            <button type="button" onClick={() => onOpen(d)} className="flex min-h-9 w-full items-center gap-2.5 px-4 py-2 text-left text-xs hover:bg-surface-2/70">
              <ActionBadge action={d.action} size="sm" />
              <span className="shrink-0 font-mono text-text-2">{sig?.control_id ?? d.control_id}</span>
              <span className="min-w-0 flex-1 truncate text-text-2" title={d.reason}>
                {d.reason}
              </span>
              <span className="shrink-0 tabular text-text-3">
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

const TIMELINE_INITIAL = 6;

export function FeedTimeline({ events }: { events: TimelineEvent[] }) {
  const [all, setAll] = useState(false);
  if (!events.length) return <div className="py-4 text-center text-xs text-text-3">No bundles applied yet.</div>;
  const shown = all ? events : events.slice(0, TIMELINE_INITIAL);
  return (
    <div>
      <ol className="relative ml-1 space-y-3 border-l border-border pl-4">
        {shown.map((e) => (
          <li key={e.key} className="relative">
            <span className={cn('absolute -left-[20.5px] top-[5px] size-2 rounded-full ring-4 ring-card', e.kind === 'applied' ? 'bg-allow' : 'bg-block')} />
            <div className="flex flex-wrap items-baseline gap-x-2 text-xs">
              <span className={cn('font-medium', e.kind === 'rejected' ? 'text-block' : 'text-text-1')}>{e.title}</span>
              <span className="text-text-3">
                <TimeAgo ts={e.at} />
              </span>
            </div>
            <div className="mt-0.5 break-words font-mono text-2xs text-text-3">{e.detail}</div>
          </li>
        ))}
      </ol>
      {events.length > TIMELINE_INITIAL ? (
        <button type="button" onClick={() => setAll((v) => !v)} className="mt-3 h-8 text-xs text-text-2 hover:text-text-1">
          {all ? 'Show fewer' : `Show all ${events.length}`}
        </button>
      ) : null}
    </div>
  );
}
