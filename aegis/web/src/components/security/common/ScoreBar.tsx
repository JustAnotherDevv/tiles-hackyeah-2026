// Score vs threshold bar with a threshold tick (prototype .score-bar).
import { motion, useReducedMotion } from 'framer-motion';
import type { Action } from '@/api/types';
import { ACTION_COLORS } from '@/lib/colors';
import { cn } from '@/lib/utils';

function fmtScore(v: number, max: number): string {
  if (max <= 1) return v.toFixed(2);
  return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(v % 1 === 0 ? 0 : 2);
}

export function ScoreBar({
  score,
  threshold,
  max = 1,
  action,
  muted,
  animate = true,
  delay = 0,
  className,
  showText = true,
}: {
  score: number | null;
  threshold: number | null;
  max?: number;
  action?: Action | null;
  muted?: boolean;
  animate?: boolean;
  delay?: number;
  className?: string;
  showText?: boolean;
}) {
  const reduce = useReducedMotion();
  if (score === null || score === undefined) return null;
  const w = Math.max(0, Math.min(1, score / (max || 1))) * 100;
  const th = threshold !== null && threshold !== undefined ? Math.max(0, Math.min(1, threshold / (max || 1))) * 100 : null;
  const over = threshold !== null && threshold !== undefined && score >= threshold;
  const fill = muted ? '#4B5160' : action && action !== 'allow' && action !== 'log' ? ACTION_COLORS[action].chart : over ? '#D97706' : '#2E8A5F';
  return (
    <div className={cn('flex min-w-0 flex-col gap-1', className)}>
      <div className="relative mt-1 h-1.5 rounded-full bg-surface-3">
        <motion.div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ background: fill }}
          initial={animate && !reduce ? { width: 0 } : false}
          animate={{ width: `${w}%` }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: delay / 1000 }}
        />
        {th !== null ? (
          <span className="absolute -inset-y-1 w-0.5 rounded-sm bg-text-1" style={{ left: `calc(${th}% - 1px)` }} title={`threshold ${threshold}`} />
        ) : null}
      </div>
      {showText ? (
        <div className="flex justify-between font-mono text-2xs text-text-3">
          <b className="font-medium text-text-1">{fmtScore(score, max)}</b>
          {threshold !== null && threshold !== undefined ? (
            <span>
              {over ? '≥' : '<'} {fmtScore(threshold, max)}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
