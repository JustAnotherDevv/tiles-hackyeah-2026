// Mock threat feed (signatures from staging/feed-seed/signatures/*.yaml + pending TI-022).
// Owner: dashboard-security.
import type { Action, FeedSignatureView, FeedStatus, Severity, Surface } from '@/api/types';
import { mockScenario } from '@/components/security/env';
import { MOCK_FEED_SERIAL } from './decisions';
import { hashString, mulberry32 } from './rng';

type Row = [id: string, title: string, severity: Severity, action: Action, aliases: string[], surfaces: Surface[], tags: string[]];

const SEED: Row[] = [
  ['AEGIS-TI-000', 'Aegis end-to-end canary (EICAR-style test string)', 'info', 'block', [], ['prompt.user', 'model.request'], ['canary']],
  ['AEGIS-TI-001', 'Malicious pickle in model file (unsafe-global allowlist)', 'critical', 'block', ['CVE-2025-1716', 'CVE-2025-1889'], ['artifact.file', 'model.admin'], ['LLM03:2026']],
  ['AEGIS-TI-002', 'nullifAI — model file with 7z magic instead of a tensor format', 'high', 'block', [], ['artifact.file'], ['LLM03:2026']],
  ['AEGIS-TI-003', 'Unsafe model format download / torch.load on pickle formats', 'high', 'require_approval', ['CVE-2025-32434', 'CVE-2025-1944', 'CVE-2025-1945'], ['tool.input', 'model.admin'], ['LLM03:2026']],
  ['AEGIS-TI-004', 'Keras Lambda-layer code execution on model load', 'critical', 'block', ['CVE-2024-3660', 'CVE-2025-1550'], ['artifact.file'], ['LLM03:2026']],
  ['AEGIS-TI-005', 'GGUF / chat-template Jinja2 SSTI ("Llama Drama")', 'critical', 'block', ['CVE-2024-34359'], ['artifact.file', 'model.admin'], ['LLM03:2026']],
  ['AEGIS-TI-006', 'Probllama — Ollama admin API abuse / path traversal', 'critical', 'block', ['CVE-2024-37032'], ['model.admin', 'egress.request'], ['LLM03:2026']],
  ['AEGIS-TI-007', 'ShadowRay — unauthenticated Ray Jobs API', 'critical', 'block', ['CVE-2023-48022'], ['egress.request', 'tool.input'], ['ASI05']],
  ['AEGIS-TI-008', 'Langflow unauthenticated code-exec endpoint', 'critical', 'block', ['CVE-2025-3248', 'CVE-2026-33017'], ['egress.request'], ['ASI05']],
  ['AEGIS-TI-009', 'Execution of LLM-generated code (dangerous call shapes)', 'high', 'block', ['CVE-2023-36258', 'CVE-2023-29374', 'CVE-2024-12366'], ['tool.input', 'model.response'], ['ASI05']],
  ['AEGIS-TI-010', 'mcp-remote OAuth endpoint command injection', 'critical', 'block', ['CVE-2025-6514'], ['mcp.init', 'mcp.result'], ['MCP05:2025']],
  ['AEGIS-TI-011', 'Spawning stdio MCP servers over HTTP (MCP Inspector / LiteLLM)', 'critical', 'block', ['CVE-2025-49596', 'CVE-2026-42271'], ['egress.request', 'mcp.init'], ['MCP05:2025']],
  ['AEGIS-TI-012', 'MCP tool poisoning, shadowing and rug pull', 'high', 'redact', [], ['mcp.list'], ['MCP03:2025']],
  ['AEGIS-TI-013', 'Invisible Unicode / ASCII tag smuggling', 'medium', 'redact', [], ['prompt.user', 'tool.output', 'mcp.result', 'mcp.list'], ['LLM01:2026']],
  ['AEGIS-TI-014', 'Markdown / URL data exfiltration (EchoLeak)', 'high', 'redact', ['CVE-2025-32711'], ['model.response', 'tool.output'], ['LLM05:2026']],
  ['AEGIS-TI-015', 'Agent config hijack for auto-approve ("YOLO mode" / CurXecute)', 'high', 'require_approval', ['CVE-2025-53773', 'CVE-2025-54135'], ['tool.input'], ['ASI09']],
  ['AEGIS-TI-016', 'Slopsquatting / hallucinated package install', 'medium', 'require_approval', [], ['tool.input'], ['ASI04']],
  ['AEGIS-TI-017', 'Compromised AI packages and MCP servers (known-bad versions + IOCs)', 'critical', 'block', ['CVE-2025-8217'], ['tool.input', 'mcp.init'], ['LLM03:2026', 'ASI04']],
  ['AEGIS-TI-018', 'Model namespace reuse / unpinned model revision', 'medium', 'require_approval', [], ['model.admin', 'tool.input'], ['LLM03:2026']],
  ['AEGIS-TI-019', 'Prompt-injection families (override / jailbreak / extraction / role spoofing)', 'high', 'block', [], ['prompt.user', 'model.request', 'tool.output', 'mcp.result'], ['LLM01:2026']],
];
const PENDING: Row = ['AEGIS-TI-022', 'EchoLeak exfiltration via an allowlisted image proxy / open redirector', 'high', 'block', ['CVE-2025-32711'], ['model.response', 'tool.output'], ['LLM05:2026']];

export function mockFeedSignatures(includePending = false): { items: FeedSignatureView[] } {
  const rows = includePending ? [...SEED, PENDING] : SEED;
  return {
    items: rows.map(([id, title, severity, action, aliases, surfaces, tags]) => {
      const r = mulberry32(hashString(id));
      const hot = id === 'AEGIS-TI-017' || id === 'AEGIS-TI-019' || id === 'AEGIS-TI-014' || id === 'AEGIS-TI-012';
      return {
        id,
        title,
        severity,
        status: id === 'AEGIS-TI-018' ? 'experimental' : 'stable',
        aliases,
        tags,
        surfaces,
        action,
        hits_24h: hot ? 8 + Math.round(r() * 40) : Math.round(r() * 4),
      };
    }),
  };
}

export function mockFeedStatus(): FeedStatus {
  const now = Date.now();
  const tamper = mockScenario() === 'tamper';
  const sigs = mockFeedSignatures().items;
  return {
    feed_id: 'aegis-threat-intel',
    url: 'http://127.0.0.1:8790/feed/latest.json',
    status: tamper ? 'rejected' : 'ok',
    serial: MOCK_FEED_SERIAL,
    version: `2026.10.03-${MOCK_FEED_SERIAL}`,
    published: new Date(now - 42 * 60e3).toISOString(),
    expires: new Date(now + 22 * 3600e3).toISOString(),
    key_id: 'a91f3c07',
    signatures_total: sigs.length,
    signatures_active: sigs.filter((s) => s.status === 'stable').length,
    signatures_monitor: sigs.filter((s) => s.status === 'experimental').length,
    signatures_quarantined: 0,
    last_check: new Date(now - 8e3).toISOString(),
    last_update: new Date(now - 41 * 60e3).toISOString(),
    last_error: tamper ? `bad_signature: ed25519 verification failed for bundle #${MOCK_FEED_SERIAL + 1} (bytes modified after signing)` : null,
    history: [
      { serial: MOCK_FEED_SERIAL, version: `2026.10.03-${MOCK_FEED_SERIAL}`, applied_at: new Date(now - 41 * 60e3).toISOString(), added: 1, removed: 0, modified: 2 },
      { serial: MOCK_FEED_SERIAL - 1, version: `2026.10.03-${MOCK_FEED_SERIAL - 1}`, applied_at: new Date(now - 5 * 3600e3).toISOString(), added: 19, removed: 0, modified: 0 },
    ],
  };
}
