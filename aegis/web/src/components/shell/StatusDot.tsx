import { cn } from '@/lib/utils';

const COLOR = { ok: 'bg-allow', warn: 'bg-redact', error: 'bg-block', off: 'bg-text-4' } as const;
const RING = { ok: 'border-allow', warn: 'border-redact', error: 'border-block', off: 'border-text-4' } as const;

export function StatusDot({ status, pulse = false, label, className }: { status: 'ok' | 'warn' | 'error' | 'off'; pulse?: boolean; label?: string; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-xs text-text-2', className)}>
      <span className="relative inline-flex size-[7px] shrink-0">
        {pulse ? <span className={cn('absolute -inset-[3px] rounded-full border-[1.5px] opacity-30', RING[status])} /> : null}
        <span className={cn('relative inline-flex size-[7px] rounded-full', COLOR[status])} />
      </span>
      {label ? <span className="truncate">{label}</span> : null}
    </span>
  );
}
