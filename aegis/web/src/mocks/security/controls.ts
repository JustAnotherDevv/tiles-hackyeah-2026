// Mock GET /api/controls, GET /healthz (security view of them).
// Owner: dashboard-security.
import type { ControlView, HealthResponse } from '@/api/types';
import { mockScenario } from '@/components/security/env';
import { FALLBACK_CONTROLS } from '@/components/security/lib/catalog';
import { MOCK_FEED_SERIAL, MOCK_POLICY_VERSION } from './decisions';
import { hashString, mulberry32, round } from './rng';

const P95: Record<string, number> = {
  'GOV-01': 0.06, 'EXE-04': 0.12, 'GOV-02': 0.05, 'GOV-03': 0.08, 'GOV-04': 0.07, 'GOV-05': 0.4, 'ACT-01': 0.18,
  'ACT-02': 0.22, 'ACT-03': 0.15, 'ACT-04': 0.11, 'DLP-01': 0.71, 'DLP-02': 0.38, 'DLP-03': 0.14, 'DLP-04': 0.52,
  'DLP-05': 0.29, 'DLP-06': 0.21, 'DLP-07': 19.4, 'DLP-08': 0.09, 'INJ-01': 0.33, 'INJ-02': 13.1, 'INJ-03': 46.2,
  'INJ-04': 1.2, 'INJ-05': 2.4, 'EXE-01': 0.19, 'EXE-02': 0.1, 'EXE-03': 0.16, 'MCP-01': 0.05, 'MCP-02': 5.4,
  'MCP-03': 0.41, 'MCP-04': 0.07, 'BUD-01': 0.13, 'BUD-02': 0.06, 'SIG-01': 0.36, 'SIG-02': 0.9, 'SIG-03': 0.12,
  'CUS-01': 0.62,
};

export function mockControls(): { items: ControlView[] } {
  const disabled = mockScenario() === 'disabled' ? new Set(['DLP-02']) : new Set<string>();
  return {
    items: FALLBACK_CONTROLS.map((c) => {
      const r = mulberry32(hashString(c.id));
      const hits = Math.round(r() * (c.action === 'block' ? 40 : 180));
      return {
        id: c.id,
        family: c.family,
        name: c.name,
        kind: c.kind,
        owner: c.owner,
        enabled: !disabled.has(c.id),
        mode: disabled.has(c.id) ? 'off' : (c.mode ?? 'enforce'),
        action: c.action ?? 'block',
        threshold: c.threshold ?? null,
        severity: c.action === 'block' ? 'high' : 'medium',
        owasp: c.owasp ?? [],
        surfaces: c.surfaces,
        implemented: c.id !== 'MCP-04' && c.id !== 'INJ-05',
        hits_24h: hits,
        blocks_24h: c.action === 'block' ? Math.round(hits * (0.3 + r() * 0.5)) : 0,
        p95_ms: P95[c.id] ?? round(0.1 + r(), 2),
      };
    }),
  };
}

export function mockHealth(): HealthResponse {
  return {
    status: 'ok',
    version: '0.1.0',
    uptime_s: 5400,
    policy_version: MOCK_POLICY_VERSION,
    feed_serial: mockScenario() === 'tamper' ? MOCK_FEED_SERIAL : MOCK_FEED_SERIAL,
    components: { pipeline: 'ok', policy: 'ok', feed: mockScenario() === 'tamper' ? 'degraded' : 'ok', audit: 'ok', semantic: 'degraded', ledger: 'ok' },
  };
}
