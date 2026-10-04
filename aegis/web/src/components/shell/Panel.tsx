import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { MockBadge } from './MockBadge';

export interface PanelProps {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** no body padding (tables, lists) */
  flush?: boolean;
  /** show the "demo data" badge in the header */
  isMock?: boolean;
  /** icon/dot before the title */
  leading?: ReactNode;
  /** header with a bottom divider */
  bordered?: boolean;
  footer?: ReactNode;
  children?: ReactNode;
}

/** Card (DESIGN_TOKENS §6): surface-1, hairline border, radius 12, shadow-card. Wrap every data panel. */
export function Panel({ title, description, actions, className, bodyClassName, flush, isMock, leading, bordered, footer, children }: PanelProps) {
  const hasHeader = Boolean(title || actions || isMock || leading);
  return (
    <section className={cn('relative flex min-w-0 flex-col rounded-lg border border-border bg-card shadow-card', className)}>
      {hasHeader ? (
        <header className={cn('flex min-h-11 items-center gap-2.5 px-4 pt-3.5 max-sm:flex-wrap', bordered && 'border-b border-border-subtle pb-3')}>
          {leading}
          <div className="min-w-0 flex-1">
            {title ? <h2 className="truncate text-[13px] font-[550] leading-[18px] tracking-[-0.005em] text-text-1">{title}</h2> : null}
            {description ? <p className="truncate text-xs leading-4 text-text-3">{description}</p> : null}
          </div>
          {isMock || actions ? (
            <div className="flex shrink-0 items-center gap-2">
              {isMock ? <MockBadge /> : null}
              {actions}
            </div>
          ) : null}
        </header>
      ) : null}
      <div className={cn('min-h-0 flex-1', flush ? '' : 'px-4 pb-4 pt-3', bodyClassName)}>{children}</div>
      {footer ? <footer className="flex items-center gap-2 border-t border-border-subtle px-4 py-2.5 text-xs text-text-3">{footer}</footer> : null}
    </section>
  );
}
