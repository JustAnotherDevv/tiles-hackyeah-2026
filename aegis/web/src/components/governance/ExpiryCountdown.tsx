// mm:ss countdown from expires_at (server clock is the truth; no client-side state transitions).
// Rose under 60 s, "expired" at ≤ 0. Owner: B18-dashboard-gov-approvals.
import { Clock } from '@/components/icons';
import { cn } from '@/lib/utils';
import { useNow } from './hooks';
import { fmtCountdown } from './lib/format-gov';

export function ExpiryCountdown({ expiresAt, prefix, className, icon = true }: { expiresAt: string | null | undefined; prefix?: string; className?: string; icon?: boolean }) {
  const now = useNow(1000);
  if (!expiresAt) return null;
  const left = Date.parse(expiresAt) - now;
  const expired = left <= 0;
  const urgent = !expired && left < 60_000;
  const soon = !expired && left < 5 * 60_000;
  return (
    <span
      className={cn('inline-flex items-center gap-1 tabular', expired || urgent ? 'text-block' : soon ? 'text-redact' : 'text-text-3', className)}
      title={`Expires ${new Date(expiresAt).toLocaleTimeString('en-GB')}`}
    >
      {icon ? <Clock className={cn('size-3', urgent && 'animate-pulse')} /> : null}
      {prefix && !expired ? <span>{prefix}</span> : null}
      <span className="font-mono">{fmtCountdown(left)}</span>
    </span>
  );
}
