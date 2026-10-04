// Audit views: Verify-chain card (animated walk), chain blocks, hash-chained event table, export dialog.
import { motion, useReducedMotion } from 'framer-motion';
import { ChevronRight, Download, Link2, ShieldCheck, ShieldX } from 'lucide-react';
import { Fragment, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { api, isApiRequestError } from '@/api/client';
import type { Action, AuditEvent, AuditVerifyResult } from '@/api/types';
import { ActionBadge, IdentityChip, JsonView, RoleGate } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { fmtDateTime, fmtNum, fmtTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import { ControlChip, HashText, LockedAction, shortHash } from '../common/atoms';
import { MiniSelect } from '../live/FeedFilters';

// ------------------------------------------------------------------ verify
export function ChainVerifyCard({ verify, isMock }: { verify: () => Promise<{ data: AuditVerifyResult; isMock: boolean }>; isMock?: boolean }) {
  const reduce = useReducedMotion();
  const [state, setState] = useState<{ phase: 'idle' | 'running' | 'done'; result: AuditVerifyResult | null; mock: boolean; error: string | null }>({ phase: 'idle', result: null, mock: false, error: null });
  const run = async () => {
    setState({ phase: 'running', result: null, mock: false, error: null });
    const started = Date.now();
    try {
      const r = await verify();
      const wait = Math.max(0, (reduce ? 0 : 900) - (Date.now() - started));
      setTimeout(() => setState({ phase: 'done', result: r.data, mock: r.isMock, error: null }), wait);
    } catch (e) {
      setState({ phase: 'done', result: null, mock: false, error: isApiRequestError(e) ? e.message : 'verify failed' });
    }
  };
  const r = state.result;
  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-card p-4 shadow-card">
      <div className="flex flex-wrap items-center gap-3">
        <div className="grid size-10 place-items-center rounded-xl border border-border bg-surface-2">
          {r ? r.ok ? <ShieldCheck className="size-5 text-allow" /> : <ShieldX className="size-5 text-block" /> : <Link2 className="size-5 text-accent-fg" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-text-1">Hash-chained audit log</div>
          <div className="text-xs text-text-3">Every record carries sha256(prev_hash ‖ record). Editing any line breaks every hash after it.</div>
        </div>
        <Button onClick={() => void run()} disabled={state.phase === 'running'}>
          <ShieldCheck /> {state.phase === 'running' ? 'Verifying…' : 'Verify chain'}
        </Button>
      </div>
      {state.phase !== 'idle' ? (
        <div className="mt-4">
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
            <motion.div
              className={cn('h-full rounded-full', r && !r.ok ? 'bg-block' : 'bg-allow')}
              initial={{ width: '0%' }}
              animate={{ width: state.phase === 'running' ? '82%' : r && !r.ok && r.records ? `${Math.max(4, ((r.broken_at_seq ?? 0) / r.records) * 100)}%` : '100%' }}
              transition={{ duration: state.phase === 'running' ? 0.9 : 0.3, ease: [0.16, 1, 0.3, 1] }}
            />
          </div>
          {state.phase === 'done' && r ? (
            <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              {r.ok ? (
                <span className="text-base font-semibold text-allow">
                  Chain OK · {fmtNum(r.records)} records · {r.files} files · head <span className="font-mono">{shortHash(r.head_hash)}</span>
                </span>
              ) : (
                <span className="text-base font-semibold text-block">Broken at seq {r.broken_at_seq}</span>
              )}
              <span className="text-xs text-text-3">{r.message}</span>
              <span className="text-xs text-text-4">checked {fmtTime(r.checked_at, { seconds: true })}</span>
              {state.mock || isMock ? <span className="text-2xs text-text-4">(demo data)</span> : null}
            </motion.div>
          ) : null}
          {state.error ? <div className="mt-3 text-sm text-block">{state.error}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ chain blocks
export function ChainBlocks({ events, brokenAt }: { events: AuditEvent[]; brokenAt: number | null }) {
  const last = useMemo(() => [...events].sort((a, b) => a.seq - b.seq).slice(-8), [events]);
  if (!last.length) return null;
  return (
    <div className="flex items-stretch gap-0 overflow-x-auto pb-1">
      {last.map((e, i) => {
        const broken = brokenAt !== null && e.seq === brokenAt;
        return (
          <Fragment key={e.seq}>
            {i > 0 ? (
              <div className="flex shrink-0 items-center px-1">
                <span className={cn('h-px w-5', broken ? 'bg-block' : 'bg-border-strong')} />
                <ChevronRight className={cn('-ml-1.5 size-3', broken ? 'text-block' : 'text-text-4')} />
              </div>
            ) : null}
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className={cn('w-[132px] shrink-0 rounded-lg border px-2.5 py-2', broken ? 'border-block/50 bg-block/10' : 'border-border bg-surface-1')}
            >
              <div className="flex items-center justify-between font-mono text-2xs">
                <span className="text-text-1">#{e.seq}</span>
                {e.action ? <ActionBadge action={e.action} size="sm" /> : null}
              </div>
              <div className="mt-1 truncate text-2xs text-text-2">{e.event_type}</div>
              <div className="mt-1 font-mono text-[10px] text-text-4">{shortHash(e.prev_hash, 3)} →</div>
              <div className={cn('font-mono text-[10px]', broken ? 'text-block' : 'text-text-2')}>{shortHash(e.hash, 3)}</div>
            </motion.div>
          </Fragment>
        );
      })}
    </div>
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
    const t = setTimeout(() => document.getElementById(`seq-${highlightSeq}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 250);
    return () => clearTimeout(t);
  }, [highlightSeq, events.length]);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-4 py-2.5">
        <MiniSelect label="Event" value={type} onChange={setType} options={types.map((t) => ({ value: t, label: t }))} />
        <span className="ml-auto text-xs text-text-3">{rows.length} records</span>
      </div>
      <div className="max-h-[560px] overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-[1] bg-surface-1/95 backdrop-blur">
            <tr className="border-b border-border text-left text-2xs uppercase tracking-[0.08em] text-text-3">
              <th className="px-4 py-2 font-medium">Seq</th>
              <th className="px-2 py-2 font-medium">Time</th>
              <th className="px-2 py-2 font-medium">Event</th>
              <th className="px-2 py-2 font-medium">Actor</th>
              <th className="px-2 py-2 font-medium">Action</th>
              <th className="px-2 py-2 font-medium">Control</th>
              <th className="px-2 py-2 font-medium">Decision</th>
              <th className="px-2 py-2 font-medium">Version</th>
              <th className="px-4 py-2 font-medium">Hash</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <Fragment key={e.seq}>
                <tr
                  id={`seq-${e.seq}`}
                  onClick={() => setOpen((o) => (o === e.seq ? null : e.seq))}
                  className={cn('cursor-pointer border-b border-border-subtle hover:bg-surface-2/60', highlightSeq === e.seq && 'bg-brand/10 shadow-[inset_2px_0_0_var(--accent-fg)]')}
                >
                  <td className="px-4 py-1.5 font-mono tabular text-text-1">
                    <ChevronRight className={cn('mr-1 inline size-3 text-text-4 transition-transform', open === e.seq && 'rotate-90')} />
                    {e.seq}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-text-3" title={fmtDateTime(e.ts)}>
                    {fmtTime(e.ts, { seconds: true })}
                  </td>
                  <td className="px-2 py-1.5">
                    <span className="rounded-[5px] border border-border bg-surface-2 px-1.5 font-mono text-2xs text-text-2">{e.event_type}</span>
                  </td>
                  <td className="max-w-[180px] truncate px-2 py-1.5">{e.actor ? <IdentityChip identity={e.actor} /> : <span className="text-text-4">system</span>}</td>
                  <td className="px-2 py-1.5">{e.action ? <ActionBadge action={e.action as Action} size="sm" /> : <span className="text-text-4">—</span>}</td>
                  <td className="px-2 py-1.5">{e.control_id ? <ControlChip id={e.control_id} /> : <span className="text-text-4">—</span>}</td>
                  <td className="px-2 py-1.5">
                    {e.decision_id ? (
                      <button
                        type="button"
                        className="font-mono text-2xs text-accent-fg hover:underline"
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
                  <td className="px-2 py-1.5 font-mono text-2xs text-text-3">
                    v{e.policy_version ?? '—'} · #{e.feed_serial ?? '—'}
                  </td>
                  <td className="px-4 py-1.5">
                    <HashText hash={e.hash} copy={false} />
                  </td>
                </tr>
                {open === e.seq ? (
                  <tr className="border-b border-border-subtle bg-background/60">
                    <td colSpan={9} className="px-4 py-3">
                      <div className="mb-2 flex flex-wrap gap-4 font-mono text-2xs text-text-3">
                        <span>prev_hash {e.prev_hash}</span>
                        <span>hash {e.hash}</span>
                      </div>
                      <JsonView value={e} collapsed={1} maxHeight={280} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ export
const FORMATS = [
  { id: 'jsonl', label: 'JSONL', ext: 'jsonl', hint: 'One aegis.audit/1 record per line, hashes included' },
  { id: 'csv', label: 'CSV', ext: 'csv', hint: 'Flat columns for spreadsheets' },
  { id: 'ocsf', label: 'OCSF', ext: 'json', hint: 'OCSF 1.9 · Detection Finding 2004 / API Activity 6003' },
] as const;

function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function ExportDialog({ open, onOpenChange, controls, agents }: { open: boolean; onOpenChange: (o: boolean) => void; controls: string[]; agents: string[] }) {
  const [format, setFormat] = useState<(typeof FORMATS)[number]['id']>('ocsf');
  const [from, setFrom] = useState(() => toLocalInput(new Date(Date.now() - 24 * 3600e3)));
  const [to, setTo] = useState(() => toLocalInput(new Date(Date.now() + 60e3)));
  const [action, setAction] = useState('');
  const [control, setControl] = useState('');
  const [agent, setAgent] = useState('');
  const [busy, setBusy] = useState(false);
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
      toast.success(`Exported ${f.label} · ${name}`);
      onOpenChange(false);
    } catch (e) {
      toast.error(isApiRequestError(e) ? e.message : 'Export failed');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>Export audit log</DialogTitle>
          <DialogDescription>Signed-off evidence for auditors and your SIEM. Exports are themselves audited.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-2">
            {FORMATS.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFormat(f.id)}
                className={cn('rounded-lg border px-3 py-2 text-left transition-colors', format === f.id ? 'border-accent-fg/60 bg-brand/10' : 'border-border hover:border-border-strong')}
              >
                <div className="text-sm font-semibold text-text-1">{f.label}</div>
                <div className="mt-0.5 text-2xs leading-4 text-text-3">{f.hint}</div>
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 text-2xs uppercase tracking-[0.08em] text-text-3">
              From
              <input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} className="h-8 rounded-md border border-border bg-background px-2 text-xs text-text-1 [color-scheme:dark]" />
            </label>
            <label className="flex flex-col gap-1 text-2xs uppercase tracking-[0.08em] text-text-3">
              To
              <input type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} className="h-8 rounded-md border border-border bg-background px-2 text-xs text-text-1 [color-scheme:dark]" />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <MiniSelect label="Action" value={action} onChange={setAction} options={(['block', 'require_approval', 'redact', 'log', 'allow'] as const).map((a) => ({ value: a, label: a }))} />
            <MiniSelect label="Control" value={control} onChange={setControl} options={controls.map((c) => ({ value: c, label: c }))} />
            <MiniSelect label="Agent" value={agent} onChange={setAgent} options={agents.map((c) => ({ value: c, label: c }))} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => void run()} disabled={busy}>
            <Download /> {busy ? 'Exporting…' : 'Export'}
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
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        <Download /> Export
      </Button>
      <ExportDialog open={open} onOpenChange={setOpen} controls={controls} agents={agents} />
    </RoleGate>
  );
}
