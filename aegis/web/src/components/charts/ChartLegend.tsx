import { cn } from '@/lib/utils';

export interface LegendItem {
  label: string;
  color: string;
  kind?: 'swatch' | 'line' | 'dash';
  value?: string;
}

/** HTML legend (always shown for ≥ 2 series — secondary encoding is mandatory, DESIGN_TOKENS §7). */
export function ChartLegend({ items, className }: { items: LegendItem[]; className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-center gap-x-3.5 gap-y-1 text-xs text-text-2', className)}>
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1.5">
          {it.kind === 'line' ? (
            <span className="h-0.5 w-3 rounded-[1px]" style={{ background: it.color }} />
          ) : it.kind === 'dash' ? (
            <span className="h-0.5 w-3" style={{ background: `repeating-linear-gradient(90deg, ${it.color} 0 3px, transparent 3px 5px)` }} />
          ) : (
            <span className="size-2 rounded-[2px]" style={{ background: it.color }} />
          )}
          {it.label}
          {it.value ? <span className="tabular text-text-3">{it.value}</span> : null}
        </span>
      ))}
    </div>
  );
}
