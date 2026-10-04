// Inline load error with Retry (used when a panel has no data and its request failed). Owner: dashboard-shell.
import { TriangleAlert } from '@/components/icons';
import { isApiRequestError } from '@/api/client';
import { cn } from '@/lib/utils';

export function errorText(error: unknown): string {
  if (isApiRequestError(error)) return error.type === 'timeout' ? error.message : `${error.message}${error.status ? ` (HTTP ${error.status})` : ''}`;
  if (error instanceof TypeError) return 'Gateway unreachable — is it running?';
  return error instanceof Error ? error.message : String(error);
}

export function PanelError({ error, onRetry, title = 'Could not load data', className }: { error: unknown; onRetry?: () => void; title?: string; className?: string }) {
  return (
    <div role="alert" className={cn('flex items-start gap-2.5 rounded-md border border-block/25 bg-block/[0.06] px-3 py-2.5 text-[12.5px]', className)}>
      <TriangleAlert className="mt-px size-4 shrink-0 text-block" />
      <div className="min-w-0 flex-1">
        <div className="font-medium text-text-1">{title}</div>
        <div className="mt-0.5 break-words text-text-3">{errorText(error)}</div>
      </div>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="h-7 shrink-0 rounded-md border border-border bg-surface-2 px-2.5 text-xs font-medium text-text-1 hover:bg-surface-3">
          Retry
        </button>
      ) : null}
    </div>
  );
}
