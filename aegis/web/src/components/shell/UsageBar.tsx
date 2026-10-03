// Usage / bullet bar (DESIGN_TOKENS §6): track surface-3, 2 px markers at 80 % and 100 %, fill colour by
// budget state, width animates over 640 ms. pct is 0–100+ (API *_pct convention).
import type { BudgetState } from '@/api/types';
import { BUDGET_STATE_COLORS } from '@/lib/colors';
import { cn } from '@/lib/utils';

export interface UsageBarProps {
  pct: number;
  state?: BudgetState;
  markers?: number[];
  size?: 'sm' | 'md' | 'lg';
  className?: string;
  /** optional dashed forecast extension (0–100+) */
  forecastPct?: number;
}

function autoState(pct: number): BudgetState {
  return pct >= 100 ? 'hard' : pct >= 80 ? 'soft' : 'ok';
}

export function UsageBar({ pct, state, markers = [80, 100], size = 'md', className, forecastPct }: UsageBarProps) {
  const st = state ?? autoState(pct);
  const max = Math.max(100, ...markers);
  const w = Math.max(0, Math.min(pct, max)) / max * 100;
  const fw = forecastPct !== undefined ? Math.max(0, Math.min(forecastPct, max)) / max * 100 : 0;
  const h = size === 'sm' ? 'h-1.5' : size === 'lg' ? 'h-2.5' : 'h-2';
  return (
    <div className={cn('relative rounded-[4px] bg-surface-3', h, className)} role="meter" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      {fw > w ? (
        <div
          className="absolute inset-y-0 left-0 rounded-[4px] opacity-40"
          style={{ width: `${fw}%`, background: `repeating-linear-gradient(90deg, ${BUDGET_STATE_COLORS[autoState(forecastPct ?? 0)].fill} 0 4px, transparent 4px 7px)` }}
        />
      ) : null}
      <div
        className="absolute inset-y-0 left-0 rounded-[4px] transition-[width,background-color] duration-[640ms] ease-out"
        style={{ width: `${w}%`, background: BUDGET_STATE_COLORS[st].fill, boxShadow: st !== 'ok' ? `0 0 12px -2px ${BUDGET_STATE_COLORS[st].fill}` : undefined }}
      />
      {markers.map((m) => (
        <span
          key={m}
          className={cn('absolute -top-[3px] -bottom-[3px] w-[2px] rounded-[1px]', m >= 100 ? 'bg-text-3' : 'bg-text-4')}
          style={{ left: `calc(${(m / max) * 100}% - 1px)` }}
        />
      ))}
    </div>
  );
}
