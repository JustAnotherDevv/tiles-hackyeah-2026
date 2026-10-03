// "View as" store (no React provider): read via useSyncExternalStore in api/hooks.ts and directly by
// api/client.ts + api/sse.ts. Boot: ?view_as= -> localStorage 'aegis.viewAs' -> null (server default).
// Owner: dashboard-shell (scaffold seed).
const KEY = 'aegis.viewAs';
type Listener = () => void;

let current: string | null = boot();
const listeners = new Set<Listener>();

function boot(): string | null {
  try {
    const q = new URLSearchParams(window.location.search).get('view_as');
    if (q) {
      localStorage.setItem(KEY, q);
      return q;
    }
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function getViewer(): string | null {
  return current;
}

export function setViewer(id: string | null): void {
  if (id === current) return;
  current = id;
  try {
    if (id) localStorage.setItem(KEY, id);
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable */
  }
  listeners.forEach((l) => l());
}

export function subscribeViewer(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
