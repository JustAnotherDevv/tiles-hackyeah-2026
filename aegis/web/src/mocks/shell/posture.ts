// Minimal mocks for posture inputs (controls, coverage, feed status, audit verify). Only for shell use —
// dashboard-security/governance keep their own rich mocks. Owner: dashboard-shell (B16).
import type { AuditVerifyResult, ControlView, CoverageResponse, FeedStatus } from '@/api/types';

const IDS: [string, ControlView['kind']][] = [
  ['GOV-01', 'deterministic'], ['GOV-02', 'deterministic'], ['GOV-03', 'deterministic'], ['GOV-04', 'deterministic'],
  ['ACT-01', 'deterministic'], ['ACT-02', 'deterministic'], ['ACT-03', 'deterministic'], ['ACT-04', 'deterministic'],
  ['GOV-05', 'deterministic'], ['DLP-01', 'deterministic'], ['DLP-02', 'deterministic'], ['DLP-03', 'deterministic'],
  ['DLP-04', 'hybrid'], ['DLP-05', 'deterministic'], ['DLP-06', 'deterministic'], ['DLP-07', 'semantic'],
  ['DLP-08', 'deterministic'], ['INJ-01', 'deterministic'], ['INJ-02', 'semantic'], ['INJ-03', 'semantic'],
  ['INJ-04', 'hybrid'], ['INJ-05', 'hybrid'], ['EXE-01', 'deterministic'], ['EXE-02', 'deterministic'],
  ['EXE-03', 'stateful'], ['EXE-04', 'stateful'], ['MCP-01', 'deterministic'], ['MCP-02', 'hybrid'],
  ['MCP-03', 'stateful'], ['MCP-04', 'deterministic'], ['BUD-01', 'deterministic'], ['BUD-02', 'deterministic'],
  ['SIG-01', 'deterministic'], ['SIG-02', 'deterministic'], ['SIG-03', 'deterministic'], ['CUS-01', 'hybrid'],
];

export function mockControls(): { items: ControlView[] } {
  return {
    items: IDS.map(([id, kind]) => ({
      id,
      family: id.split('-')[0],
      name: id,
      kind,
      owner: 'mock',
      enabled: true,
      mode: id === 'INJ-05' || id === 'MCP-04' ? 'monitor' : 'enforce',
      action: 'block',
      threshold: kind === 'semantic' ? 0.9 : null,
      severity: 'high',
      owasp: [],
      surfaces: [],
      implemented: true,
      hits_24h: 0,
      blocks_24h: 0,
      p95_ms: null,
    })),
  };
}

export function mockCoverage(): CoverageResponse {
  const mk = (prefix: string, n: number, suffix: string, partial: number[], uncovered: number[] = []) =>
    Array.from({ length: n }, (_, i) => {
      const num = String(i + 1).padStart(2, '0');
      const status: CoverageResponse['frameworks'][number]['items'][number]['status'] = uncovered.includes(i + 1) ? 'uncovered' : partial.includes(i + 1) ? 'partial' : 'covered';
      return { id: `${prefix}${num}${suffix}`, name: `${prefix}${num}`, status, controls: [] };
    });
  return {
    frameworks: [
      { id: 'OWASP-LLM-2026', name: 'OWASP Top 10 for LLM Apps 2026', items: mk('LLM', 10, ':2026', [9]) },
      { id: 'OWASP-ASI-2026', name: 'OWASP Agentic Security 2026', items: mk('ASI', 10, '', [7, 10]) },
      { id: 'OWASP-MCP-2025', name: 'OWASP MCP Top 10 2025', items: mk('MCP', 10, ':2025', [8], [10]) },
    ],
  };
}

export function mockFeedStatus(): FeedStatus {
  const now = Date.now();
  return {
    feed_id: 'aegis-ti',
    url: 'http://127.0.0.1:8790/feed/bundle.json',
    status: 'ok',
    serial: 43,
    version: '2026.10.03-43',
    published: new Date(now - 42 * 60_000).toISOString(),
    expires: new Date(now + 6 * 24 * 3600_000).toISOString(),
    key_id: 'ed25519:aegis-ti-2026',
    signatures_total: 38,
    signatures_active: 34,
    signatures_monitor: 3,
    signatures_quarantined: 1,
    last_check: new Date(now - 2 * 60_000).toISOString(),
    last_update: new Date(now - 42 * 60_000).toISOString(),
    last_error: null,
    history: [
      { serial: 43, version: '2026.10.03-43', applied_at: new Date(now - 42 * 60_000).toISOString(), added: 2, removed: 0, modified: 1 },
      { serial: 42, version: '2026.10.02-42', applied_at: new Date(now - 26 * 3600_000).toISOString(), added: 4, removed: 1, modified: 0 },
    ],
  };
}

export function mockAuditVerify(): AuditVerifyResult {
  return {
    ok: true,
    records: 51_284,
    head_hash: 'ab12f9c4e07d5b3a91c2e8f4d6a7b0c3e5f1a2d4b6c8e0f2a4c6e8b0d2f4a6c8',
    broken_at_seq: null,
    files: 3,
    checked_at: new Date().toISOString(),
    message: 'Chain OK',
  };
}
