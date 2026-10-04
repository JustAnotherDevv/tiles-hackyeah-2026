// Horizontal bar list (HTML, framer width grow): label · bar · value. Used for top controls, entities,
// agents, per-control latency. Bars animate width over 640 ms; rows link when `href` is set.
import { motion, useReducedMotion } from 'framer-motion';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/shell/EmptyState';
import { cn } from '@/lib/utils';

export interface BarListItem {
  key: string;
  label: ReactNode;
  value: number;
  color?: string;
  hint?: ReactNode;
  href?: string;
}

export interface BarListProps {
  items: BarListItem[];
  valueFormat?: (n: number) => string;
  max?: number;
  limit?: number;
  emptyText?: string;
  className?: string;
  /** label column width in px (default 128) */
  labelWidth?: number;
}

export function BarList({ items, valueFormat = (n) => n.toLocaleString('en-US'), max, limit, emptyText = 'Nothing yet', className, labelWidth = 128 }: BarListProps) {
  const reduce = useReducedMotion();
  const rows = (limit ? items.slice(0, limit) : items).filter((i) => Number.isFinite(i.value));
  if (rows.length === 0) return <EmptyState icon="ChartBar" title={emptyText} className="py-6" />;
  const top = max ?? Math.max(...rows.map((r) => r.value), 1);
  return (
    <div className={cn('flex flex-col', className)}>
      {rows.map((r, i) => {
        const pct = Math.max(r.value > 0 ? 1.5 : 0, Math.min(100, (r.value / top) * 100));
        const inner = (
          <>
            <div className="min-w-0" style={{ width: labelWidth }}>
              <div className="truncate text-[12.5px] text-text-1">{r.label}</div>
              {r.hint ? <div className="truncate text-[11px] leading-[14px] text-text-3">{r.hint}</div> : null}
            </div>
            <div className="relative h-2 min-w-0 flex-1 rounded-[3px] bg-surface-2/60">
              <motion.div
                className="absolute inset-y-0 left-0 rounded-[3px]"
                style={{ background: r.color ?? '#4A7FE0' }}
                initial={reduce ? false : { width: 0 }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.64, delay: reduce ? 0 : i * 0.03, ease: [0.16, 1, 0.3, 1] }}
              />
            </div>
            <div className="w-14 shrink-0 text-right text-[12.5px] text-text-2 tabular">{valueFormat(r.value)}</div>
          </>
        );
        const cls = 'flex items-center gap-3 rounded-md px-1 py-[7px] transition-colors duration-100';
        return r.href ? (
          <Link key={r.key} to={r.href} className={cn(cls, 'hover:bg-white/[0.025]')}>
            {inner}
          </Link>
        ) : (
          <div key={r.key} className={cls}>
            {inner}
          </div>
        );
      })}
    </div>
  );
}
