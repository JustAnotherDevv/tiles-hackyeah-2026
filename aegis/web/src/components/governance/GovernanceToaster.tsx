// GovernanceToaster (UIG-05): singleton, no props, safe to mount many times (only the first mounted
// instance is active). It keeps a verdict-probe baseline for the active policy version and, on every
// reload (SSE `policy.applied`, or a version bump seen by polling / the offline mock store), re-runs
// the dry-run probes and toasts "Policy vN hot-reloaded in X ms" + WHICH VERDICTS FLIPPED.
// The shell owns the plain SSE toasts (policy.*, approval.*, killswitch); this one adds the flips and
// uses sonner id `policy-v<version>` so a shell toast with the same id is updated in place.
// Owner: B19-dashboard-gov-policy.
import { useEffect, useRef, useState } from 'react';
import { useApi, useEvents } from '@/api/hooks';
import type { PolicyResponse, SseEventMap } from '@/api/types';
import { policyMocks, policyPaths, useMockStoreRefresh } from './policy/policy-api';
import { announcePolicyApplied } from './policy/policy-toast';
import { runProbes } from './policy/probe-runner';

let owner: number | null = null;
let seq = 0;

export function GovernanceToaster() {
  const [id] = useState(() => ++seq);
  const [active, setActive] = useState(false);
  useEffect(() => {
    if (owner === null) {
      owner = id;
      setActive(true);
    }
    return () => {
      if (owner === id) owner = null;
    };
  }, [id]);
  return active ? <ToasterInner /> : null;
}

function ToasterInner() {
  const { data, isMock, refresh } = useApi<PolicyResponse>(policyPaths.policy, { mock: policyMocks.policy, refreshOn: ['policy.applied'], refreshMs: 30000 });
  useMockStoreRefresh(refresh, isMock);
  const version = data?.version ?? null;

  // baseline for the version we booted on
  useEffect(() => {
    if (version === null) return;
    const t = setTimeout(() => void runProbes(version, { mock: isMock }), 1500);
    return () => clearTimeout(t);
  }, [version, isMock]);

  // live reloads (editor, judge editing config/policy.yaml, approvals executing a change)
  useEvents(['policy.applied'], (_name, payload, meta) => {
    // ring-buffer replays after (re)connect / persona switch are history, not news
    if (meta.replay) return;
    const p = payload as SseEventMap['policy.applied'];
    void announcePolicyApplied(
      { version: p.version, previous_version: p.previous_version, source: p.source, actor: p.actor, changes: p.changes ?? [], latency_ms: p.latency_ms },
      { mock: false },
    );
  });

  // version bump without an SSE event (offline mock store, missed event): announce after a grace period
  const last = useRef<number | null>(null);
  useEffect(() => {
    if (version === null) return;
    const prev = last.current;
    last.current = version;
    if (prev === null || version <= prev) return;
    const t = setTimeout(
      () =>
        void announcePolicyApplied(
          { version, previous_version: prev, source: data?.source ?? 'api', actor: null, changes: [], latency_ms: null },
          { mock: isMock },
        ),
      1200,
    );
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  return null;
}
