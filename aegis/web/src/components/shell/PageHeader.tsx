import type { LucideIcon } from '@/components/icons';
import type { ReactNode } from 'react';
import { resolveIcon } from '@/lib/icons';

export interface PageHeaderProps {
  title: string;
  subtitle?: ReactNode;
  icon?: string | LucideIcon;
  actions?: ReactNode;
  badge?: ReactNode;
}

/** Page title block (22 px / 600, muted 13 px subtitle, actions bottom-right; actions wrap below on mobile). */
export function PageHeader({ title, subtitle, icon, actions, badge }: PageHeaderProps) {
  const Icon = typeof icon === 'string' ? resolveIcon(icon) : icon;
  return (
    <div className="mb-5 flex flex-wrap items-end gap-x-4 gap-y-3 max-md:mb-4">
      <div className="flex min-w-0 items-start gap-2.5">
        {Icon ? <Icon className="mt-[5px] size-5 shrink-0 text-text-3 max-md:hidden" /> : null}
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="m-0 text-xl font-semibold tracking-[-0.01em] text-text-1 max-md:text-lg">{title}</h1>
            {badge}
          </div>
          {subtitle ? <p className="mt-1 max-w-[880px] text-[13px] text-text-3">{subtitle}</p> : null}
        </div>
      </div>
      {actions ? <div className="ml-auto flex flex-wrap items-center gap-2 max-md:ml-0 max-md:w-full">{actions}</div> : null}
    </div>
  );
}
