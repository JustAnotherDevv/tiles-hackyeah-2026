import type { DestClass, Destination } from '@/api/types';
import { DEST_COLORS } from '@/lib/colors';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';

/** Destination tag: Laptop local · Cloud remote · Globe third party. */
export function DestBadge({ dest, className }: { dest: DestClass | Destination; className?: string }) {
  const cls = typeof dest === 'string' ? dest : dest.dest_class;
  const c = DEST_COLORS[cls] ?? DEST_COLORS.remote;
  const Icon = resolveIcon(c.icon);
  return (
    <span className={cn('inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-xs border border-border bg-surface-2 px-1.5 font-mono text-[11px] text-text-2', className)} title={c.label}>
      <Icon className="size-3" style={{ color: c.fg }} />
      {typeof dest === 'string' ? c.label : dest.name}
    </span>
  );
}
