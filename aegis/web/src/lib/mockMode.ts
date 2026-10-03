// Forced-mock switch (CONTRACTS §5.4): VITE_AEGIS_MOCK=1 or ?mock=1 (persisted per tab in sessionStorage;
// ?mock=0 clears). Forced mocks short-circuit the network for calls that pass a mock factory and attach the
// synthetic SSE pump (mocks/shell/pump.ts) — never in unforced mode. Owner: dashboard-shell (B16).
import { readString, STORAGE_KEYS, writeString } from './storage';

let cached: boolean | null = null;

function readQuery(name: string): string | null {
  try {
    return new URLSearchParams(window.location.search).get(name);
  } catch {
    return null;
  }
}

export function isMockForced(): boolean {
  if (cached !== null) return cached;
  if (import.meta.env.VITE_AEGIS_MOCK === '1') return (cached = true);
  const q = readQuery('mock');
  if (q === '1') writeString(STORAGE_KEYS.mock, '1', 'session');
  if (q === '0') writeString(STORAGE_KEYS.mock, null, 'session');
  cached = readString(STORAGE_KEYS.mock, null, 'session') === '1';
  return cached;
}

/** Persist the forced-mock flag for this tab; takes effect after reload. */
export function setMockForced(on: boolean): void {
  writeString(STORAGE_KEYS.mock, on ? '1' : null, 'session');
  cached = null;
}

/** ?mockRate=<events per second> for burst tests of the pump (forced mocks only). */
export function mockRate(): number | null {
  const v = Number(readQuery('mockRate'));
  return Number.isFinite(v) && v > 0 ? Math.min(v, 200) : null;
}
