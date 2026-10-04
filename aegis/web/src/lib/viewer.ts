// "View as" store (no React provider): read via useSyncExternalStore in api/hooks.ts and directly by
// api/client.ts + api/sse.ts. Boot: ?view_as= (then removed from the URL) -> localStorage 'aegis.viewAs'
// -> null (server default viewer, AEGIS_DEFAULT_VIEWER = u_katarzyna). Owner: dashboard-shell (B16).
import { readString, STORAGE_KEYS, writeString } from './storage';

type Listener = () => void;

let current: string | null = boot();
let epoch = 0;
const listeners = new Set<Listener>();

function boot(): string | null {
  try {
    const url = new URL(window.location.href);
    const q = url.searchParams.get('view_as');
    if (q) {
      writeString(STORAGE_KEYS.viewAs, q);
      url.searchParams.delete('view_as');
      window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash);
      return q;
    }
  } catch {
    /* no window / bad URL */
  }
  return readString(STORAGE_KEYS.viewAs);
}

export function getViewer(): string | null {
  return current;
}

/** Monotonic counter bumped on every viewer change (cache keys, in-flight aborts). */
export function getViewerEpoch(): number {
  return epoch;
}

export function setViewer(id: string | null): void {
  if (id === current) return;
  current = id;
  epoch += 1;
  writeString(STORAGE_KEYS.viewAs, id);
  listeners.forEach((l) => l());
}

export function subscribeViewer(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
