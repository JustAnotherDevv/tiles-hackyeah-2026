// Shared SSE hub for GET /api/events (CONTRACTS §6.3, docs/plan/15 §2.6). Owner: dashboard-shell (B16).
//
// - ONE EventSource for the whole app, ref-counted by subscribers (StrictMode-safe: closing is deferred).
// - Status store: connecting | live | reconnecting | offline | mock (| idle before the first subscriber).
// - Native auto-reconnect keeps Last-Event-ID; on a hard error or no message (incl. heartbeat) for 35 s the
//   hub reconnects manually with backoff 1 → 2 → 5 → 10 s; after 3 failures the status is `offline`
//   (still retrying). Viewer change (view as) → close + reopen with the new ?view_as=.
// - Forced mocks (?mock=1 / VITE_AEGIS_MOCK=1) → no EventSource; mocks/shell/pump.ts emits synthetic events.
//   No synthetic events ever in unforced mode (contract).
// - Messages that arrive in the first ~1.5 s after (re)connecting are flagged `replay` (server replays the
//   ring buffer) so toasts are not re-shown for old events; data consumers still get them.
import { isMockForced } from '@/lib/mockMode';
import { getViewer, subscribeViewer } from '@/lib/viewer';
import { startMockPump } from '@/mocks/shell/pump';
import { apiUrl } from './client';
import type { SseEventMap, SseEventName } from './types';

export const SSE_EVENTS: readonly SseEventName[] = [
  'decision',
  'approval.created',
  'approval.updated',
  'budget.updated',
  'budget.threshold',
  'policy.applied',
  'policy.rejected',
  'feed.updated',
  'feed.rejected',
  'killswitch',
  'mcp.tool',
  'org.updated',
  'stats',
  'system',
  'heartbeat',
] as const;

export type SseStatus = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'offline' | 'mock';

export interface SseMeta {
  /** true for messages replayed from the server ring buffer right after (re)connecting */
  replay: boolean;
  /** SSE `id:` field (bus id) when present */
  id: string | null;
}

export type SseHandler = <K extends SseEventName>(name: K, data: SseEventMap[K], meta: SseMeta) => void;

interface Sub {
  names: Set<SseEventName>;
  handler: SseHandler;
}

const STALE_MS = 35_000;
const BACKOFF_MS = [1000, 2000, 5000, 10_000];
const REPLAY_WINDOW_MS = 1500;
const CLOSE_GRACE_MS = 1500;

class EventHub {
  private es: EventSource | null = null;
  private stopPump: (() => void) | null = null;
  private subs = new Set<Sub>();
  private statusListeners = new Set<() => void>();
  private failures = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private closeTimer: ReturnType<typeof setTimeout> | null = null;
  private staleTimer: ReturnType<typeof setInterval> | null = null;
  private openedAt = 0;
  /** last SSE message id seen (resume point) and its value when the current connection opened */
  private lastId: number | null = null;
  private idAtConnect: number | null = null;
  status: SseStatus = 'idle';
  /** epoch ms of the last message received (any event incl. heartbeat) */
  lastEventAt: number | null = null;
  /** epoch ms when the status last changed */
  statusSince = Date.now();
  /** events received since page load */
  received = 0;

  constructor() {
    subscribeViewer(() => {
      if (this.es || this.retryTimer) this.reconnect(false);
    });
  }

  /** Subscribe to some events (empty list = all). Returns an unsubscribe function. */
  subscribe(names: readonly SseEventName[], handler: SseHandler): () => void {
    const sub: Sub = { names: new Set(names), handler };
    this.subs.add(sub);
    if (this.closeTimer) {
      clearTimeout(this.closeTimer);
      this.closeTimer = null;
    }
    this.ensureOpen();
    return () => {
      this.subs.delete(sub);
      if (this.subs.size === 0 && !this.closeTimer) {
        this.closeTimer = setTimeout(() => {
          this.closeTimer = null;
          if (this.subs.size === 0) this.close();
        }, CLOSE_GRACE_MS);
      }
    };
  }

  onStatus(listener: () => void): () => void {
    this.statusListeners.add(listener);
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  /** Force a reconnect now (e.g. "Retry" button). */
  retryNow(): void {
    this.failures = 0;
    this.reconnect(false);
  }

  /** Dispatch a synthetic event (used by the forced-mock pump only). */
  inject<K extends SseEventName>(name: K, data: SseEventMap[K]): void {
    if (this.status !== 'mock') return;
    this.deliver(name, data, { replay: false, id: null });
  }

  private ensureOpen(): void {
    if (this.es || this.stopPump || this.retryTimer) return;
    this.connect();
  }

  private setStatus(s: SseStatus): void {
    if (this.status === s) return;
    this.status = s;
    this.statusSince = Date.now();
    this.statusListeners.forEach((l) => l());
  }

  private connect(): void {
    this.retryTimer = null;
    if (isMockForced()) {
      this.setStatus('mock');
      this.stopPump = startMockPump((name, data) => this.inject(name, data));
      return;
    }
    // First connect: replay the last 100 ring-buffer messages. Reconnects (network blip, viewer switch) resume
    // after the last id we saw, so already-handled events are not re-delivered (no duplicate side effects).
    const qs = this.lastId !== null ? new URLSearchParams({ last_event_id: String(this.lastId) }) : new URLSearchParams({ replay: '100' });
    this.idAtConnect = this.lastId;
    const viewer = getViewer();
    if (viewer) qs.set('view_as', viewer);
    this.setStatus(this.failures > 0 ? (this.failures >= 3 ? 'offline' : 'reconnecting') : 'connecting');
    let es: EventSource;
    try {
      es = new EventSource(apiUrl(`/api/events?${qs.toString()}`));
    } catch {
      this.scheduleRetry();
      return;
    }
    this.es = es;
    this.openedAt = Date.now();
    es.onopen = () => {
      this.failures = 0;
      this.openedAt = Date.now();
      this.lastEventAt = Date.now();
      this.setStatus('live');
    };
    es.onerror = () => {
      // CONNECTING = the browser is auto-reconnecting (keeps Last-Event-ID); CLOSED = gave up (HTTP error).
      if (es.readyState === EventSource.CLOSED) {
        this.teardownSource();
        this.scheduleRetry();
      } else {
        this.setStatus('reconnecting');
      }
    };
    for (const name of SSE_EVENTS) {
      es.addEventListener(name, (ev: MessageEvent<string>) => this.onMessage(name, ev));
    }
    if (!this.staleTimer) {
      this.staleTimer = setInterval(() => {
        if (this.status === 'mock' || !this.es) return;
        const last = this.lastEventAt ?? this.openedAt;
        if (Date.now() - last > STALE_MS) this.reconnect(true);
      }, 5000);
    }
  }

  private onMessage(name: SseEventName, ev: MessageEvent<string>): void {
    this.lastEventAt = Date.now();
    if (this.status !== 'live') {
      this.failures = 0;
      this.setStatus('live');
    }
    let data: unknown;
    try {
      data = JSON.parse(ev.data);
    } catch {
      return;
    }
    const replay = Date.now() - this.openedAt < REPLAY_WINDOW_MS;
    const n = ev.lastEventId ? Number(ev.lastEventId) : NaN;
    if (Number.isFinite(n)) {
      // backlog duplicates of something already delivered before this connection: drop
      if (replay && this.idAtConnect !== null && n <= this.idAtConnect) return;
      this.lastId = n; // last seen (not max: a restarted gateway starts its ids again from 1)
    }
    this.deliver(name, data as SseEventMap[typeof name], { replay, id: ev.lastEventId || null });
  }

  private deliver<K extends SseEventName>(name: K, data: SseEventMap[K], meta: SseMeta): void {
    this.received += 1;
    if (this.status === 'mock') this.lastEventAt = Date.now();
    for (const sub of [...this.subs]) {
      if (sub.names.size === 0 || sub.names.has(name)) {
        try {
          sub.handler(name, data, meta);
        } catch (err) {
          console.error('[aegis] sse handler failed', name, err);
        }
      }
    }
  }

  private scheduleRetry(): void {
    if (this.subs.size === 0) {
      this.setStatus('idle');
      return;
    }
    const delay = BACKOFF_MS[Math.min(this.failures, BACKOFF_MS.length - 1)];
    this.failures += 1;
    this.setStatus(this.failures >= 3 ? 'offline' : 'reconnecting');
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }

  private teardownSource(): void {
    if (this.es) {
      this.es.onopen = null;
      this.es.onerror = null;
      this.es.close();
    }
    this.es = null;
  }

  private reconnect(asFailure: boolean): void {
    this.teardownSource();
    if (this.stopPump) {
      this.stopPump();
      this.stopPump = null;
    }
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    if (this.subs.size === 0) return;
    if (asFailure) this.scheduleRetry();
    else this.connect();
  }

  private close(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    if (this.staleTimer) clearInterval(this.staleTimer);
    this.staleTimer = null;
    this.teardownSource();
    if (this.stopPump) {
      this.stopPump();
      this.stopPump = null;
    }
    this.setStatus('idle');
  }
}

export const eventHub = new EventHub();
