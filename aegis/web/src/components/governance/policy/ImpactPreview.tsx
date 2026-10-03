// Pre-apply impact preview (UIG-12): full self-test of the ACTIVE policy (cached per version) vs the
// DRAFT, listing cases whose verdict changes ("aws-key-blocked: block → allow") and failing
// must-protect cases ("apply will be rejected"). Runs on demand (it executes the whole self-test
// suite on the server). Owner: B19-dashboard-gov-policy.
import { ArrowRight, FlaskConical, Loader2, ShieldAlert } from 'lucide-react';
import { useState } from 'react';
import type { SelfTestResult } from '@/api/types';
import { ActionBadge } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { policyApi } from './policy-api';
import type { PolicyDraft } from './use-policy-draft';

const baselineCache = new Map<number, SelfTestResult[]>();

interface Impact {
  draftKey: string;
  flips: { name: string; before: SelfTestResult; after: SelfTestResult }[];
  failing: SelfTestResult[];
  total: number;
  passed: number;
  error: string | null;
}

export function ImpactPreview({ d }: { d: PolicyDraft }) {
  const [busy, setBusy] = useState(false);
  const [impact, setImpact] = useState<Impact | null>(null);
  const draftKey = `${d.base?.version ?? 0}|${d.draft?.length ?? 0}|${d.draft?.slice(-64) ?? ''}`;
  const stale = impact !== null && impact.draftKey !== draftKey;

  const run = async () => {
    if (!d.base || d.draft === null) return;
    setBusy(true);
    try {
      let base = baselineCache.get(d.base.version);
      const [bv, dv] = await Promise.all([
        base ? Promise.resolve(null) : policyApi.validate(d.base.yaml, true, d.base.yaml),
        policyApi.validate(d.draft, true, d.base.yaml),
      ]);
      if (bv) {
        base = bv.data.selftest ?? [];
        baselineCache.set(d.base.version, base);
      }
      const after = dv.data.selftest ?? [];
      const byName = new Map((base ?? []).map((t) => [t.name, t]));
      const flips = after.filter((t) => byName.has(t.name) && byName.get(t.name)?.got !== t.got).map((t) => ({ name: t.name, before: byName.get(t.name) as SelfTestResult, after: t }));
      setImpact({ draftKey, flips, failing: after.filter((t) => !t.passed), total: after.length, passed: after.filter((t) => t.passed).length, error: dv.data.valid || after.length ? null : (dv.data.errors[0]?.message ?? 'Draft does not parse') });
    } catch (e) {
      setImpact({ draftKey, flips: [], failing: [], total: 0, passed: 0, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <FlaskConical className="size-3.5 text-text-3" />
        <span className="text-xs text-text-2">Impact preview — full self-test, active vs draft</span>
        <Button size="xs" variant="secondary" className="ml-auto" disabled={!d.dirty || busy} onClick={() => void run()}>
          {busy ? <Loader2 className="size-3 animate-spin" /> : null}
          {impact && !stale ? 'Re-check' : 'Check impact'}
        </Button>
      </div>
      {!d.dirty ? (
        <div className="text-2xs text-text-3">No draft changes.</div>
      ) : impact === null ? (
        <div className="text-2xs text-text-3">Runs every self-test case against the draft and lists the verdicts that would change.</div>
      ) : (
        <div className={cn('space-y-2', stale && 'opacity-60')}>
          {stale ? <div className="text-2xs text-redact">Draft changed since this check.</div> : null}
          {impact.error ? <div className="text-xs text-block">{impact.error}</div> : null}
          {impact.total > 0 ? (
            <div className={cn('text-xs tabular', impact.failing.length ? 'text-block' : 'text-allow')}>
              self-test {impact.passed}/{impact.total} {impact.failing.length ? '· apply will be rejected' : 'passed'}
            </div>
          ) : null}
          {impact.flips.length ? (
            <ul className="space-y-1">
              {impact.flips.map((f) => (
                <li key={f.name} className="flex flex-wrap items-center gap-1.5 rounded-md border border-approval/25 bg-approval/[0.05] px-2 py-1 text-xs">
                  <span className="font-mono text-text-1">{f.name}</span>
                  <ActionBadge action={f.before.got} size="sm" />
                  <ArrowRight className="size-3 text-text-3" />
                  <ActionBadge action={f.after.got} size="sm" />
                  {f.after.got_control ? <span className="font-mono text-2xs text-text-3">{f.after.got_control}</span> : null}
                </li>
              ))}
            </ul>
          ) : impact.total > 0 ? (
            <div className="text-2xs text-text-3">No self-test verdict changes.</div>
          ) : null}
          {impact.failing.length ? (
            <ul className="space-y-1">
              {impact.failing.slice(0, 5).map((t) => (
                <li key={t.name} className="flex items-center gap-1.5 text-2xs text-block">
                  <ShieldAlert className="size-3" /> {t.name}: expected {t.expect}, got {t.got}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </div>
  );
}
