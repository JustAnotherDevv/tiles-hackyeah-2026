// Playground visuals: reveal scheduler, scanning skeleton, VerdictHero, FlowStrip packet, RunHistory.
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { Ban, Bot, Cloud, HardDrive, Shield, User, X } from 'lucide-react';
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

/** In-flight state: the controls that apply to this surface, shimmering. */
export function ScanningControls({ controls }: { controls: CatalogControl[] }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 text-xs text-text-3">
        <span className="relative flex size-2">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent-fg opacity-60" />
          <span className="relative inline-flex size-2 rounded-full bg-accent-fg" />
        </span>
        Scanning with {controls.length} controls…
      </div>
      <div className="grid gap-1">
        {controls.slice(0, 14).map((c, i) => (
          <motion.div
            key={c.id}
            initial={{ opacity: 0.25 }}
            animate={{ opacity: [0.25, 0.9, 0.25] }}
            transition={{ duration: 1.4, repeat: Infinity, delay: i * 0.06 }}
            className="grid grid-cols-[86px_1fr_80px] items-center gap-3 rounded-md border border-border-subtle bg-surface-1 px-2.5 py-1.5"
          >
            <ControlChip id={c.id} kind={c.kind} name={c.name} />
            <span className="truncate text-xs text-text-2">{c.name}</span>
            <span className="h-1.5 rounded-full bg-gradient-to-r from-surface-3 via-accent-fg/40 to-surface-3" />
          </motion.div>
        ))}
      </div>
    </div>
  );
}

export function VerdictHero({
  action,
  controlId,
  reason,
  score,
  threshold,
  policyVersion,
  feedSerial,
  totalMs,
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
  isMock?: boolean;
}) {
  const c = ACTION_COLORS[action];
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, scale: 0.96, y: 8 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 320, damping: 26 }}
      className="relative overflow-hidden rounded-xl border p-4"
      style={{ borderColor: c.border, background: `radial-gradient(120% 140% at 0% 0%, ${c.bg}, transparent 60%), var(--surface-1)` }}
    >
      <div className="absolute -right-10 -top-10 size-40 rounded-full opacity-25 blur-3xl" style={{ background: c.chart }} />
      <div className="relative flex flex-wrap items-center gap-3">
        <ActionBadge action={action} size="lg" />
        {controlId ? <ControlChip id={controlId} /> : <span className="text-xs text-text-3">no control fired</span>}
        {score !== null ? (
          <span className="font-mono text-xs text-text-2">
            score <b className="text-text-1">{score.toFixed(2)}</b>
            {threshold !== null ? ` ${score >= threshold ? '≥' : '<'} ${threshold}` : ''}
          </span>
        ) : null}
        <span className="ml-auto font-mono text-xs text-text-3">
          policy v{policyVersion} · feed #{feedSerial ?? '—'} · {fmtMs(totalMs)}
          {isMock ? ' · simulated' : ''}
        </span>
      </div>
      <div className="relative mt-2 text-[15px] leading-6 text-text-1">{reason || (action === 'allow' ? 'No control fired — request allowed.' : '—')}</div>
    </motion.div>
  );
}

const DEST_ICON: Record<DestClass, typeof Cloud> = { local: HardDrive, remote: Cloud, third_party: Cloud };

/** agent → Aegis → destination; the packet stops at Aegis on block/approval. */
export function FlowStrip({ action, dest, destName, agent, active, sent }: { action: Action | null; dest: DestClass; destName: string; agent: string; active: boolean; sent: boolean }) {
  const reduce = useReducedMotion();
  const stopped = action === 'block' || action === 'require_approval';
  const color = action ? ACTION_COLORS[action].chart : '#6366F1';
  const DestIcon = DEST_ICON[dest];
  const node = (icon: ReactNode, label: string, sub: string, highlight?: string) => (
    <div className="flex min-w-0 flex-col items-center gap-1">
      <div className="grid size-10 place-items-center rounded-xl border border-border bg-surface-2 text-text-2 shadow-raised" style={highlight ? { borderColor: highlight, color: highlight } : undefined}>
        {icon}
      </div>
      <div className="max-w-[120px] truncate text-xs font-medium text-text-1">{label}</div>
      <div className="max-w-[120px] truncate font-mono text-2xs text-text-3">{sub}</div>
    </div>
  );
  return (
    <div className="grid grid-cols-[auto_1fr_auto_1fr_auto] items-center gap-2 rounded-xl border border-border bg-surface-1 px-4 py-3">
      {node(agent.includes('@') ? <Bot className="size-4" /> : <User className="size-4" />, agent.includes('@') ? agent.split('@')[0] ?? agent : 'you', agent)}
      <div className="relative h-px bg-border">
        <AnimatePresence>
          {active && !reduce ? (
            <motion.span
              key={`p1-${action}`}
              className="absolute -top-[3px] size-[7px] rounded-full"
              style={{ background: '#818CF8', boxShadow: '0 0 10px #818CF8' }}
              initial={{ left: '0%' }}
              animate={{ left: '100%' }}
              transition={{ duration: 0.6, ease: 'easeInOut', repeat: action ? 0 : Infinity }}
            />
          ) : null}
        </AnimatePresence>
      </div>
      {node(<Shield className="size-4" />, 'Aegis', 'in-line', action ? ACTION_COLORS[action].fg : '#818CF8')}
      <div className="relative h-px" style={{ background: stopped ? 'transparent' : 'var(--border)', borderTop: stopped ? '1px dashed var(--border-strong)' : undefined }}>
        {action && stopped ? (
          <span className="absolute left-1/2 top-0 grid size-5 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-block/20 text-block">
            {action === 'block' ? <Ban className="size-3" /> : <X className="size-3" />}
          </span>
        ) : null}
        {action && !stopped && !reduce ? (
          <motion.span
            key={`p2-${action}-${sent}`}
            className="absolute -top-[3px] size-[7px] rounded-full"
            style={{ background: color, boxShadow: `0 0 10px ${color}` }}
            initial={{ left: '0%', opacity: 1 }}
            animate={{ left: '100%', opacity: sent ? 1 : 0.4 }}
            transition={{ duration: 0.7, ease: 'easeInOut', delay: 0.1 }}
          />
        ) : null}
      </div>
      {node(<DestIcon className="size-4" />, destName, sent ? dest : `${dest} · not sent`, action && !stopped && sent ? ACTION_COLORS[action].fg : undefined)}
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
  isMock: boolean;
}

/** Memory-only run history (text may contain PII, so it never goes to storage). */
export function RunHistory({ runs, className }: { runs: RunRecord[]; className?: string }) {
  if (!runs.length) return null;
  return (
    <div className={cn('flex flex-wrap items-center gap-1.5', className)}>
      <span className="mr-1 text-2xs uppercase tracking-[0.08em] text-text-3">History</span>
      <AnimatePresence initial={false}>
        {runs.map((r, i) => (
          <motion.span
            key={r.n}
            layout
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-1 py-0.5 pl-1 pr-2 text-2xs"
            title={`${r.label} · ${new Date(r.at).toLocaleTimeString()}`}
          >
            <ActionBadge action={r.action} size="sm" />
            <span className="font-mono text-text-2">v{r.policyVersion}</span>
            {r.controlId ? <span className="font-mono text-text-3">{r.controlId}</span> : null}
            {r.score !== null ? <span className="font-mono text-text-3">{r.score.toFixed(2)}</span> : null}
            {i < runs.length - 1 ? <span className="text-text-4">←</span> : null}
          </motion.span>
        ))}
      </AnimatePresence>
    </div>
  );
}
