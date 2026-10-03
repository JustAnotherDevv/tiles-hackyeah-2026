// Verdict-probe runner (UIG-05): module-level cache {policy_version → results}, serialised runs, fresh
// `ses_probe_<ts>` session per run (no loop/rate state accumulates), dry_run so nothing is audited,
// approved or reserved. Gracefully "unavailable" when /v1/guard is missing or rejects the body.
// Owner: B19-dashboard-gov-policy.
import { useEffect, useSyncExternalStore } from 'react';
import { api, isApiRequestError } from '@/api/client';
import type { Verdict } from '@/api/types';
import { buildProbeBodies, diffProbes, fakeAwsKey, PROBES, summarizeVerdict, type ProbeFlip, type ProbeResult } from '@/components/governance/lib/probe-defs';
import { mockPolicyState } from '@/mocks/governance/policy';
import { mockProbeResults } from '@/mocks/governance/probes';

export interface ProbeRunnerState {
  status: 'idle' | 'running' | 'ready' | 'unavailable';
  version: number | null;
  results: Record<string, ProbeResult> | null;
  /** Flips of the latest version change (kept until the next change). */
  flips: ProbeFlip[];
  flipVersion: number | null;
  flippedAt: number;
  isMock: boolean;
  ranAt: number | null;
  durationMs: number | null;
  error: string | null;
}

export interface ProbeRun {
  version: number | null;
  results: Record<string, ProbeResult> | null;
  flips: ProbeFlip[];
  available: boolean;
  isMock: boolean;
}

interface GuardResponse {
  verdict: Verdict;
  decision_id?: string | null;
}

let state: ProbeRunnerState = {
  status: 'idle',
  version: null,
  results: null,
  flips: [],
  flipVersion: null,
  flippedAt: 0,
  isMock: false,
  ranAt: null,
  durationMs: null,
  error: null,
};
const listeners = new Set<() => void>();
let queue: Promise<unknown> = Promise.resolve();
const runs = new Map<string, Promise<ProbeRun>>();

function set(patch: Partial<ProbeRunnerState>): void {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

export function getProbeState(): ProbeRunnerState {
  return state;
}

export function subscribeProbes(l: () => void): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function errText(e: unknown): string {
  if (isApiRequestError(e)) return `${e.status} ${e.type ?? ''} ${e.message}`.trim();
  return e instanceof Error ? e.message : String(e);
}

async function execute(version: number | null, mock: boolean): Promise<ProbeRun> {
  const prev = state.results;
  const prevVersion = state.version;
  set({ status: 'running' });
  const t = performance.now();
  let results: Record<string, ProbeResult>;
  if (mock) {
    await sleep(220);
    results = mockProbeResults(mockPolicyState().yaml);
  } else {
    const bodies = buildProbeBodies(`ses_probe_${Date.now().toString(36)}`, fakeAwsKey());
    const settled = await Promise.allSettled(PROBES.map((p) => api.post<GuardResponse>('/v1/guard', bodies[p.id])));
    results = {};
    let firstErr: unknown = null;
    settled.forEach((s, i) => {
      const id = PROBES[i].id;
      if (s.status === 'fulfilled' && s.value.data && typeof s.value.data === 'object' && s.value.data.verdict) results[id] = summarizeVerdict(id, s.value.data.verdict);
      else if (s.status === 'rejected' && firstErr === null) firstErr = s.reason;
    });
    if (Object.keys(results).length === 0) {
      set({ status: 'unavailable', error: firstErr ? errText(firstErr) : 'POST /v1/guard returned no verdicts', ranAt: Date.now(), isMock: false });
      return { version, results: null, flips: [], available: false, isMock: false };
    }
  }
  const changed = prev !== null && prevVersion !== version;
  const flips = changed ? diffProbes(prev, results) : [];
  set({
    status: 'ready',
    version,
    results,
    flips: changed ? flips : state.flips,
    flipVersion: changed ? version : state.flipVersion,
    flippedAt: changed && flips.length ? Date.now() : state.flippedAt,
    isMock: mock,
    ranAt: Date.now(),
    durationMs: Math.round(performance.now() - t),
    error: null,
  });
  return { version, results, flips, available: true, isMock: mock };
}

/** Run the probe set for a policy version (deduped per version; serialised across versions). */
export function runProbes(version: number | null, opts: { mock?: boolean; force?: boolean } = {}): Promise<ProbeRun> {
  const key = `${version ?? 'x'}|${opts.mock ? 'mock' : 'live'}`;
  const existing = runs.get(key);
  if (existing && !opts.force) return existing;
  const p = queue.then(() => execute(version, Boolean(opts.mock)));
  queue = p.catch(() => undefined);
  runs.set(key, p);
  return p;
}

/** Subscribe to the probe cache; schedules a baseline run for `version` (1.2 s after first mount). */
export function useProbeRunner(version: number | null | undefined, isMock: boolean): ProbeRunnerState & { rerun: () => void } {
  const s = useSyncExternalStore(subscribeProbes, getProbeState, getProbeState);
  useEffect(() => {
    if (version === null || version === undefined) return;
    const delay = getProbeState().results ? 0 : 1200;
    const t = setTimeout(() => void runProbes(version, { mock: isMock }), delay);
    return () => clearTimeout(t);
  }, [version, isMock]);
  return { ...s, rerun: () => void runProbes(version ?? null, { mock: isMock, force: true }) };
}
