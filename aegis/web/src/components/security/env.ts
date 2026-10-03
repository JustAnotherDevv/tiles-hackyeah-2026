// Forced-mock detection + mock scenario switch for the Security pages.
// ?mock=1 / VITE_AEGIS_MOCK=1 force mocks (shell semantics); ?scenario=tamper|broken|rugpull|disabled picks a mock variant.
import { isMockForced as shellMockForced } from '@/lib/mockMode';

export function isMockForced(): boolean {
  try {
    return shellMockForced();
  } catch {
    return import.meta.env.VITE_AEGIS_MOCK === '1';
  }
}

export type MockScenario = 'tamper' | 'broken' | 'rugpull' | 'disabled' | null;

export function mockScenario(): MockScenario {
  try {
    const s = new URLSearchParams(window.location.search).get('scenario');
    return s === 'tamper' || s === 'broken' || s === 'rugpull' || s === 'disabled' ? s : null;
  } catch {
    return null;
  }
}
