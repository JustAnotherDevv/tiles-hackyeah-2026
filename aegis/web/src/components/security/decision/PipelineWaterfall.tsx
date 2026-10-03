// Stage grid: icon | control + sub | score vs threshold | latency waterfall (prototype .stage / .wf).
import { motion, useReducedMotion } from 'framer-motion';
import { Ban, Check, Eye, EyeOff, Minus, ScrollText, SkipForward, TriangleAlert, UserCheck, type LucideIcon } from 'lucide-react';
import { memo } from 'react';
import type { Action } from '@/api/types';
import { ACTION_COLORS } from '@/lib/colors';
import { fmtMs } from '@/lib/format';
import { cn } from '@/lib/utils';
import { KIND_COLORS } from '../common/colors';
import { ScoreBar } from '../common/ScoreBar';
import type { TraceModel, TraceStage } from '../types';

export type RevealState = 'pending' | 'running' | 'done';

const ACTION_ICON: Record<Action, LucideIcon> = { allow: Check, log: ScrollText, redact: EyeOff, require_approval: UserCheck, block: Ban };

function stageTone(s: TraceStage): { icon: LucideIcon; fg: string; bg: string; border: string } {
  const neutral = { fg: 'var(--text-3)', bg: 'var(--surface-2)', border: 'var(--border-default)' };
  switch (s.status) {
    case 'hit': {
      const c = ACTION_COLORS[s.action ?? 'block'];
      return { icon: ACTION_ICON[s.action ?? 'block'], fg: c.fg, bg: c.bg, border: c.border };
    }
    case 'pass':
      return { icon: Check, fg: ACTION_COLORS.allow.fg, bg: ACTION_COLORS.allow.bg, border: ACTION_COLORS.allow.border };
    case 'monitor':
      return { icon: Eye, fg: ACTION_COLORS[s.action ?? 'block'].fg, bg: 'transparent', border: ACTION_COLORS[s.action ?? 'block'].border };
    case 'degraded':
      return { icon: TriangleAlert, fg: '#FBBF24', bg: 'rgba(245,158,11,.10)', border: 'rgba(245,158,11,.28)' };
    case 'skipped':
      return { icon: SkipForward, ...neutral };
    default:
      return { icon: Minus, ...neutral };
  }
}

function subText(s: TraceStage): string {
  if (s.status === 'skipped') return s.skippedReason ?? 'skipped';
  if (s.status === 'quiet') return `ran · no finding${s.latencyMs === null ? ' · latency n/a' : ''}`;
  if (s.status === 'monitor') return `monitor · would have ${s.action === 'require_approval' ? 'required approval' : s.action} — ${s.reason ?? ''}`;
  if (s.status === 'degraded') return `degraded · ${s.reason ?? 'fail-mode applied'}`;
  return s.reason ?? '';
}

export const StageRow = memo(function StageRow({
  s,
  scaleMs,
  index,
  reveal = 'done',
  animate = true,
}: {
  s: TraceStage;
  scaleMs: number;
  index: number;
  reveal?: RevealState;
  animate?: boolean;
}) {
  const reduce = useReducedMotion();
  const tone = stageTone(s);
  const Icon = tone.icon;
  const pending = reveal === 'pending';
  const running = reveal === 'running';
  const left = scaleMs > 0 ? (s.offsetMs / scaleMs) * 100 : 0;
  const width = scaleMs > 0 && s.latencyMs !== null ? Math.max(0.8, (s.latencyMs / scaleMs) * 100) : 0;
  const barColor = s.status === 'hit' && s.action ? ACTION_COLORS[s.action].chart : (KIND_COLORS[s.kind] ?? 'var(--accent-fg)');
  return (
    <motion.div
      initial={animate && !reduce ? { opacity: 0, x: -6 } : false}
      animate={{ opacity: pending ? 0.38 : 1, x: 0 }}
      transition={{ duration: 0.42, ease: [0.16, 1, 0.3, 1], delay: animate && !reduce ? index * 0.045 : 0 }}
      className={cn(
        'grid grid-cols-[22px_minmax(140px,1.25fr)_minmax(110px,1fr)_120px] items-center gap-3 border-b border-border-subtle py-2 last:border-0',
        s.status === 'skipped' && 'text-text-3',
      )}
      data-control={s.controlId}
    >
      <span
        className={cn('relative grid size-[22px] place-items-center rounded-[7px] border', running && 'animate-pulse', s.status === 'monitor' && 'border-dashed')}
        style={pending ? undefined : { color: tone.fg, background: tone.bg, borderColor: tone.border }}
      >
        {running ? <span className="absolute inset-0 rounded-[7px] ring-2 ring-accent-fg/50" /> : null}
        <Icon className="size-3" />
      </span>
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 text-[12.5px] font-medium leading-4">
          <span className={cn('truncate', s.status === 'skipped' && 'text-text-3')}>{s.name}</span>
          <span className="shrink-0 font-mono text-2xs font-normal text-text-3">{s.controlId}</span>
          {s.primary ? <span className="shrink-0 rounded-full border border-accent-fg/40 px-1.5 text-[9.5px] uppercase tracking-wider text-accent-fg">primary</span> : null}
          {s.degraded && s.status !== 'degraded' ? <span className="shrink-0 rounded-full border border-redact/40 px-1.5 text-[9.5px] text-redact">degraded</span> : null}
        </div>
        <div className="truncate font-mono text-[11px] leading-[14px] text-text-3" title={subText(s)}>
          {pending ? 'pending…' : running ? 'scanning…' : subText(s)}
        </div>
      </div>
      <div className="min-w-0">
        {pending || running ? (
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">{running ? <div className="h-full w-1/3 animate-pulse rounded-full bg-accent-fg/40" /> : null}</div>
        ) : s.score !== null && s.status !== 'skipped' ? (
          <ScoreBar score={s.score} threshold={s.threshold} max={s.scaleMax} action={s.status === 'hit' ? s.action : null} muted={s.status === 'monitor'} animate={animate} delay={index * 45} />
        ) : (
          <span className="font-mono text-[11px] text-text-4">{s.status === 'skipped' ? 'skipped' : s.action && s.action !== 'allow' ? (s.status === 'monitor' ? `would ${s.action}` : s.action) : '—'}</span>
        )}
      </div>
      <div className="min-w-0">
        {s.status === 'skipped' || pending ? (
          <div className="text-right font-mono text-[11px] text-text-4">—</div>
        ) : (
          <>
            <div className="relative h-3.5">
              <div className="absolute inset-x-0 top-1.5 h-0.5 rounded-sm bg-border-subtle" />
              {s.latencyMs !== null ? (
                <motion.div
                  className="absolute top-[3px] h-2 rounded-[2px] opacity-90"
                  style={{ left: `${left}%`, background: barColor }}
                  initial={animate && !reduce ? { width: 0 } : false}
                  animate={{ width: `${Math.min(width, 100 - left)}%` }}
                  transition={{ duration: 0.5, delay: animate && !reduce ? index * 0.045 : 0 }}
                />
              ) : null}
            </div>
            <div className="mt-0.5 text-right font-mono text-[11px] text-text-2">{s.latencyMs === null ? 'n/a' : fmtMs(s.latencyMs)}</div>
          </>
        )}
      </div>
    </motion.div>
  );
});

export function PhaseHeader({ label, right }: { label: string; right?: string }) {
  return (
    <div className="flex items-center gap-2 pb-1 pt-3 text-2xs uppercase tracking-[0.08em] text-text-3">
      <span>{label}</span>
      <span className="h-px flex-1 bg-border-subtle" />
      {right ? <span className="font-mono normal-case tracking-normal">{right}</span> : null}
    </div>
  );
}

export function PipelineWaterfall({ trace, reveal, animate = true }: { trace: TraceModel; reveal?: Record<string, RevealState>; animate?: boolean }) {
  const scale = Math.max(trace.totalMs, 0.05);
  const det = trace.stages.filter((s) => s.phase === 'deterministic');
  const sem = trace.stages.filter((s) => s.phase === 'semantic');
  return (
    <div>
      <div className="grid grid-cols-[22px_minmax(140px,1.25fr)_minmax(110px,1fr)_120px] gap-3 border-b border-border pb-1.5 text-2xs uppercase tracking-[0.08em] text-text-3">
        <span />
        <span>Control</span>
        <span>Score vs threshold</span>
        <span className="text-right">Latency · waterfall</span>
      </div>
      {det.length ? <PhaseHeader label="Deterministic · sequential" right={fmtMs(trace.detTotalMs)} /> : null}
      {det.map((s, i) => (
        <StageRow key={s.key} s={s} scaleMs={scale} index={i} reveal={reveal?.[s.key]} animate={animate} />
      ))}
      {sem.length ? (
        <PhaseHeader
          label={trace.shortCircuitAfter ? `Semantic · skipped (short-circuit after ${trace.shortCircuitAfter})` : 'Semantic · parallel'}
          right={trace.shortCircuitAfter ? '0 ms' : fmtMs(trace.semTotalMs)}
        />
      ) : null}
      {sem.map((s, i) => (
        <StageRow key={s.key} s={s} scaleMs={scale} index={det.length + i} reveal={reveal?.[s.key]} animate={animate} />
      ))}
    </div>
  );
}
