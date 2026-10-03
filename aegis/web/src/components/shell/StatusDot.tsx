import { cn } from '@/lib/utils';

const COLOR = { ok: 'bg-allow', warn: 'bg-redact', error: 'bg-block', off: 'bg-text-4' } as const;

export function StatusDot({ status, pulse = false, label }: { status: 'ok' | 'warn' | 'error' | 'off'; pulse?: boolean; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-text-2">
      <span className="relative inline-flex size-2">
        {pulse ? <span className={cn('absolute inset-0 rounded-full animate-ping-dot', COLOR[status])} /> : null}
        <span className={cn('relative inline-flex size-2 rounded-full', COLOR[status])} />
      </span>
      {label}
    </span>
  );
}
