// try/catch-wrapped Web Storage helpers (private mode, blocked storage and SSR never throw).
// Owner: dashboard-shell (B16).
type Area = 'local' | 'session';

function area(kind: Area): Storage | null {
  try {
    return kind === 'local' ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readString(key: string, fallback: string | null = null, kind: Area = 'local'): string | null {
  try {
    return area(kind)?.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeString(key: string, value: string | null, kind: Area = 'local'): void {
  try {
    const s = area(kind);
    if (!s) return;
    if (value === null) s.removeItem(key);
    else s.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

export function readJson<T>(key: string, fallback: T, kind: Area = 'local'): T {
  const raw = readString(key, null, kind);
  if (raw === null) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown, kind: Area = 'local'): void {
  writeString(key, value === undefined ? null : JSON.stringify(value), kind);
}

/** Storage keys used by the shell (documented in docs/plan/15 §2.9). */
export const STORAGE_KEYS = {
  viewAs: 'aegis.viewAs',
  overviewWindow: 'aegis.overview.window',
  sidebarCollapsed: 'aegis.sidebarCollapsed',
  adminToken: 'aegis.adminToken',
  mock: 'aegis.mock',
} as const;
