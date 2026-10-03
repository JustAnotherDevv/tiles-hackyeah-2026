import type { DestClass, Destination } from '@/api/types';
import { DEST_COLORS } from '@/lib/colors';
import { resolveIcon } from '@/lib/icons';

export function DestBadge({ dest }: { dest: DestClass | Destination }) {
  const cls = typeof dest === 'string' ? dest : dest.dest_class;
  const c = DEST_COLORS[cls];
  const Icon = resolveIcon(c.icon);
  return (
    <span className="inline-flex h-5 items-center gap-1 rounded-xs border border-border bg-surface-2 px-1.5 font-mono text-xs" style={{ color: c.fg }}>
      <Icon className="size-3" />
      {typeof dest === 'string' ? c.label : dest.name}
    </span>
  );
}
