// Live feed data: backfill (GET /api/decisions) + live SSE ring buffer (shell) + "Load older" cursor pages,
// deduped by id, newest first, capped at 300 rows. Pause freezes the visible list and buffers new ids.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { api } from '@/api/client';
import { useApi, useLiveDecisions } from '@/api/hooks';
import type { DecisionSummary, Page } from '@/api/types';
import { mockDecisionPage } from '@/mocks/security';
import { isFilterActive, matchDecision, toApiQuery } from '../lib/filters';
import type { DecisionFilter } from '../types';

export const FEED_CAP = 300;

function byTsDesc(a: DecisionSummary, b: DecisionSummary): number {
  return a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0;
}

export interface FeedItems {
  /** Visible rows (filtered, capped). */
  rows: DecisionSummary[];
  /** All known rows before filtering (for chip counts). */
  all: DecisionSummary[];
  total: number;
  /** Ids that arrived after first render (animate these only). */
  isNew: (id: string) => boolean;
  bufferedCount: number;
  paused: boolean;
  setPaused: (p: boolean) => void;
  connected: boolean;
  isMock: boolean;
  loading: boolean;
  nextCursor: string | null;
  loadOlder: () => Promise<void>;
  loadingOlder: boolean;
  /** Server-side history search results (UIX-14) — merged into `all` when present. */
  searchHistory: () => Promise<void>;
  searching: boolean;
  /** Backfill (GET /api/decisions) failure, if any — the SSE rows may still be flowing. */
  error: Error | null;
  /** Re-run the backfill request. */
  retry: () => void;
}

export function useFeedItems(filter: DecisionFilter): FeedItems {
  const backfill = useApi<Page<DecisionSummary>>('/api/decisions?limit=200', { mock: () => mockDecisionPage(80) });
  const live = useLiveDecisions(FEED_CAP);
  const [older, setOlder] = useState<DecisionSummary[]>([]);
  const [cursor, setCursor] = useState<string | null | undefined>(undefined);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [searching, setSearching] = useState(false);

  const merged = useMemo(() => {
    const seen = new Set<string>();
    const out: DecisionSummary[] = [];
    for (const src of [live.items, backfill.data?.items ?? [], older]) {
      for (const d of src) {
        if (!d || seen.has(d.id)) continue;
        seen.add(d.id);
        out.push(d);
      }
    }
    out.sort(byTsDesc);
    return out.length > FEED_CAP * 2 ? out.slice(0, FEED_CAP * 2) : out;
  }, [live.items, backfill.data, older]);

  // ids present at first data load never animate
  const [mountIds] = useState(() => new Set(live.items.map((d) => d.id)));
  const backfillIds = useMemo(() => new Set((backfill.data?.items ?? []).map((d) => d.id)), [backfill.data]);
  const isNew = useCallback((id: string) => !mountIds.has(id) && !backfillIds.has(id), [mountIds, backfillIds]);

  // pause: freeze the list we show (snapshot taken on toggle)
  const [frozen, setFrozen] = useState<DecisionSummary[] | null>(null);
  const paused = frozen !== null;
  const setPaused = useCallback((p: boolean) => setFrozen(p ? merged : null), [merged]);
  const source = frozen ?? merged;
  const bufferedCount = useMemo(() => {
    if (!frozen) return 0;
    const shown = new Set(frozen.map((d) => d.id));
    return merged.reduce((n, d) => (shown.has(d.id) ? n : n + 1), 0);
  }, [frozen, merged]);

  const rows = useMemo(() => {
    const active = isFilterActive(filter);
    const out: DecisionSummary[] = [];
    for (const d of source) {
      if (active && !matchDecision(d, filter)) continue;
      out.push(d);
      if (out.length >= FEED_CAP) break;
    }
    return out;
  }, [source, filter]);

  const nextCursor = cursor === undefined ? (backfill.data?.next_cursor ?? null) : cursor;

  const loadOlder = useCallback(async () => {
    if (!nextCursor) return;
    setLoadingOlder(true);
    try {
      const r = await api.get<Page<DecisionSummary>>(`/api/decisions?limit=100&cursor=${encodeURIComponent(nextCursor)}`, () => ({ items: [], next_cursor: null }));
      setOlder((o) => [...o, ...(r.data.items ?? [])]);
      setCursor(r.data.next_cursor ?? null);
    } catch (e) {
      toast.error('Could not load older decisions', { description: e instanceof Error ? e.message : String(e) });
    } finally {
      setLoadingOlder(false);
    }
  }, [nextCursor]);

  const searchHistory = useCallback(async () => {
    setSearching(true);
    try {
      const r = await api.get<Page<DecisionSummary>>(`/api/decisions?limit=200${toApiQuery(filter)}`, () => ({ items: [], next_cursor: null }));
      const found = r.data.items ?? [];
      setOlder((o) => [...o, ...found]);
      toast.message(found.length ? `History search: ${found.length} matching decision${found.length === 1 ? '' : 's'} merged into the feed` : 'History search: no older matches');
    } catch (e) {
      toast.error('History search failed', { description: e instanceof Error ? e.message : String(e) });
    } finally {
      setSearching(false);
    }
  }, [filter]);

  // The backfill is a one-shot GET: if it failed (gateway down at page load) or was served from mocks, refetch it
  // once the live stream (re)connects, so real history replaces the gap instead of mixing with fabricated rows.
  const { refresh: refreshBackfill } = backfill;
  const backfillStale = Boolean(backfill.error) || backfill.isMock;
  useEffect(() => {
    if (live.connected && backfillStale) void refreshBackfill();
  }, [live.connected, backfillStale, refreshBackfill]);
  const retry = useCallback(() => void refreshBackfill(), [refreshBackfill]);

  return {
    rows,
    all: source,
    total: merged.length,
    isNew,
    bufferedCount,
    paused,
    setPaused,
    connected: live.connected,
    isMock: backfill.isMock,
    loading: backfill.loading && merged.length === 0,
    nextCursor,
    loadOlder,
    loadingOlder,
    searchHistory,
    searching,
    error: backfill.error,
    retry,
  };
}
