import type { Action } from '@/api/types';
import { ACTION_COLORS } from '@/lib/colors';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';

export function ActionBadge({ action, size = 'md', monitor = false }: { action: Action; size?: 'sm' | 'md' | 'lg'; monitor?: boolean }) {
  const c = ACTION_COLORS[action];
  const Icon = resolveIcon(c.icon);
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-sm border font-medium',
        size === 'sm' ? 'h-5 px-1.5 text-2xs' : size === 'lg' ? 'h-6 px-2 text-sm' : 'h-5 px-1.5 text-xs',
        monitor && 'border-dashed',
        c.className,
      )}
    >
      <Icon className="size-3" />
      {monitor ? `would ${c.label.toLowerCase()}` : c.label}
    </span>
  );
}
