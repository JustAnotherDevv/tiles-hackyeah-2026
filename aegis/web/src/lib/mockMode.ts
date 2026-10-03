// Forced-mock switch (CONTRACTS §5.4): VITE_AEGIS_MOCK=1 or ?mock=1 (persisted per tab; ?mock=0 clears).
// Owner: dashboard-shell (scaffold seed).
const KEY = 'aegis.mock';

function readQuery(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('mock');
  } catch {
    return null;
  }
}

export function isMockForced(): boolean {
  if (import.meta.env.VITE_AEGIS_MOCK === '1') return true;
  const q = readQuery();
  try {
    if (q === '1') sessionStorage.setItem(KEY, '1');
    if (q === '0') sessionStorage.removeItem(KEY);
    return sessionStorage.getItem(KEY) === '1';
  } catch {
    return q === '1';
  }
}

export function setMockForced(on: boolean): void {
  try {
    if (on) sessionStorage.setItem(KEY, '1');
    else sessionStorage.removeItem(KEY);
  } catch {
    /* storage unavailable */
  }
}
