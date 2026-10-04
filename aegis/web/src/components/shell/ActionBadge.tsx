import type { Action } from '@/api/types';
import { ACTION_COLORS } from '@/lib/colors';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';

/** Decision badge: icon + label in the decision colour (never colour alone). `monitor` → dashed "would …". */
export function ActionBadge({ action, size = 'md', monitor = false, className }: { action: Action; size?: 'sm' | 'md' | 'lg'; monitor?: boolean; className?: string }) {
  const c = ACTION_COLORS[action] ?? ACTION_COLORS.log;
  const Icon = resolveIcon(c.icon);
  return (
    <span
      data-action={action}
      className={cn(
        'inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-sm border font-[550] leading-none tracking-[0.01em]',
        size === 'sm' ? 'h-[18px] px-1.5 text-[11px]' : size === 'lg' ? 'h-6 gap-1.5 px-2 text-sm' : 'h-5 px-1.5 text-xs',
        monitor && 'border-dashed bg-transparent',
        c.className,
      )}
    >
      <Icon className={size === 'lg' ? 'size-3.5' : 'size-3'} strokeWidth={2.2} />
      {monitor ? `would ${c.label.toLowerCase()}` : c.label}
    </span>
  );
}
