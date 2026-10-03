// Threat-feed update pipeline checklist (plan 16 §2.3 "Threat feed"). PURE module, node-testable.
import type { FeedStatus } from '@/api/types';
import type { FeedStep } from '../types';

const STEPS: { key: string; label: string }[] = [
  { key: 'fetch', label: 'Fetch latest.json' },
  { key: 'verify', label: 'Verify ed25519 (pinned key)' },
  { key: 'sha256', label: 'sha256 matches index' },
  { key: 'schema', label: 'Schema + RE2 compile' },
  { key: 'vectors', label: 'Inline test vectors' },
  { key: 'swap', label: 'Atomic swap · anti-rollback' },
];

/** Index of the failing step for a rejection reason (machine token first, free text fallback). */
export function failingStepIndex(reason: string | null | undefined): number {
  if (!reason) return -1;
  const r = reason.toLowerCase();
  if (/unreachable|timeout|connect|refused|dns/.test(r)) return 0;
  if (/bad_signature|signature|ed25519|verify/.test(r)) return 1;
  if (/sha256|digest|mismatch/.test(r)) return 2;
  if (/schema|regex|re2|expired|invalid/.test(r)) return 3;
  if (/vector|selftest|self-test/.test(r)) return 4;
  if (/rollback|serial|stale/.test(r)) return 5;
  return 1;
}

export function deriveFeedSteps(status: FeedStatus | null, lastRejectedReason?: string | null): FeedStep[] {
  const rejected = status?.status === 'rejected' || status?.status === 'unreachable';
  const reason = lastRejectedReason ?? (rejected ? (status?.last_error ?? status?.status ?? null) : null);
  let fail = failingStepIndex(reason);
  if (fail < 0 && status?.status === 'unreachable') fail = 0;
  const serial = status?.serial ?? null;
  const quarantined = status?.signatures_quarantined ?? 0;
  const total = status?.signatures_total ?? 0;
  return STEPS.map((s, i) => {
    let state: FeedStep['state'] = 'ok';
    let detail: string | null = null;
    if (!status) state = 'pending';
    else if (fail >= 0 && i === fail) state = 'fail';
    else if (fail >= 0 && i > fail) state = 'skipped';
    if (s.key === 'vectors' && state === 'ok') detail = quarantined ? `${total} signatures · quarantined ${quarantined}` : `${total} signatures passed`;
    if (s.key === 'swap') {
      if (state === 'ok') detail = serial !== null ? `active #${serial}` : 'seed bundle';
      else if (state !== 'pending') detail = serial !== null ? `kept #${serial}` : 'kept last-good';
    }
    if (state === 'fail') detail = reason ?? 'failed';
    if (state === 'skipped' && s.key !== 'swap') detail = 'skipped';
    return { key: s.key, label: s.label, state, detail };
  });
}
