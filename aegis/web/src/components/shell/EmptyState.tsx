import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { resolveIcon } from '@/lib/icons';

export function EmptyState({ icon, title, hint, action }: { icon?: string | LucideIcon; title: ReactNode; hint?: ReactNode; action?: ReactNode }) {
  const Icon = typeof icon === 'string' ? resolveIcon(icon) : (icon ?? resolveIcon('Inbox'));
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <Icon className="size-6 text-text-4" />
      <div className="text-sm font-medium text-text-2">{title}</div>
      {hint ? <div className="text-xs text-text-3">{hint}</div> : null}
      {action}
    </div>
  );
}
