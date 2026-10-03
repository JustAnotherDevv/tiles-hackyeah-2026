// "policy v14 · feed #2" with the current versions from /healthz ("decided under v14 · now v15").
import { Link } from 'react-router-dom';
import { cn } from '@/lib/utils';

export function VersionStamp({
  policyVersion,
  feedSerial,
  current,
  className,
  compact,
}: {
  policyVersion: number | null | undefined;
  feedSerial: number | null | undefined;
  current?: { policyVersion: number | null; feedSerial: number | null };
  className?: string;
  compact?: boolean;
}) {
  const policyStale = current?.policyVersion != null && policyVersion != null && current.policyVersion !== policyVersion;
  const feedStale = current?.feedSerial != null && feedSerial != null && current.feedSerial !== feedSerial;
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-x-1.5 font-mono text-xs text-text-2', className)}>
      {policyVersion != null ? (
        <Link
          to={`/governance/policy?tab=history&version=${policyVersion}`}
          className="hover:text-text-1 hover:underline"
          title="Open this policy version"
          onClick={(e) => e.stopPropagation()}
        >
          policy v{policyVersion}
        </Link>
      ) : (
        <span>policy —</span>
      )}
      <span className="text-text-4">·</span>
      <span>feed #{feedSerial ?? '—'}</span>
      {!compact && (policyStale || feedStale) ? (
        <span className="rounded-full border border-redact/30 bg-redact/10 px-1.5 text-2xs text-redact" title="Versions have changed since this decision">
          now {policyStale ? `v${current?.policyVersion}` : ''}
          {policyStale && feedStale ? ' · ' : ''}
          {feedStale ? `#${current?.feedSerial}` : ''}
        </span>
      ) : null}
    </span>
  );
}
