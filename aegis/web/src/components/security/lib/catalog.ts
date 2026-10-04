// Fallback control catalog (CONTRACTS §4.4) used when GET /api/controls is unavailable.
// PURE module: no runtime imports (node --test runs it with native type stripping).
import type { Surface } from '@/api/types';
import type { CatalogControl, ControlKind, Phase } from '../types';

const ALL: Surface[] = [
  'prompt.user', 'model.request', 'model.response', 'model.admin',
  'tool.input', 'tool.output', 'artifact.file',
  'mcp.init', 'mcp.list', 'mcp.call', 'mcp.result',
  'egress.request', 'egress.response',
  'a2a.message', 'a2a.result',
  'config.change',
];
const OUT: Surface[] = ['prompt.user', 'model.request', 'model.admin', 'tool.input', 'mcp.init', 'mcp.call', 'egress.request', 'a2a.message'];
const INJ: Surface[] = ['prompt.user', 'model.request', 'tool.output', 'mcp.result', 'mcp.list', 'egress.response'];

type Row = [id: string, name: string, owner: string, kind: ControlKind, surfaces: Surface[], action: CatalogControl['action'], threshold: number | null, owasp: string[], description: string];

const ROWS: Row[] = [
  ['GOV-01', 'Caller identity & attribution', 'org-rbac', 'deterministic', ALL, 'log', null, ['ASI03'], 'API key → agent · sponsor · team'],
  ['EXE-04', 'Loop / rate / circuit breaker / kill switch', 'budgets-ledger', 'stateful', OUT, 'block', null, ['LLM10:2026', 'ASI08'], 'loop fingerprints · rate · kill switch'],
  ['GOV-02', 'Model allowlist & destination tiering', 'org-rbac', 'deterministic', ['model.request', 'model.admin'], 'block', null, ['LLM03:2026'], 'allowed models ∩ agent models'],
  ['GOV-03', 'Tool authorization (RBAC + arg constraints)', 'action-guards', 'deterministic', ['tool.input', 'mcp.call'], 'block', null, ['ASI02', 'LLM06:2026'], 'allowed tools · deny tools · arg rules'],
  ['GOV-04', 'Human approval gate for high-impact tools', 'action-guards', 'deterministic', ['tool.input', 'mcp.call', 'egress.request'], 'require_approval', null, ['ASI09', 'LLM06:2026'], 'approve_tools globs · fingerprint-bound'],
  ['GOV-05', 'Config-change governance', 'approvals-engine', 'deterministic', ['config.change'], 'require_approval', null, ['ASI09'], 'who may change what'],
  ['ACT-01', 'Spend guard (purchases, subscriptions)', 'action-guards', 'deterministic', ['tool.input', 'mcp.call', 'egress.request'], 'require_approval', null, ['ASI02', 'LLM06:2026'], 'amount → approver level'],
  ['ACT-02', 'Data access guard (tables by sensitivity)', 'action-guards', 'deterministic', ['tool.input', 'mcp.call'], 'require_approval', null, ['ASI02', 'LLM02:2026'], 'resource labels · standing grants'],
  ['ACT-03', 'External send guard (email, webhooks)', 'action-guards', 'deterministic', ['tool.input', 'mcp.call', 'egress.request'], 'require_approval', null, ['ASI02', 'LLM02:2026'], 'recipients outside internal domains'],
  ['ACT-04', 'Code execution & deploy guard', 'action-guards', 'deterministic', ['tool.input', 'mcp.call'], 'require_approval', null, ['ASI05'], 'kubectl/terraform apply · push to main'],
  ['DLP-01', 'PII / PCI / Polish-ID tokenization', 'redaction-engine', 'deterministic', ['prompt.user', 'model.request', 'tool.input', 'mcp.call', 'egress.request'], 'redact', null, ['LLM02:2026'], 'regex + checksum · destination matrix'],
  ['DLP-02', 'Secrets & credentials', 'redaction-engine', 'deterministic', [...OUT.filter((s) => s !== 'a2a.message'), 'tool.output', 'mcp.result'], 'block', 4.0, ['LLM02:2026'], 'key shapes + entropy ≥ 4.0'],
  ['DLP-03', 'Metadata stripping & generalization', 'metadata-egress', 'deterministic', ['model.request', 'mcp.call', 'egress.request'], 'redact', null, ['LLM02:2026'], 'headers · user ids · paths · hostnames'],
  ['DLP-04', 'Tool-arg / egress exfiltration scan', 'metadata-egress', 'hybrid', ['tool.input', 'mcp.call', 'egress.request'], 'block', null, ['LLM02:2026', 'ASI02'], 'encoded blobs · long queries · DNS labels'],
  ['DLP-05', 'Output & tool-result leak detection', 'redaction-engine', 'deterministic', ['model.response', 'tool.output', 'mcp.result', 'egress.response'], 'redact', null, ['LLM02:2026', 'LLM05:2026'], 'leak patterns · canary'],
  ['DLP-06', 'Exfil-channel neutralization', 'metadata-egress', 'deterministic', ['model.response', 'tool.output', 'mcp.result'], 'redact', null, ['LLM05:2026'], 'markdown images · links · ANSI'],
  ['DLP-07', 'Multilingual NER (incl. Polish)', 'redaction-engine', 'semantic', ['prompt.user', 'model.request', 'tool.output', 'mcp.result'], 'redact', 0.6, ['LLM02:2026'], 'eu-pii-ner ONNX · PERSON ADDRESS HEALTH'],
  ['DLP-08', 'Vault & controlled re-identification', 'redaction-engine', 'deterministic', ['model.response', 'tool.input'], 'allow', null, ['LLM02:2026'], 'rehydrate for local user only'],
  ['INJ-01', 'Normalization + injection signatures', 'injection-defense', 'deterministic', INJ, 'block', null, ['LLM01:2026'], 'decode · fuzzy signatures EN/PL'],
  ['INJ-02', 'Semantic injection / jailbreak classifier', 'injection-defense', 'semantic', INJ, 'block', 0.9, ['LLM01:2026'], 'prompt-guard classifier'],
  ['INJ-03', 'Content safety + topic adherence', 'semantic-models', 'semantic', ['prompt.user', 'model.request', 'model.response'], 'block', 0.8, ['LLM09:2026'], 'aegis-guard · adherence %'],
  ['INJ-04', 'Hidden-context exposure', 'injection-defense', 'hybrid', ['prompt.user', 'model.request', 'model.response'], 'block', 0.4, ['LLM07:2026'], 'extraction · canary · overlap'],
  ['INJ-05', 'Goal-drift / grounding check', 'injection-defense', 'hybrid', ['tool.input', 'mcp.call'], 'require_approval', null, ['ASI01'], 'monitor-only'],
  ['EXE-01', 'Dangerous command guard', 'action-guards', 'deterministic', ['tool.input', 'mcp.call', 'mcp.init'], 'block', null, ['ASI05', 'LLM05:2026'], 'pipe-to-shell · rm -rf · pickle.loads'],
  ['EXE-02', 'Filesystem & network scope (SSRF)', 'action-guards', 'deterministic', ['tool.input', 'mcp.call', 'egress.request'], 'block', null, ['ASI02', 'LLM06:2026'], '~/.ssh · .env · private ranges'],
  ['EXE-03', 'Taint-flow breaker (lethal trifecta)', 'action-guards', 'stateful', ['tool.input', 'mcp.call', 'egress.request'], 'require_approval', null, ['ASI01', 'LLM01:2026'], 'private + untrusted + exfil'],
  ['MCP-01', 'Server registry & launch check', 'mcp-proxy', 'deterministic', ['mcp.init', 'mcp.call'], 'block', null, ['MCP09:2025'], 'registered servers only'],
  ['MCP-02', 'Tool-definition poisoning scan', 'mcp-proxy', 'hybrid', ['mcp.list'], 'redact', null, ['MCP03:2025'], 'hidden instructions in descriptions'],
  ['MCP-03', 'Tool pinning (rug pull) & shadowing', 'mcp-proxy', 'stateful', ['mcp.list', 'mcp.call'], 'block', null, ['MCP03:2025', 'MCP06:2025'], 'sha256 pin per tool'],
  ['MCP-04', 'Token & auth hygiene', 'mcp-proxy', 'deterministic', ['mcp.init', 'mcp.call', 'mcp.result'], 'block', null, ['MCP01:2025', 'MCP07:2025'], 'scopes · OAuth URLs'],
  ['BUD-01', 'Token & cost budgets', 'budgets-ledger', 'deterministic', ['model.request', 'tool.input', 'mcp.call', 'egress.request'], 'block', null, ['LLM10:2026'], 'reserve · clamp · downgrade'],
  ['BUD-02', 'Local compute & concurrency', 'budgets-ledger', 'deterministic', ['model.request', 'model.admin'], 'block', null, ['LLM10:2026'], 'concurrency · model size'],
  ['SIG-01', 'External exploit-signature engine', 'threat-feed', 'deterministic', ALL, 'block', null, ['LLM03:2026', 'ASI04'], 'signed feed signatures'],
  ['SIG-02', 'Model-artifact gate (pickle / GGUF)', 'threat-feed', 'deterministic', ['model.admin', 'artifact.file'], 'block', null, ['LLM03:2026', 'LLM04:2026'], 'pickle globals · format magic'],
  ['SIG-03', 'Package-install / slopsquatting guard', 'threat-feed', 'deterministic', ['tool.input', 'mcp.init'], 'block', null, ['LLM03:2026', 'ASI04'], 'known-bad + unknown packages'],
  ['CUS-01', 'Customer-defined rules', 'semantic-models', 'hybrid', ['prompt.user', 'model.request', 'tool.input', 'mcp.call'], 'block', 0.7, ['LLM02:2026'], 'keywords + aegis-judge'],
];

const FAMILY: Record<string, string> = {
  GOV: 'governance', ACT: 'actions', DLP: 'data', INJ: 'injection', EXE: 'execution',
  MCP: 'mcp', BUD: 'budget', SIG: 'signatures', CUS: 'custom', A2A: 'a2a',
};

export function familyOf(id: string): string {
  return FAMILY[id.split('-')[0] ?? ''] ?? 'other';
}

/** The 36 catalog controls in pipeline-ish order (enabled, enforce, defaults). */
export const FALLBACK_CONTROLS: CatalogControl[] = ROWS.map(([id, name, owner, kind, surfaces, action, threshold, owasp, description]) => ({
  id,
  name,
  family: familyOf(id),
  kind,
  owner,
  surfaces,
  enabled: true,
  mode: id === 'INJ-05' ? 'monitor' : 'enforce',
  action,
  threshold,
  owasp,
  description,
}));

export const ALL_SURFACES: Surface[] = ALL;

export function phaseOf(kind: ControlKind | string | null | undefined): Phase {
  return kind === 'semantic' || kind === 'hybrid' ? 'semantic' : 'deterministic';
}

/** Kind for an id that is missing from the live catalog. */
export function fallbackKind(id: string): ControlKind {
  const hit = ROWS.find((r) => r[0] === id);
  if (hit) return hit[3];
  return 'deterministic';
}

export function fallbackControl(id: string): CatalogControl | undefined {
  return FALLBACK_CONTROLS.find((c) => c.id === id);
}
