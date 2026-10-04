// Audit views: chain-integrity card (verify walk), chain head blocks, hash-chained event table, export dialog.
import { ChevronRight, Download, ShieldCheck, ShieldX, Link2 } from '@/components/icons';
import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { api, isApiRequestError } from '@/api/client';
import type { Action, AuditEvent, AuditVerifyResult } from '@/api/types';
import { ActionBadge, EmptyState, IdentityChip, JsonView, MockBadge, RoleGate } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { fmtAgo, fmtDateTime, fmtNum, fmtTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import { ControlChip, CopyButton, HashText, LockedAction, shortHash } from '../common/atoms';
import { MiniSelect } from '../live/FeedFilters';

const TH = 'whitespace-nowrap px-2 py-2 text-left text-2xs font-medium uppercase tracking-[0.06em] text-text-3';
const TD = 'whitespace-nowrap px-2 py-1.5 align-middle max-md:py-2.5';

// ------------------------------------------------------------------ verify
type VerifyState = { phase: 'idle' | 'running' | 'done'; result: AuditVerifyResult | null; mock: boolean; error: string | null };

function Stat({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn('min-w-0', className)}>
      <dt className="text-2xs text-text-3">{label}</dt>
      <dd className="mt-0.5 truncate font-mono text-[13px] tabular text-text-1">{children}</dd>
    </div>
  );
}

/**
 * Chain integrity: shows the last known verification (`last`, from GET /api/audit/verify) until the user
 * runs "Verify chain", which re-walks the chain server-side and replaces it.
 */
export function ChainVerifyCard({
  verify,
  last,
  isMock,
}: {
  verify: () => Promise<{ data: AuditVerifyResult; isMock: boolean }>;
  last?: AuditVerifyResult;
  isMock?: boolean;
}) {
  const [state, setState] = useState<VerifyState>({ phase: 'idle', result: null, mock: false, error: null });
  const run = async () => {
    setState({ phase: 'running', result: null, mock: false, error: null });
    const started = Date.now();
    try {
      const r = await verify();
      // keep the walk visible for a beat so the re-check registers on screen
      const wait = Math.max(0, 600 - (Date.now() - started));
      setTimeout(() => setState({ phase: 'done', result: r.data, mock: r.isMock, error: null }), wait);
    } catch (e) {
      setState({ phase: 'done', result: null, mock: false, error: isApiRequestError(e) ? e.message : 'Verification request failed' });
    }
  };
  const r = state.phase === 'running' ? null : (state.result ?? last ?? null);
  const fresh = state.phase === 'done' && state.result !== null;
  const status = state.phase === 'running' ? 'running' : !r ? 'unknown' : r.ok ? 'ok' : 'broken';
  const Icon = status === 'ok' ? ShieldCheck : status === 'broken' ? ShieldX : Link2;
  return (
    <section className="rounded-lg border border-border bg-card shadow-card" aria-live="polite">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-3.5">
        <Icon className={cn('size-4 shrink-0', status === 'ok' ? 'text-allow' : status === 'broken' ? 'text-block' : 'text-text-3')} />
        <div className="min-w-0 flex-1">
          <h2 className="text-[13px] font-[550] leading-[18px] text-text-1">Chain integrity</h2>
          <p className="text-xs leading-4 text-text-3">Each record stores sha256(prev_hash ‖ record); editing any line breaks every hash after it.</p>
        </div>
        {state.mock || isMock ? <MockBadge /> : null}
        <Button size="sm" onClick={() => void run()} disabled={state.phase === 'running'} className="max-md:h-9">
          <ShieldCheck /> {state.phase === 'running' ? 'Verifying…' : 'Verify chain'}
        </Button>
      </header>
      <div className="mx-4 mt-3 h-1 overflow-hidden rounded-full bg-surface-3">
        <div
          className={cn(
            'h-full rounded-full transition-[width] ease-linear',
            status === 'broken' ? 'bg-block' : status === 'ok' ? 'bg-allow' : status === 'running' ? 'bg-accent-fg' : 'bg-transparent',
            state.phase === 'running' ? 'duration-500' : 'duration-150',
          )}
          style={{
            width:
              status === 'running' ? '85%' : status === 'broken' && r?.records ? `${Math.max(4, ((r.broken_at_seq ?? 0) / r.records) * 100)}%` : status === 'ok' ? '100%' : '0%',
          }}
        />
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 pb-4 pt-3 sm:grid-cols-3 lg:grid-cols-5">
        <Stat label="Status">
          {status === 'running' ? (
            <span className="text-text-2">verifying…</span>
          ) : status === 'ok' ? (
            <span className="font-sans font-medium text-allow">Intact</span>
          ) : status === 'broken' ? (
            <span className="font-sans font-medium text-block">Broken at seq {r?.broken_at_seq ?? '—'}</span>
          ) : (
            <span className="font-sans text-text-3">Not verified</span>
          )}
        </Stat>
        <Stat label="Records">{r ? fmtNum(r.records) : '—'}</Stat>
        <Stat label="Files">{r ? fmtNum(r.files) : '—'}</Stat>
        <Stat label="Head hash">
          {r ? (
            <span className="inline-flex items-center gap-0.5" title={r.head_hash}>
              {shortHash(r.head_hash, 6)}
              <CopyButton value={r.head_hash} label="head hash" />
            </span>
          ) : (
            '—'
          )}
        </Stat>
        <Stat label={fresh ? 'Verified' : 'Last verified'} className="col-span-2 sm:col-span-1">
          {r ? (
            <span title={fmtDateTime(r.checked_at)}>
              {fmtTime(r.checked_at, { seconds: true })} <span className="font-sans text-text-3">· {fmtAgo(r.checked_at)}</span>
            </span>
          ) : (
            '—'
          )}
        </Stat>
      </dl>
      {r?.message || state.error ? (
        <div className={cn('border-t border-border-subtle px-4 py-2 text-xs', state.error || (r && !r.ok) ? 'text-block' : 'text-text-3')}>{state.error ?? r?.message}</div>
      ) : null}
    </section>
  );
}

// ------------------------------------------------------------------ chain blocks
export function ChainBlocks({ events, brokenAt }: { events: AuditEvent[]; brokenAt: number | null }) {
  const last = useMemo(() => [...events].sort((a, b) => a.seq - b.seq).slice(-8), [events]);
  if (!last.length) return null;
  return (
    <ol className="-mx-4 flex items-stretch overflow-x-auto px-4 pb-1" aria-label="Most recent chain records">
      {last.map((e, i) => {
        const broken = brokenAt !== null && e.seq === brokenAt;
        return (
          <Fragment key={e.seq}>
            {i > 0 ? (
              <li aria-hidden className="flex shrink-0 items-center px-0.5">
                <span className={cn('h-px w-3', broken ? 'bg-block' : 'bg-border-strong')} />
                <ChevronRight className={cn('-ml-1 size-3', broken ? 'text-block' : 'text-text-4')} />
              </li>
            ) : null}
            <li className={cn('w-[124px] shrink-0 rounded-md border px-2.5 py-2', broken ? 'border-block/50 bg-block/10' : 'border-border bg-surface-1')}>
              <div className="flex items-center justify-between gap-1 font-mono text-2xs tabular">
                <span className="text-text-1">#{e.seq}</span>
                {e.action ? <ActionBadge action={e.action} size="sm" /> : null}
              </div>
              <div className="mt-1 truncate font-mono text-2xs text-text-2" title={e.event_type}>
                {e.event_type}
              </div>
              <div className="mt-1.5 font-mono text-[10px] leading-[14px] text-text-4" title={e.prev_hash}>
                prev {shortHash(e.prev_hash, 3)}
              </div>
              <div className={cn('font-mono text-[10px] leading-[14px]', broken ? 'text-block' : 'text-text-2')} title={e.hash}>
                hash {shortHash(e.hash, 3)}
              </div>
            </li>
          </Fragment>
        );
      })}
    </ol>
  );
}

// ------------------------------------------------------------------ table
export function AuditTable({ events, highlightSeq, onOpenDecision }: { events: AuditEvent[]; highlightSeq: number | null; onOpenDecision: (id: string) => void }) {
  const [type, setType] = useState('');
  const [open, setOpen] = useState<number | null>(highlightSeq);
  const types = useMemo(() => [...new Set(events.map((e) => e.event_type))].sort(), [events]);
  const rows = useMemo(() => (type ? events.filter((e) => e.event_type === type) : events), [events, type]);
  useEffect(() => {
    if (highlightSeq === null) return;
    const t = setTimeout(() => document.getElementById(`seq-${highlightSeq}`)?.scrollIntoView({ block: 'center' }), 250);
    return () => clearTimeout(t);
  }, [highlightSeq, events.length]);
  const seqs = rows.length ? [rows[rows.length - 1].seq, rows[0].seq].sort((a, b) => a - b) : null;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-4 py-2.5">
        <MiniSelect label="Event" value={type} onChange={setType} options={types.map((t) => ({ value: t, label: t }))} className="max-md:h-9" />
        {type ? (
          <button type="button" onClick={() => setType('')} className="h-8 rounded-md px-2 text-xs text-text-3 hover:text-text-1 max-md:h-9">
            Clear
          </button>
        ) : null}
        <span className="ml-auto font-mono text-xs tabular text-text-3">
          {fmtNum(rows.length)} records{seqs ? ` · seq ${seqs[0]}–${seqs[1]}` : ''}
        </span>
      </div>
      {rows.length === 0 ? (
        <EmptyState
          icon="ScrollText"
          title={events.length ? 'No records match this filter' : 'No audit records yet'}
          hint={events.length ? 'Clear the event filter to see the full chain.' : 'Decisions, policy changes, feed updates and approvals are appended here as they happen.'}
        />
      ) : (
        <div className="max-h-[560px] overflow-auto overscroll-contain">
          <table className="w-full min-w-[920px] text-xs">
            <thead className="sticky top-0 z-[1] bg-surface-1">
              <tr className="border-b border-border">
                <th className={cn(TH, 'pl-4')}>Seq</th>
                <th className={TH}>Time</th>
                <th className={TH}>Event</th>
                <th className={TH}>Actor</th>
                <th className={TH}>Action</th>
                <th className={TH}>Control</th>
                <th className={TH}>Decision</th>
                <th className={TH}>Policy · feed</th>
                <th className={cn(TH, 'pr-4')}>Hash</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => {
                const isOpen = open === e.seq;
                return (
                  <Fragment key={e.seq}>
                    <tr
                      id={`seq-${e.seq}`}
                      onClick={() => setOpen((o) => (o === e.seq ? null : e.seq))}
                      aria-expanded={isOpen}
                      className={cn(
                        'cursor-pointer border-b border-border-subtle hover:bg-surface-2/60',
                        isOpen && 'bg-surface-2/40',
                        highlightSeq === e.seq && 'bg-accent-fg/10 shadow-[inset_2px_0_0_var(--accent-fg)]',
                      )}
                    >
                      <td className={cn(TD, 'pl-4 font-mono tabular text-text-1')}>
                        <ChevronRight className={cn('mr-1 inline size-3 text-text-4 transition-transform duration-150', isOpen && 'rotate-90')} />
                        {e.seq}
                      </td>
                      <td className={cn(TD, 'font-mono tabular text-text-3')} title={fmtDateTime(e.ts)}>
                        {fmtTime(e.ts, { seconds: true })}
                      </td>
                      <td className={TD}>
                        <span className="rounded-[4px] border border-border bg-surface-2 px-1.5 py-px font-mono text-2xs text-text-2">{e.event_type}</span>
                      </td>
                      <td className={cn(TD, 'max-w-[180px] truncate')}>{e.actor ? <IdentityChip identity={e.actor} /> : <span className="text-text-4">system</span>}</td>
                      <td className={TD}>{e.action ? <ActionBadge action={e.action as Action} size="sm" /> : <span className="text-text-4">—</span>}</td>
                      <td className={TD}>{e.control_id ? <ControlChip id={e.control_id} /> : <span className="text-text-4">—</span>}</td>
                      <td className={TD}>
                        {e.decision_id ? (
                          <button
                            type="button"
                            className="font-mono text-2xs text-accent-fg hover:underline"
                            title={e.decision_id}
                            onClick={(ev) => {
                              ev.stopPropagation();
                              onOpenDecision(e.decision_id as string);
                            }}
                          >
                            {e.decision_id.slice(0, 14)}…
                          </button>
                        ) : (
                          <span className="text-text-4">—</span>
                        )}
                      </td>
                      <td className={cn(TD, 'font-mono text-2xs tabular text-text-3')}>
                        v{e.policy_version ?? '—'} · #{e.feed_serial ?? '—'}
                      </td>
                      <td className={cn(TD, 'pr-4')}>
                        <HashText hash={e.hash} copy={false} />
                      </td>
                    </tr>
                    {isOpen ? (
                      <tr className="border-b border-border-subtle bg-background/60">
                        <td colSpan={9} className="px-4 py-3">
                          <dl className="mb-2 grid gap-1 font-mono text-2xs text-text-3 md:max-w-[880px]">
                            <div className="flex gap-2">
                              <dt className="w-16 shrink-0">prev_hash</dt>
                              <dd className="break-all text-text-2">{e.prev_hash}</dd>
                            </div>
                            <div className="flex gap-2">
                              <dt className="w-16 shrink-0">hash</dt>
                              <dd className="break-all text-text-2">{e.hash}</dd>
                            </div>
                          </dl>
                          <JsonView value={e} collapsed={1} maxHeight={280} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ export
const FORMATS = [
  { id: 'jsonl', label: 'JSONL', ext: 'jsonl', hint: 'One aegis.audit/1 record per line, hashes included' },
  { id: 'csv', label: 'CSV', ext: 'csv', hint: 'Flat columns for spreadsheets' },
  { id: 'ocsf', label: 'OCSF', ext: 'json', hint: 'OCSF 1.9 · Detection Finding 2004, API Activity 6003' },
] as const;

function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

const FIELD = 'h-9 w-full min-w-0 rounded-md border border-border bg-background px-2 font-mono text-xs tabular text-text-1 [color-scheme:dark]';

export function ExportDialog({ open, onOpenChange, controls, agents }: { open: boolean; onOpenChange: (o: boolean) => void; controls: string[]; agents: string[] }) {
  const [format, setFormat] = useState<(typeof FORMATS)[number]['id']>('ocsf');
  const [from, setFrom] = useState(() => toLocalInput(new Date(Date.now() - 24 * 3600e3)));
  const [to, setTo] = useState(() => toLocalInput(new Date(Date.now() + 60e3)));
  const [action, setAction] = useState('');
  const [control, setControl] = useState('');
  const [agent, setAgent] = useState('');
  const [busy, setBusy] = useState(false);
  const rangeInvalid = Boolean(from && to && new Date(from) > new Date(to));
  const run = async () => {
    const f = FORMATS.find((x) => x.id === format) ?? FORMATS[0];
    const q = new URLSearchParams({ format });
    if (from) q.set('from', new Date(from).toISOString());
    if (to) q.set('to', new Date(to).toISOString());
    if (action) q.set('action', action);
    if (control) q.set('control_id', control);
    if (agent) q.set('agent_id', agent);
    const name = `aegis-audit-${new Date().toISOString().slice(0, 10)}.${f.ext}`;
    setBusy(true);
    try {
      await api.download(`/api/audit/export?${q.toString()}`, name);
      toast.success(`Exported ${f.label}: ${name}`);
      onOpenChange(false);
    } catch (e) {
      toast.error(isApiRequestError(e) ? e.message : 'Export failed');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-[540px]">
        <DialogHeader>
          <DialogTitle>Export audit log</DialogTitle>
          <DialogDescription>Evidence for auditors and SIEM ingestion. Every export is itself written to the audit log.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <fieldset>
            <legend className="mb-1.5 text-xs text-text-3">Format</legend>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3" role="radiogroup">
              {FORMATS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  role="radio"
                  aria-checked={format === f.id}
                  onClick={() => setFormat(f.id)}
                  className={cn(
                    'rounded-md border px-3 py-2 text-left transition-colors duration-150',
                    format === f.id ? 'border-accent-fg/70 bg-accent-fg/[.08]' : 'border-border hover:border-border-strong',
                  )}
                >
                  <div className="font-mono text-[13px] font-medium text-text-1">{f.label}</div>
                  <div className="mt-0.5 text-2xs leading-4 text-text-3">{f.hint}</div>
                </button>
              ))}
            </div>
          </fieldset>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex min-w-0 flex-col gap-1 text-xs text-text-3">
              From (local time)
              <input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} className={FIELD} />
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-xs text-text-3">
              To (local time)
              <input type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} className={FIELD} />
            </label>
          </div>
          {rangeInvalid ? <p className="-mt-2 text-xs text-block">The start time is after the end time.</p> : null}
          <div>
            <div className="mb-1.5 text-xs text-text-3">Filters (optional)</div>
            <div className="flex flex-wrap gap-2">
              <MiniSelect label="Action" value={action} onChange={setAction} className="max-md:h-9" options={(['block', 'require_approval', 'redact', 'log', 'allow'] as const).map((a) => ({ value: a, label: a }))} />
              <MiniSelect label="Control" value={control} onChange={setControl} className="max-md:h-9" options={controls.map((c) => ({ value: c, label: c }))} />
              <MiniSelect label="Agent" value={agent} onChange={setAgent} className="max-md:h-9" options={agents.map((c) => ({ value: c, label: c }))} />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => void run()} disabled={busy || rangeInvalid}>
            <Download /> {busy ? 'Exporting…' : `Export ${FORMATS.find((f) => f.id === format)?.label ?? ''}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ExportButton({ controls, agents }: { controls: string[]; agents: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <RoleGate min="admin" fallback={<LockedAction label="Export needs admin — switch View as" compact />}>
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)} className="max-md:h-9">
        <Download /> Export
      </Button>
      <ExportDialog open={open} onOpenChange={setOpen} controls={controls} agents={agents} />
    </RoleGate>
  );
}
