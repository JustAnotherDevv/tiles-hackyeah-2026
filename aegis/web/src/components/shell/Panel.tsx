import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { MockBadge } from './MockBadge';

export interface PanelProps {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  bodyClassName?: string;
  flush?: boolean;
  isMock?: boolean;
  children?: ReactNode;
}

export function Panel({ title, description, actions, className, bodyClassName, flush, isMock, children }: PanelProps) {
  return (
    <section className={cn('rounded-lg border border-border bg-card shadow-card', className)}>
      {title || actions || isMock ? (
        <header className="flex items-start justify-between gap-3 px-4 pt-3.5">
          <div>
            {title ? <h2 className="text-[13px] font-semibold">{title}</h2> : null}
            {description ? <p className="text-xs text-text-3">{description}</p> : null}
          </div>
          <div className="flex items-center gap-2">
            {isMock ? <MockBadge /> : null}
            {actions}
          </div>
        </header>
      ) : null}
      <div className={cn(flush ? '' : 'px-4 pb-4 pt-3', bodyClassName)}>{children}</div>
    </section>
  );
}
