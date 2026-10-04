// Playground visuals: reveal scheduler, in-flight state, verdict summary, request path, run history.
import { useReducedMotion } from 'framer-motion';
import { Ban, Bot, Cloud, HardDrive, Shield, User, X } from '@/components/icons';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import type { Action, DestClass } from '@/api/types';
import { ActionBadge } from '@/components/shell';
import { ACTION_COLORS } from '@/lib/colors';
import { fmtMs } from '@/lib/format';
import { cn } from '@/lib/utils';
import { ControlChip } from '../common/atoms';
import type { RevealState } from '../decision/PipelineWaterfall';
import { stageSchedule } from '../lib/schedule';
import type { CatalogControl, TraceModel } from '../types';

/** Drives pending → running → done per stage, paced by real latencies (×25, clamped 140–700 ms). */
export function useRevealSchedule(trace: TraceModel | null, runKey: string | null): { reveal: Record<string, RevealState>; done: boolean } {
  const reduce = useReducedMotion() ?? false;
  const [state, setState] = useState<{ key: string | null; reveal: Record<string, RevealState>; done: boolean }>({ key: null, reveal: {}, done: false });
  const plan = useMemo(
    () => (trace ? stageSchedule(trace.stages.map((s) => ({ key: s.key, phase: s.phase, latencyMs: s.latencyMs, status: s.status })), { reduced: reduce }) : null),
    [trace, reduce],
  );
  useEffect(() => {
    if (!trace || !plan || !runKey) return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const initial: Record<string, RevealState> = {};
    for (const it of plan.items) initial[it.key] = reduce ? 'done' : 'pending';
    const t0 = setTimeout(() => setState({ key: runKey, reveal: initial, done: reduce }), 0);
    timers.push(t0);
    if (!reduce) {
      for (const it of plan.items) {
        timers.push(setTimeout(() => setState((s) => ({ ...s, reveal: { ...s.reveal, [it.key]: 'running' } })), it.startMs));
        timers.push(setTimeout(() => setState((s) => ({ ...s, reveal: { ...s.reveal, [it.key]: 'done' } })), it.startMs + Math.max(60, it.durMs)));
      }
      timers.push(setTimeout(() => setState((s) => ({ ...s, done: true })), plan.totalMs + 120));
    }
    return () => timers.forEach(clearTimeout);
  }, [trace, plan, runKey, reduce]);
  if (state.key !== runKey) return { reveal: {}, done: false };
  return { reveal: state.reveal, done: state.done };
}

export function Spinner({ className }: { className?: string }) {
  return <span aria-hidden className={cn('inline-block size-3.5 shrink-0 animate-spin rounded-full border-[1.5px] border-text-4 border-t-text-1', className)} />;
}

/** In-flight state: the controls that apply to this surface (static list, one spinner). */
export function ScanningControls({ controls }: { controls: CatalogControl[] }) {
  const shown = controls.slice(0, 12);
  return (
    <div className="space-y-3" role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-xs text-text-2">
        <Spinner />
        Evaluating against {controls.length} control{controls.length === 1 ? '' : 's'}
      </div>
      {shown.length ? (
        <div className="flex flex-wrap gap-1.5 opacity-70">
          {shown.map((c) => (
            <ControlChip key={c.id} id={c.id} kind={c.kind} name={c.name} />
          ))}
          {controls.length > shown.length ? <span className="self-center font-mono text-2xs text-text-4">+{controls.length - shown.length}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-2xs text-text-3">{label}</dt>
      <dd className="truncate font-mono text-xs tabular-nums text-text-1">{children}</dd>
    </div>
  );
}

/** Verdict summary: decision, primary control, reason, score vs threshold, latency, policy/feed version. */
export function VerdictHero({
  action,
  controlId,
  reason,
  score,
  threshold,
  policyVersion,
  feedSerial,
  totalMs,
  redactions,
  isMock,
}: {
  action: Action;
  controlId: string | null;
  reason: string;
  score: number | null;
  threshold: number | null;
  policyVersion: number;
  feedSerial: number | null;
  totalMs: number;
  redactions?: number;
  isMock?: boolean;
}) {
  const c = ACTION_COLORS[action];
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card shadow-card" style={{ borderLeft: `3px solid ${c.chart}` }} aria-label="Verdict">
      <div className="flex flex-wrap items-center gap-2 px-4 pt-3.5">
        <span className="text-xs text-text-3">Verdict</span>
        <ActionBadge action={action} size="lg" />
        {controlId ? <ControlChip id={controlId} /> : <span className="text-xs text-text-3">No control fired</span>}
        {isMock ? <span className="ml-auto text-2xs text-text-3">Simulated</span> : null}
      </div>
      <p className="px-4 pt-2 text-sm leading-6 text-text-1">{reason || (action === 'allow' ? 'No control fired. Request allowed.' : '—')}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-border-subtle px-4 py-3 sm:grid-cols-5">
        <Meta label="Score">
          {score !== null ? (
            <>
              {score.toFixed(2)}
              {threshold !== null ? <span className="text-text-3"> {score >= threshold ? '≥' : '<'} {threshold.toFixed(2)}</span> : null}
            </>
          ) : (
            <span className="text-text-4">—</span>
          )}
        </Meta>
        <Meta label="Redactions">{redactions ?? 0}</Meta>
        <Meta label="Latency">{fmtMs(totalMs)}</Meta>
        <Meta label="Policy">v{policyVersion}</Meta>
        <Meta label="Feed">{feedSerial !== null ? `#${feedSerial}` : '—'}</Meta>
      </dl>
    </section>
  );
}

const DEST_ICON: Record<DestClass, typeof Cloud> = { local: HardDrive, remote: Cloud, third_party: Cloud };

/** Request path: caller → Aegis → destination. The link to the destination is cut on block/approval. */
export function FlowStrip({ action, dest, destName, agent, active, sent }: { action: Action | null; dest: DestClass; destName: string; agent: string; active: boolean; sent: boolean }) {
  const stopped = action === 'block' || action === 'require_approval';
  const DestIcon = DEST_ICON[dest];
  const isAgent = agent.includes('@');
  const node = (icon: ReactNode, label: string, sub: string, color?: string) => (
    <div className="flex min-w-0 items-center gap-2">
      <div className="grid size-8 shrink-0 place-items-center rounded-md border border-border bg-surface-2 text-text-2" style={color ? { borderColor: color, color } : undefined}>
        {icon}
      </div>
      <div className="min-w-0">
        <div className="truncate text-xs font-medium text-text-1">{label}</div>
        <div className="truncate font-mono text-2xs text-text-3">{sub}</div>
      </div>
    </div>
  );
  const link = (cut: boolean, state: 'idle' | 'pending' | 'done') => (
    <div className="relative mx-1 h-px min-w-4" style={cut ? { borderTop: '1px dashed var(--border-strong)' } : { background: state === 'done' ? 'var(--text-4)' : 'var(--border)' }}>
      {state === 'pending' ? <span className="absolute inset-0 animate-pulse bg-text-3" /> : null}
      {cut ? (
        <span className="absolute left-1/2 top-0 grid size-4 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-block/40 bg-background text-block">
          {action === 'block' ? <Ban className="size-2.5" /> : <X className="size-2.5" />}
        </span>
      ) : null}
    </div>
  );
  const verdictColor = action ? ACTION_COLORS[action].fg : undefined;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(16px,0.6fr)_minmax(0,1fr)_minmax(16px,0.6fr)_minmax(0,1fr)] items-center rounded-lg border border-border bg-card px-3 py-2.5 shadow-card sm:px-4" aria-label="Request path">
      {node(isAgent ? <Bot className="size-4" /> : <User className="size-4" />, isAgent ? (agent.split('@')[0] ?? agent) : 'You', agent === 'you' ? 'viewer' : agent)}
      {link(false, action ? 'done' : active ? 'pending' : 'idle')}
      {node(<Shield className="size-4" />, 'Aegis', action ? ACTION_COLORS[action].label.toLowerCase() : active ? 'evaluating' : 'in-line', verdictColor)}
      {link(Boolean(action && stopped), action && !stopped && sent ? 'done' : 'idle')}
      {node(<DestIcon className="size-4" />, destName, sent ? dest.replace('_', ' ') : `${dest.replace('_', ' ')} · not sent`)}
    </div>
  );
}

export interface RunRecord {
  n: number;
  at: number;
  label: string;
  action: Action;
  controlId: string | null;
  score: number | null;
  policyVersion: number;
  latencyMs?: number;
  isMock: boolean;
}

/** Memory-only run history (text may contain PII, so it never goes to storage). */
export function RunHistory({ runs, className }: { runs: RunRecord[]; className?: string }) {
  if (!runs.length) return null;
  return (
    <div className={cn('overflow-x-auto', className)}>
      <table className="w-full min-w-[520px] text-xs">
        <thead>
          <tr className="border-b border-border-subtle text-left text-2xs text-text-3">
            <th className="py-1.5 pl-4 pr-2 font-normal">Time</th>
            <th className="px-2 py-1.5 font-normal">Input</th>
            <th className="px-2 py-1.5 font-normal">Verdict</th>
            <th className="px-2 py-1.5 font-normal">Control</th>
            <th className="px-2 py-1.5 text-right font-normal">Score</th>
            <th className="px-2 py-1.5 text-right font-normal">Latency</th>
            <th className="py-1.5 pl-2 pr-4 text-right font-normal">Policy</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.n} className="border-b border-border-subtle last:border-0">
              <td className="py-1.5 pl-4 pr-2 font-mono tabular-nums text-text-3">{new Date(r.at).toLocaleTimeString([], { hour12: false })}</td>
              <td className="max-w-[220px] truncate px-2 py-1.5 text-text-2" title={r.label}>
                {r.label}
                {r.isMock ? <span className="text-text-4"> · simulated</span> : null}
              </td>
              <td className="px-2 py-1.5">
                <ActionBadge action={r.action} size="sm" />
              </td>
              <td className="px-2 py-1.5 font-mono text-text-2">{r.controlId ?? <span className="text-text-4">—</span>}</td>
              <td className="px-2 py-1.5 text-right font-mono tabular-nums text-text-2">{r.score !== null ? r.score.toFixed(2) : <span className="text-text-4">—</span>}</td>
              <td className="px-2 py-1.5 text-right font-mono tabular-nums text-text-2">{r.latencyMs !== undefined ? fmtMs(r.latencyMs) : '—'}</td>
              <td className="py-1.5 pl-2 pr-4 text-right font-mono tabular-nums text-text-3">v{r.policyVersion}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
