// Mock GET /api/coverage: OWASP LLM 2026 / Agentic ASI / MCP 2025 matrix derived from control state.
// Owner: dashboard-security.
import type { ControlView, CoverageResponse } from '@/api/types';
import { mockControls } from './controls';

type Item = [id: string, name: string, controls: string[]];

const LLM: Item[] = [
  ['LLM01:2026', 'Prompt injection', ['INJ-01', 'INJ-02', 'SIG-01']],
  ['LLM02:2026', 'Sensitive information disclosure', ['DLP-01', 'DLP-02', 'DLP-03', 'DLP-07']],
  ['LLM03:2026', 'Supply chain', ['SIG-01', 'SIG-03', 'GOV-02']],
  ['LLM04:2026', 'Data & model poisoning', ['SIG-02']],
  ['LLM05:2026', 'Improper output handling', ['DLP-05', 'DLP-06']],
  ['LLM06:2026', 'Excessive agency', ['GOV-03', 'GOV-04', 'ACT-01']],
  ['LLM07:2026', 'System prompt leakage', ['INJ-04']],
  ['LLM08:2026', 'Vector & embedding weaknesses', []],
  ['LLM09:2026', 'Misinformation', ['INJ-03']],
  ['LLM10:2026', 'Unbounded consumption', ['BUD-01', 'BUD-02', 'EXE-04']],
];
const ASI: Item[] = [
  ['ASI01', 'Agent goal hijack', ['INJ-05', 'EXE-03']],
  ['ASI02', 'Tool misuse & exploitation', ['GOV-03', 'ACT-01', 'ACT-02', 'ACT-03', 'EXE-02']],
  ['ASI03', 'Identity & privilege abuse', ['GOV-01']],
  ['ASI04', 'Agentic supply chain', ['SIG-03', 'SIG-01']],
  ['ASI05', 'Unexpected code execution', ['EXE-01', 'ACT-04']],
  ['ASI06', 'Memory & context poisoning', ['INJ-01']],
  ['ASI07', 'Insecure inter-agent communication', []],
  ['ASI08', 'Cascading failures', ['EXE-04']],
  ['ASI09', 'Human-agent trust exploitation', ['GOV-04', 'GOV-05']],
  ['ASI10', 'Rogue agents', ['EXE-04', 'GOV-01']],
];
const MCP: Item[] = [
  ['MCP01:2025', 'Token mismanagement & secret exposure', ['MCP-04', 'DLP-02']],
  ['MCP02:2025', 'Privilege escalation via scope creep', ['GOV-03']],
  ['MCP03:2025', 'Tool poisoning', ['MCP-02', 'MCP-03']],
  ['MCP04:2025', 'Software supply chain', ['SIG-03']],
  ['MCP05:2025', 'Command injection & execution', ['EXE-01']],
  ['MCP06:2025', 'Intent-flow subversion / rug pull', ['MCP-03']],
  ['MCP07:2025', 'Insufficient authentication', ['MCP-04']],
  ['MCP08:2025', 'Lack of audit & telemetry', ['GOV-01']],
  ['MCP09:2025', 'Shadow MCP servers', ['MCP-01']],
  ['MCP10:2025', 'Context injection & over-sharing', ['DLP-01', 'INJ-01']],
];

function status(controls: string[], byId: Map<string, ControlView>): CoverageResponse['frameworks'][number]['items'][number]['status'] {
  if (!controls.length) return 'uncovered';
  let enforce = 0;
  let monitor = 0;
  let off = 0;
  for (const id of controls) {
    const c = byId.get(id);
    if (!c || !c.enabled || c.mode === 'off') off++;
    else if (c.mode === 'monitor' || !c.implemented) monitor++;
    else enforce++;
  }
  if (off > 0) return 'disabled'; // F7: a disabled mapped control is shown, never hidden
  if (enforce === 0 || monitor > 0) return 'partial';
  return 'covered';
}

/** Coverage computed from (mock) control state; pass live controls to recompute after a policy change. */
export function mockCoverage(controls?: ControlView[]): CoverageResponse {
  const byId = new Map((controls ?? mockControls().items).map((c) => [c.id, c]));
  const fw = (id: string, name: string, items: Item[]) => ({
    id,
    name,
    items: items.map(([iid, iname, ctl]) => ({ id: iid, name: iname, status: status(ctl, byId), controls: ctl })),
  });
  return {
    frameworks: [
      fw('OWASP-LLM-2026', 'OWASP Top 10 for LLM apps 2026', LLM),
      fw('OWASP-ASI-2026', 'OWASP Agentic Security (ASI) 2026', ASI),
      fw('OWASP-MCP-2025', 'OWASP MCP Top 10 2025', MCP),
    ],
  };
}
