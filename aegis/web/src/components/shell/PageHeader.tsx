import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { resolveIcon } from '@/lib/icons';

export interface PageHeaderProps {
  title: string;
  subtitle?: ReactNode;
  icon?: string | LucideIcon;
  actions?: ReactNode;
  badge?: ReactNode;
}

/** Page title block (22 px / 600, muted 13 px subtitle, actions bottom-right). */
export function PageHeader({ title, subtitle, icon, actions, badge }: PageHeaderProps) {
  const Icon = typeof icon === 'string' ? resolveIcon(icon) : icon;
  return (
    <div className="mb-5 flex flex-wrap items-end gap-4">
      <div className="flex min-w-0 items-start gap-3">
        {Icon ? (
          <div className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-[10px] border border-border bg-surface-2 text-accent-fg shadow-raised">
            <Icon className="size-[18px]" />
          </div>
        ) : null}
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="m-0 text-xl font-semibold tracking-[-0.02em] text-text-1">{title}</h1>
            {badge}
          </div>
          {subtitle ? <p className="mt-1 text-[13px] text-text-3">{subtitle}</p> : null}
        </div>
      </div>
      {actions ? <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
