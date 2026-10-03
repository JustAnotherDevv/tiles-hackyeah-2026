import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        'inline-grid h-[18px] min-w-[18px] place-items-center rounded-[5px] border border-b-2 border-border-strong bg-surface-2 px-[5px] font-mono text-[10.5px] leading-none text-text-3',
        className,
      )}
    >
      {children}
    </kbd>
  );
}
