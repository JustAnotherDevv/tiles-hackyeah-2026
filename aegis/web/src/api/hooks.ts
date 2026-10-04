// Data hooks for pages (CONTRACTS §5.4 "Shared shell API"; docs/plan/15 §4.2). Names and signatures are
// binding: useApi, useEvents, useLiveDecisions, useViewAs, usePendingApprovals (+ additive extras).
// Owner: dashboard-shell (B16).
//
// useApi: small SWR cache keyed `viewer|path` (switching "view as" refetches everything), in-flight dedupe,
// keeps previous data while refetching, `refreshMs` polling and debounced (≥ 500 ms) `refreshOn` SSE events.
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { toast } from 'sonner';
import { ROLE_COLORS } from '@/lib/colors';
import { isMockForced } from '@/lib/mockMode';
import type { ViewRole } from '@/lib/page';
import { getViewer, setViewer, subscribeViewer } from '@/lib/viewer';
import { mockDecisionsPage } from '@/mocks/shell/decisions';
import { mockHealth } from '@/mocks/shell/health';
import { mockApprovalsPending, mockMembers, whoamiFor } from '@/mocks/shell/org';
import { isApiRequestError, request, type ApiResult } from './client';
import { eventHub, type SseMeta, type SseStatus } from './sse';
import type { ApprovalsResponse, DecisionSummary, HealthResponse, Member, Page, SseEventMap, SseEventName, StatsTick, WhoAmI } from './types';

export interface UseApiOptions<T> {
  mock?: () => T;
  refreshMs?: number;
  refreshOn?: SseEventName[];
}

export interface UseApiResult<T> {
  data: T | undefined;
  error: Error | null;
  loading: boolean;
  isMock: boolean;
  refresh: () => Promise<void>;
}

// ---------------------------------------------------------------- viewer
/** Viewer id (re-renders on "view as" changes). null = server default viewer. */
export function useViewerId(): string | null {
  return useSyncExternalStore(subscribeViewer, getViewer, getViewer);
}

// ---------------------------------------------------------------- SWR cache
interface CacheEntry {
  data: unknown;
  isMock: boolean;
  at: number;
}
const cache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<ApiResult<unknown>>>();

function cacheKey(path: string): string {
  return `${getViewer() ?? ''}|${path}`;
}

function fetchShared<T>(path: string, mock?: () => T): Promise<ApiResult<T>> {
  const key = cacheKey(path);
  const existing = inflight.get(key);
  if (existing) return existing as Promise<ApiResult<T>>;
  const p = request<T>('GET', path, undefined, mock)
    .then((r) => {
      cache.set(key, { data: r.data, isMock: r.isMock, at: Date.now() });
      return r as ApiResult<unknown>;
    })
    .finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p as Promise<ApiResult<T>>;
}

/** Drop cached responses (all, or those whose path starts with `prefix`). */
export function invalidateApi(prefix?: string): void {
  for (const k of [...cache.keys()]) if (!prefix || k.split('|')[1]?.startsWith(prefix)) cache.delete(k);
}

export function useApi<T>(path: string | null, opts: UseApiOptions<T> = {}): UseApiResult<T> {
  const viewer = useViewerId();
  const key = path === null ? null : `${viewer ?? ''}|${path}`;
  const cached = key ? cache.get(key) : undefined;
  const [state, setState] = useState<{ key: string | null; path: string | null; data: T | undefined; error: Error | null; loading: boolean; isMock: boolean }>(() => ({
    key,
    path,
    data: cached?.data as T | undefined,
    error: null,
    loading: path !== null && !cached,
    isMock: cached?.isMock ?? false,
  }));
  const mockRef = useRef(opts.mock);
  mockRef.current = opts.mock;
  const pathRef = useRef(path);
  pathRef.current = path;
  const mounted = useRef(true);

  const load = useCallback(async (): Promise<void> => {
    const p = pathRef.current;
    if (p === null) return;
    const myKey = `${getViewer() ?? ''}|${p}`;
    setState((s) => ({ ...s, loading: true }));
    try {
      const r = await fetchShared<T>(p, mockRef.current);
      if (!mounted.current || `${getViewer() ?? ''}|${pathRef.current}` !== myKey) return;
      setState({ key: myKey, path: p, data: r.data, error: null, loading: false, isMock: r.isMock });
    } catch (e: unknown) {
      if (!mounted.current || `${getViewer() ?? ''}|${pathRef.current}` !== myKey) return;
      const error = e instanceof Error ? e : new Error(String(e));
      setState((s) => ({ ...s, error, loading: false }));
      if (!isApiRequestError(e)) console.warn('[aegis] useApi failed', p, e);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // (re)load on path or viewer change. Cached data shows immediately; otherwise a different PATH starts empty
  // (never another path's data/error), while a viewer-only change keeps the previous data marked stale.
  useEffect(() => {
    if (key === null) return;
    const c = cache.get(key);
    if (c) setState({ key, path, data: c.data as T, error: null, loading: true, isMock: c.isMock });
    else setState((s) => (s.path === path ? { ...s, key, error: null, loading: true } : { key, path, data: undefined, error: null, loading: true, isMock: false }));
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- path is part of key
  }, [key, load]);

  // polling pauses while the tab is hidden and catches up when it becomes visible again
  useEffect(() => {
    if (!opts.refreshMs || path === null) return;
    const id = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return;
      void load();
    }, Math.max(1000, opts.refreshMs));
    const onVis = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [opts.refreshMs, path, load]);

  const refreshOnKey = (opts.refreshOn ?? []).join(',');
  useEffect(() => {
    if (!refreshOnKey || path === null) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let lastRun = 0;
    const unsub = eventHub.subscribe(refreshOnKey.split(',') as SseEventName[], () => {
      const wait = Math.max(0, 500 - (Date.now() - lastRun));
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        lastRun = Date.now();
        void load();
      }, wait || 150);
    });
    return () => {
      unsub();
      if (timer) clearTimeout(timer);
    };
  }, [refreshOnKey, path, load]);

  const sameKey = state.key === key;
  const samePath = state.path === path;
  return {
    data: sameKey || samePath ? state.data : undefined,
    error: sameKey ? state.error : null,
    loading: state.loading,
    isMock: state.isMock,
    refresh: load,
  };
}

// ---------------------------------------------------------------- events
/** Subscribe to SSE events for the lifetime of the component (handler may change between renders). */
export function useEvents<N extends SseEventName>(names: N[], handler: (name: N, data: SseEventMap[N], meta: SseMeta) => void): void {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  const key = names.join(',');
  useEffect(() => {
    if (!key) return;
    return eventHub.subscribe(key.split(',') as SseEventName[], (name, data, meta) =>
      handlerRef.current(name as unknown as N, data as unknown as SseEventMap[N], meta),
    );
  }, [key]);
}

export function useSseStatus(): SseStatus {
  return useSyncExternalStore(
    (l) => eventHub.onStatus(l),
    () => eventHub.status,
    () => eventHub.status,
  );
}

// ---------------------------------------------------------------- generic module store helper
function createStore<T>(initial: T) {
  let value = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set: (v: T) => {
      value = v;
      listeners.forEach((l) => l());
    },
    subscribe: (l: () => void) => {
      listeners.add(l);
      return () => {
        listeners.delete(l);
      };
    },
  };
}

/** Keeps one hub subscription alive while at least one component uses it. */
function refCountedSubscription(start: () => () => void) {
  let count = 0;
  let stop: (() => void) | null = null;
  return () => {
    count += 1;
    if (count === 1) stop = start();
    return () => {
      count -= 1;
      if (count === 0 && stop) {
        stop();
        stop = null;
      }
    };
  };
}

// ---------------------------------------------------------------- live decisions (shared ring buffer)
const MAX_DECISIONS = 500;
const decisionStore = createStore<DecisionSummary[]>([]);
const seenIds = new Set<string>();
const batchListeners = new Set<(batch: DecisionSummary[]) => void>();
let pending: DecisionSummary[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;
let backfillState: 'idle' | 'loading' | 'done' = 'idle';

function flush(): void {
  flushTimer = null;
  if (pending.length === 0) return;
  const batch = pending.filter((d) => !seenIds.has(d.id));
  pending = [];
  if (batch.length === 0) return;
  batch.forEach((d) => seenIds.add(d.id));
  // newest first
  batch.sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0));
  const next = [...batch, ...decisionStore.get()].slice(0, MAX_DECISIONS);
  if (seenIds.size > MAX_DECISIONS * 4) {
    seenIds.clear();
    next.forEach((d) => seenIds.add(d.id));
  }
  decisionStore.set(next);
  batchListeners.forEach((l) => {
    try {
      l(batch);
    } catch (err) {
      console.error('[aegis] decision listener failed', err);
    }
  });
}

function queueDecision(d: DecisionSummary): void {
  pending.push(d);
  if (!flushTimer) flushTimer = setTimeout(() => requestAnimationFrame(flush), 200);
}

function backfill(): void {
  if (backfillState !== 'idle') return;
  backfillState = 'loading';
  const forced = isMockForced();
  request<Page<DecisionSummary>>('GET', '/api/decisions?limit=50', undefined, () => (forced ? mockDecisionsPage(30) : { items: [] }))
    .then((r) => {
      const items = (r.data?.items ?? []).filter((d) => !seenIds.has(d.id));
      items.forEach((d) => seenIds.add(d.id));
      const merged = [...decisionStore.get(), ...items].sort((a, b) => (a.ts < b.ts ? 1 : -1)).slice(0, MAX_DECISIONS);
      decisionStore.set(merged);
    })
    .catch(() => undefined)
    .finally(() => {
      backfillState = 'done';
    });
}

const retainDecisionFeed = refCountedSubscription(() => {
  backfill();
  return eventHub.subscribe(['decision'], (_n, data) => queueDecision(data as DecisionSummary));
});

/** Called with each 200 ms batch of NEW decisions (newest first). Returns an unsubscribe function. */
export function onDecisionBatch(listener: (batch: DecisionSummary[]) => void): () => void {
  batchListeners.add(listener);
  return () => {
    batchListeners.delete(listener);
  };
}

/** Clear the live buffer (demo reset). */
export function clearLiveDecisions(): void {
  seenIds.clear();
  decisionStore.set([]);
}

export function useLiveDecisions(limit = 200): { items: DecisionSummary[]; connected: boolean } {
  const all = useSyncExternalStore(decisionStore.subscribe, decisionStore.get, decisionStore.get);
  const status = useSseStatus();
  useEffect(() => retainDecisionFeed(), []);
  const items = useMemo(() => (all.length > limit ? all.slice(0, limit) : all), [all, limit]);
  return { items, connected: status === 'live' || status === 'mock' };
}

/** Subscribe to new-decision batches inside a component (handler may change). */
export function useDecisionBatches(handler: (batch: DecisionSummary[]) => void): void {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => retainDecisionFeed(), []);
  useEffect(() => onDecisionBatch((b) => ref.current(b)), []);
}

// ---------------------------------------------------------------- stats ticks
const statsStore = createStore<StatsTick | null>(null);
const retainStatsFeed = refCountedSubscription(() => eventHub.subscribe(['stats'], (_n, data) => statsStore.set(data as StatsTick)));

/** Latest SSE `stats` tick (every ~2 s) or null before the first one. */
export function useStatsTick(): StatsTick | null {
  useEffect(() => retainStatsFeed(), []);
  return useSyncExternalStore(statsStore.subscribe, statsStore.get, statsStore.get);
}

// ---------------------------------------------------------------- versions (policy / feed)
interface Versions {
  policyVersion: number | null;
  feedSerial: number | null;
  changedAt: number;
}
const versionStore = createStore<Versions>({ policyVersion: null, feedSerial: null, changedAt: 0 });
function setVersions(v: Partial<Versions>, flash: boolean): void {
  const cur = versionStore.get();
  const next = { ...cur, ...v };
  if (next.policyVersion === cur.policyVersion && next.feedSerial === cur.feedSerial) return;
  versionStore.set({ ...next, changedAt: flash && (cur.policyVersion !== null || cur.feedSerial !== null) ? Date.now() : cur.changedAt });
}
const retainVersionFeed = refCountedSubscription(() =>
  eventHub.subscribe(['policy.applied', 'feed.updated', 'decision'], (name, data) => {
    if (name === 'policy.applied') setVersions({ policyVersion: (data as SseEventMap['policy.applied']).version }, true);
    else if (name === 'feed.updated') setVersions({ feedSerial: (data as SseEventMap['feed.updated']).serial }, true);
    else if (name === 'decision') {
      const d = data as DecisionSummary;
      const cur = versionStore.get();
      if (cur.policyVersion === null || d.policy_version > cur.policyVersion) setVersions({ policyVersion: d.policy_version }, cur.policyVersion !== null);
    }
  }),
);

/** Active policy version + feed serial (from /healthz, kept fresh by SSE); changedAt bumps on change (flash). */
export function useVersions(): Versions {
  useEffect(() => retainVersionFeed(), []);
  const health = useApi<HealthResponse>('/healthz', { mock: mockHealth, refreshMs: 15_000 });
  useEffect(() => {
    if (health.data) setVersions({ policyVersion: health.data.policy_version, feedSerial: health.data.feed_serial }, true);
  }, [health.data]);
  return useSyncExternalStore(versionStore.subscribe, versionStore.get, versionStore.get);
}

// ---------------------------------------------------------------- org / view as
const memberIndex = new Map<string, Member>(mockMembers().items.map((m) => [m.id, m]));

/** Synchronous member lookup (seeded with the demo cast, refreshed whenever /api/members loads). */
export function getMember(id: string | null | undefined): Member | undefined {
  return id ? memberIndex.get(id) : undefined;
}

export function useMembers(): Member[] {
  const { data } = useApi<{ items: Member[] }>('/api/members', { mock: mockMembers, refreshOn: ['org.updated'] });
  const items = data?.items;
  useEffect(() => {
    if (items?.length) items.forEach((m) => memberIndex.set(m.id, m));
  }, [items]);
  return items ?? EMPTY_MEMBERS;
}
const EMPTY_MEMBERS: Member[] = [];

export function useWhoAmI(): UseApiResult<WhoAmI> {
  const viewer = useViewerId();
  return useApi<WhoAmI>('/api/whoami', { mock: () => whoamiFor(viewer), refreshOn: ['org.updated'] });
}

function announceViewer(member: Member | undefined): void {
  if (!member) return;
  toast(`Viewing as ${member.name} · ${ROLE_COLORS[member.role].label}`, {
    id: 'view-as',
    description: member.title ?? undefined,
    duration: 2600,
    className: 'aegis-toast',
  });
}

export function useViewAs(): { member: Member | null; role: ViewRole; members: Member[]; setViewAs: (id: string) => void } {
  const viewer = useViewerId();
  const members = useMembers();
  const who = useWhoAmI();
  const member = useMemo(
    () => members.find((m) => m.id === viewer) ?? (viewer ? null : (who.data?.member ?? null)) ?? members.find((m) => m.role === 'owner') ?? null,
    [members, viewer, who.data],
  );
  const setViewAs = useCallback(
    (id: string) => {
      if (id === getViewer()) return;
      setViewer(id);
      announceViewer(members.find((m) => m.id === id));
    },
    [members],
  );
  // unknown roles (e.g. an anonymous read-only `viewer`) get the least privilege, never owner
  const raw = member?.role ?? 'owner';
  const role: ViewRole = raw === 'owner' || raw === 'admin' || raw === 'member' ? raw : 'member';
  return { member, role, members, setViewAs };
}

// ---------------------------------------------------------------- approvals badge
function useApprovalsPending() {
  return useApi<ApprovalsResponse>('/api/approvals?status=pending', {
    mock: mockApprovalsPending,
    refreshOn: ['approval.created', 'approval.updated'],
    refreshMs: 30_000,
  });
}

/** Pending approvals count for the sidebar badge (fresher StatsTick value wins when the list is mocked). */
export function usePendingApprovals(): number {
  return usePendingApprovalsDetail().total;
}

export function usePendingApprovalsDetail(): { total: number; forMe: number } {
  const res = useApprovalsPending();
  const tick = useStatsTick();
  const items = res.data?.items ?? [];
  const listed = res.data ? (res.data.counts?.pending ?? items.filter((a) => a.status === 'pending').length) : null;
  const total = listed !== null && !res.isMock ? listed : (tick?.approvals_pending ?? listed ?? 0);
  const forMe = items.filter((a) => a.status === 'pending' && a.can_vote).length;
  return { total, forMe: Math.min(forMe, total) };
}
