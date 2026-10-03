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

export function PageHeader({ title, subtitle, icon, actions, badge }: PageHeaderProps) {
  const Icon = typeof icon === 'string' ? resolveIcon(icon) : icon;
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        {Icon ? (
          <div className="mt-0.5 grid size-8 place-items-center rounded-md border border-border bg-surface-2 text-accent-fg">
            <Icon className="size-4" />
          </div>
        ) : null}
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            {badge}
          </div>
          {subtitle ? <p className="text-sm text-text-3">{subtitle}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
