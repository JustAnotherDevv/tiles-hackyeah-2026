import type { LucideIcon } from '@/components/icons';
import type { ReactNode } from 'react';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';

export function EmptyState({ icon, title, hint, action, className }: { icon?: string | LucideIcon; title: ReactNode; hint?: ReactNode; action?: ReactNode; className?: string }) {
  const Icon = typeof icon === 'string' ? resolveIcon(icon) : (icon ?? resolveIcon('Inbox'));
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 px-4 py-10 text-center', className)}>
      <Icon className="size-5 text-text-4" />
      <div className="text-sm font-medium text-text-2">{title}</div>
      {hint ? <div className="max-w-sm text-xs text-text-3">{hint}</div> : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
