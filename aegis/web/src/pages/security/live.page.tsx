// /security/live — every model, tool, MCP and egress decision as it happens (SSE), URL-synced filters,
// row → decision trace drawer (?d=<id>), pause buffer, keyboard j/k/Enter.
import { History, Pause, Play, Radio } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { DecisionSummary } from '@/api/types';
import { EmptyState, LiveDot, PageHeader, Panel, StatusDot } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { DecisionDrawer } from '@/components/security/decision';
import { useAgentsIndex } from '@/components/security/hooks';
import { filterToParams, isFilterActive, paramsToFilter } from '@/components/security/lib/filters';
import { AuditChainStatus, DecisionFeedTable, FEED_CAP, FeedFilters, LiveCounters, useFeedItems } from '@/components/security/live';
import type { DecisionFilter } from '@/components/security/types';
import { fmtNum } from '@/lib/format';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/security/live',
  title: 'Live decisions',
  icon: 'Activity',
  section: 'Security',
  order: 10,
  badge: 'live',
  shortcut: 'g l',
  description: 'Every model, tool, MCP and egress decision as it happens',
};

function isTyping(): boolean {
  const el = document.activeElement as HTMLElement | null;
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable);
}

export default function LiveDecisionsPage() {
  const [params, setParams] = useSearchParams();
  const filter = useMemo(() => paramsToFilter(params), [params]);
  const openId = params.get('d');
  const feed = useFeedItems(filter);
  const { paused, setPaused } = feed;
  const { agents } = useAgentsIndex();
  const [cursorIdx, setCursorIdx] = useState(-1);
  const [hint, setHint] = useState<DecisionSummary | null>(null);

  const setFilter = useCallback(
    (f: DecisionFilter) => setParams((p) => filterToParams(f, p), { replace: true }),
    [setParams],
  );
  const open = useCallback(
    (d: DecisionSummary) => {
      setHint(d);
      setParams(
        (p) => {
          const n = new URLSearchParams(p);
          n.set('d', d.id);
          return n;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  const close = useCallback(() => {
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        n.delete('d');
        return n;
      },
      { replace: true },
    );
    // return focus to the row
    const id = openId;
    if (id) setTimeout(() => (document.querySelector(`[data-id="${CSS.escape(id)}"]`) as HTMLElement | null)?.focus(), 50);
  }, [setParams, openId]);

  // keyboard: j/k move, Enter opens, Esc handled by the drawer, space toggles pause
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (openId || isTyping() || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'j' || e.key === 'k') {
        e.preventDefault();
        setCursorIdx((i) => {
          const next = Math.max(0, Math.min(feed.rows.length - 1, i + (e.key === 'j' ? 1 : -1)));
          const id = feed.rows[next]?.id;
          if (id) (document.querySelector(`[data-id="${CSS.escape(id)}"]`) as HTMLElement | null)?.scrollIntoView({ block: 'nearest' });
          return next;
        });
      } else if (e.key === 'Enter' && cursorIdx >= 0 && feed.rows[cursorIdx]) {
        open(feed.rows[cursorIdx]);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [openId, feed.rows, cursorIdx, open]);

  const drawerHint = hint && hint.id === openId ? hint : (feed.all.find((d) => d.id === openId) ?? null);
  const selectedId = openId ?? feed.rows[cursorIdx]?.id ?? null;
  const filtered = isFilterActive(filter);

  return (
    <div>
      <PageHeader
        title="Live decisions"
        icon="Activity"
        subtitle="Every prompt, response, tool call, MCP message and egress request — decided in-line, explained, and hash-chained."
        actions={
          <div className="flex items-center gap-2">
            {paused && feed.bufferedCount > 0 ? (
              <button
                type="button"
                onClick={() => setPaused(false)}
                className="inline-flex h-7 items-center gap-1.5 rounded-full border border-accent-fg/40 bg-brand/15 px-3 text-xs font-medium text-text-1 shadow-raised"
              >
                {feed.bufferedCount} new ↑
              </button>
            ) : null}
            <Button variant={paused ? 'secondary' : 'ghost'} size="sm" onClick={() => setPaused(!paused)} aria-pressed={paused}>
              {paused ? <Play /> : <Pause />}
              {paused ? 'Paused' : 'Live'}
              <LiveDot paused={paused} tone={feed.connected ? 'good' : 'bad'} className="ml-1" />
            </Button>
          </div>
        }
      />
      <div className="mb-3">
        <LiveCounters items={feed.all} />
      </div>
      <Panel flush isMock={feed.isMock} className="overflow-hidden">
        <div className="border-b border-border-subtle px-4 py-3">
          <FeedFilters
            filter={filter}
            onChange={setFilter}
            items={feed.all}
            agents={agents}
            right={
              filtered ? (
                <Button variant="ghost" size="sm" onClick={() => void feed.searchHistory()} disabled={feed.searching}>
                  <History /> {feed.searching ? 'Searching…' : 'Search history'}
                </Button>
              ) : null
            }
          />
        </div>
        <div className="max-h-[calc(100vh-330px)] min-h-[360px] overflow-y-auto">
          {feed.loading ? (
            <div className="space-y-1 p-4">
              {Array.from({ length: 10 }, (_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : (
            <DecisionFeedTable
              rows={feed.rows}
              isNew={feed.isNew}
              selectedId={selectedId}
              onOpen={open}
              empty={
                <EmptyState
                  icon={Radio}
                  title={filtered ? 'No decisions match these filters' : 'Waiting for traffic…'}
                  hint={filtered ? 'Clear a filter or search the history on the server.' : 'Send a request through the gateway, or run a preset in the Playground.'}
                />
              }
            />
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-subtle bg-surface-1/60 px-4 py-2 text-xs text-text-3">
          <span>
            Showing <b className="font-medium text-text-2">{fmtNum(feed.rows.length)}</b> of {fmtNum(feed.total)}
            {feed.rows.length >= FEED_CAP ? ` (capped at ${FEED_CAP})` : ''}
          </span>
          <StatusDot status={feed.connected ? 'ok' : 'error'} pulse={feed.connected && !paused} label={feed.connected ? (paused ? 'stream paused' : 'stream live') : 'offline — retrying'} />
          <AuditChainStatus />
          <span className="hidden text-text-4 lg:inline">j / k to move · Enter to open</span>
          {feed.nextCursor ? (
            <Button variant="ghost" size="xs" className="ml-auto" onClick={() => void feed.loadOlder()} disabled={feed.loadingOlder}>
              {feed.loadingOlder ? 'Loading…' : 'Load older'}
            </Button>
          ) : null}
        </div>
      </Panel>
      <DecisionDrawer decisionId={openId} open={Boolean(openId)} onOpenChange={(o) => (o ? undefined : close())} hint={drawerHint} />
    </div>
  );
}
