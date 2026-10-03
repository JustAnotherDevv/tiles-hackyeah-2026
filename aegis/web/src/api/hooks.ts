// Data hooks for pages (CONTRACTS §5.4 "Shared shell API"). Names and signatures are binding.
// Owner: dashboard-shell (scaffold seed — SWR cache, batching and extras come later).
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ViewRole } from '@/lib/page';
import { getViewer, setViewer, subscribeViewer } from '@/lib/viewer';
import { mockMembers } from '@/mocks/shell/org';
import { api, isApiRequestError } from './client';
import { eventHub, type SseStatus } from './sse';
import type { ApprovalsResponse, DecisionSummary, Member, Page, SseEventMap, SseEventName } from './types';

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
  refresh: () => void;
}

/** Viewer id (re-renders on "view as" changes). */
export function useViewerId(): string | null {
  return useSyncExternalStore(subscribeViewer, getViewer, getViewer);
}

export function useApi<T>(path: string | null, opts: UseApiOptions<T> = {}): UseApiResult<T> {
  const viewer = useViewerId();
  const [state, setState] = useState<{ data: T | undefined; error: Error | null; loading: boolean; isMock: boolean }>({
    data: undefined,
    error: null,
    loading: path !== null,
    isMock: false,
  });
  const [tick, setTick] = useState(0);
  const mockRef = useRef(opts.mock);
  mockRef.current = opts.mock;
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (path === null) return;
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    api
      .get<T>(path, mockRef.current)
      .then((r) => !cancelled && setState({ data: r.data, error: null, loading: false, isMock: r.isMock }))
      .catch((e: unknown) => {
        if (cancelled) return;
        const error = e instanceof Error ? e : new Error(String(e));
        setState((s) => ({ ...s, error, loading: false }));
        if (!isApiRequestError(e)) console.warn('useApi failed', path, e);
      });
    return () => {
      cancelled = true;
    };
  }, [path, viewer, tick]);

  useEffect(() => {
    if (!opts.refreshMs || path === null) return;
    const id = setInterval(refresh, opts.refreshMs);
    return () => clearInterval(id);
  }, [opts.refreshMs, path, refresh]);

  const refreshOnKey = (opts.refreshOn ?? []).join(',');
  useEffect(() => {
    if (!refreshOnKey || path === null) return;
    return eventHub.subscribe(refreshOnKey.split(',') as SseEventName[], () => refresh());
  }, [refreshOnKey, path, refresh]);

  return { ...state, refresh };
}

/** Subscribe to SSE events for the lifetime of the component. */
export function useEvents(
  names: SseEventName[],
  handler: <K extends SseEventName>(name: K, data: SseEventMap[K]) => void,
): void {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  const key = names.join(',');
  useEffect(() => {
    return eventHub.subscribe(key.split(',') as SseEventName[], (name, data) => handlerRef.current(name, data));
  }, [key]);
}

export function useSseStatus(): SseStatus {
  return useSyncExternalStore(
    (l) => eventHub.onStatus(l),
    () => eventHub.status,
    () => eventHub.status,
  );
}

// ---------------------------------------------------------------- live decisions (shared ring buffer)
const MAX_DECISIONS = 500;
let decisions: DecisionSummary[] = [];
const decisionListeners = new Set<() => void>();
let backfilled = false;

function pushDecision(d: DecisionSummary): void {
  if (decisions.some((x) => x.id === d.id)) return;
  decisions = [d, ...decisions].slice(0, MAX_DECISIONS);
  decisionListeners.forEach((l) => l());
}

export function useLiveDecisions(limit = 200): { items: DecisionSummary[]; connected: boolean } {
  const items = useSyncExternalStore(
    (l) => {
      decisionListeners.add(l);
      return () => decisionListeners.delete(l);
    },
    () => decisions,
    () => decisions,
  );
  const status = useSseStatus();
  useEffect(() => {
    if (!backfilled) {
      backfilled = true;
      api
        .get<Page<DecisionSummary>>('/api/decisions?limit=50', () => ({ items: [] }))
        .then((r) => [...r.data.items].reverse().forEach(pushDecision))
        .catch(() => undefined);
    }
    return eventHub.subscribe(['decision'], (_name, data) => pushDecision(data as DecisionSummary));
  }, []);
  return { items: items.slice(0, limit), connected: status === 'live' || status === 'mock' };
}

// ---------------------------------------------------------------- view as
export function useViewAs(): { member: Member | null; role: ViewRole; members: Member[]; setViewAs: (id: string) => void } {
  const viewer = useViewerId();
  const { data } = useApi<{ items: Member[] }>('/api/members', { mock: mockMembers, refreshOn: ['org.updated'] });
  const members = data?.items ?? [];
  const member = members.find((m) => m.id === viewer) ?? members.find((m) => m.role === 'owner') ?? null;
  return { member, role: member?.role ?? 'owner', members, setViewAs: setViewer };
}

export function usePendingApprovals(): number {
  const { data } = useApi<ApprovalsResponse>('/api/approvals?status=pending', {
    mock: () => ({ items: [], counts: { pending: 0, approved: 0, denied: 0, expired: 0, cancelled: 0 } }),
    refreshOn: ['approval.created', 'approval.updated'],
  });
  return data?.counts?.pending ?? data?.items.length ?? 0;
}
