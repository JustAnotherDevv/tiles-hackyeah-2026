// Budget usage bar (UIG-03): used fill + striped reserved segment + soft (80 %) / hard (100 %) markers.
// Width eases over 300 ms so live settles are visible; colours from BUDGET_STATE_COLORS.
// Over-limit usage extends into a 0–110 % track so "Blocking · 402" reads at a glance.
// Owner: B19-dashboard-gov-policy.
import type { BudgetState } from '@/api/types';
import { BUDGET_STATE_COLORS } from '@/lib/colors';
import { cn } from '@/lib/utils';

const MAX = 110; // track covers 0–110 % of the limit

function pos(pct: number): number {
  return (Math.max(0, Math.min(pct, MAX)) / MAX) * 100;
}

export function BudgetUsageBar({
  used,
  reserved,
  limit,
  state,
  softPct = 80,
  size = 'md',
  className,
}: {
  used: number;
  reserved: number;
  limit: number;
  state: BudgetState;
  softPct?: number;
  size?: 'sm' | 'md';
  className?: string;
}) {
  const pct = limit > 0 ? (used / limit) * 100 : 0;
  const resPct = limit > 0 ? ((used + reserved) / limit) * 100 : 0;
  const c = BUDGET_STATE_COLORS[state];
  const w = pos(pct);
  const rw = Math.max(0, pos(resPct) - w);
  return (
    <div
      className={cn('relative w-full rounded-[4px] bg-surface-3', size === 'sm' ? 'h-1.5' : 'h-2', className)}
      role="meter"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`${Math.round(pct)}% used`}
    >
      <div
        className="absolute inset-y-0 left-0 rounded-[4px] transition-[width,background-color] duration-300 ease-out motion-reduce:transition-none"
        style={{ width: `${w}%`, background: c.fill }}
      />
      {rw > 0.2 ? (
        <div
          className="absolute inset-y-0 transition-[left,width] duration-300 ease-out motion-reduce:transition-none"
          title="reserved (in-flight requests)"
          style={{
            left: `${w}%`,
            width: `${rw}%`,
            background: `repeating-linear-gradient(135deg, ${c.fill}99 0 3px, transparent 3px 6px)`,
          }}
        />
      ) : null}
      <span className="absolute -top-[3px] -bottom-[3px] w-[2px] rounded-[1px] bg-text-4" style={{ left: `calc(${pos(softPct)}% - 1px)` }} title={`soft limit ${softPct}%`} />
      <span className="absolute -top-[4px] -bottom-[4px] w-[2px] rounded-[1px] bg-text-2" style={{ left: `calc(${pos(100)}% - 1px)` }} title="hard limit" />
    </div>
  );
}

const STATE_TEXT: Record<BudgetState, string> = {
  ok: 'Healthy',
  soft: 'Downgrading',
  hard: 'Blocking · 402',
  killed: 'Killed · 429',
};

export function BudgetStatePill({ state, className }: { state: BudgetState; className?: string }) {
  const c = BUDGET_STATE_COLORS[state];
  return (
    <span
      className={cn('inline-flex h-5 items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 text-2xs font-medium', className)}
      style={{ color: c.fg, borderColor: `${c.fill}55`, background: `${c.fill}14` }}
    >
      <span className="size-1.5 rounded-full" style={{ background: c.fill }} />
      {STATE_TEXT[state]}
    </span>
  );
}
