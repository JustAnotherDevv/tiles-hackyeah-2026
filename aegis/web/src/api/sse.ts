// Shared SSE hub for GET /api/events (CONTRACTS §6.3). One EventSource for the whole app,
// ref-counted, reconnect with backoff, reconnects when the viewer changes.
// Owner: dashboard-shell (scaffold seed — batching, stale detection and the mock pump come later).
import { isMockForced } from '@/lib/mockMode';
import { getViewer, subscribeViewer } from '@/lib/viewer';
import { apiUrl } from './client';
import type { SseEventMap, SseEventName } from './types';

export const SSE_EVENTS: SseEventName[] = [
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
];

export type SseStatus = 'idle' | 'connecting' | 'live' | 'offline' | 'mock';
export type SseHandler = <K extends SseEventName>(name: K, data: SseEventMap[K]) => void;

interface Sub {
  names: Set<SseEventName>;
  handler: SseHandler;
}

class EventHub {
  private es: EventSource | null = null;
  private subs = new Set<Sub>();
  private statusListeners = new Set<() => void>();
  private retry = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  status: SseStatus = 'idle';

  constructor() {
    subscribeViewer(() => {
      if (this.es) this.reconnect();
    });
  }

  subscribe(names: SseEventName[], handler: SseHandler): () => void {
    const sub: Sub = { names: new Set(names), handler };
    this.subs.add(sub);
    if (!this.es && !this.timer) this.connect();
    return () => {
      this.subs.delete(sub);
      if (this.subs.size === 0) this.close();
    };
  }

  onStatus(listener: () => void): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  private setStatus(s: SseStatus): void {
    this.status = s;
    this.statusListeners.forEach((l) => l());
  }

  private connect(): void {
    this.timer = null;
    if (isMockForced()) {
      this.setStatus('mock'); // synthetic events: dashboard-shell's mocks/shell/pump.ts
      return;
    }
    const viewer = getViewer();
    const qs = new URLSearchParams({ replay: '0' });
    if (viewer) qs.set('view_as', viewer);
    this.setStatus('connecting');
    const es = new EventSource(apiUrl(`/api/events?${qs.toString()}`));
    this.es = es;
    es.onopen = () => {
      this.retry = 0;
      this.setStatus('live');
    };
    es.onerror = () => {
      es.close();
      this.es = null;
      this.setStatus('offline');
      if (this.subs.size > 0) {
        const delay = Math.min(15000, 500 * 2 ** this.retry++);
        this.timer = setTimeout(() => this.connect(), delay);
      }
    };
    for (const name of SSE_EVENTS) {
      es.addEventListener(name, (ev: MessageEvent<string>) => this.dispatch(name, ev.data));
    }
  }

  private dispatch(name: SseEventName, raw: string): void {
    let data: unknown;
    try {
      data = JSON.parse(raw);
    } catch {
      return;
    }
    for (const sub of this.subs) {
      if (sub.names.size === 0 || sub.names.has(name)) {
        try {
          sub.handler(name, data as SseEventMap[typeof name]);
        } catch (err) {
          console.error('sse handler failed', name, err);
        }
      }
    }
  }

  private reconnect(): void {
    this.close();
    if (this.subs.size > 0) this.connect();
  }

  private close(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.es?.close();
    this.es = null;
    this.setStatus('idle');
  }
}

export const eventHub = new EventHub();
