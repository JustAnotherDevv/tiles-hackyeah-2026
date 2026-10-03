// HealthResponse / SemanticStatus mocks for the shell. Owner: dashboard-shell (B16).
import type { HealthResponse, PerfResponse } from '@/api/types';

const bootAt = Date.now() - 3 * 3600_000 - 17 * 60_000;

export function mockHealth(): HealthResponse {
  return {
    status: 'ok',
    version: '0.1.0',
    uptime_s: Math.round((Date.now() - bootAt) / 1000),
    policy_version: 14,
    feed_serial: 43,
    components: {
      gateway: 'ok',
      policy: 'ok',
      pipeline: 'ok',
      audit: 'ok',
      ledger: 'ok',
      approvals: 'ok',
      feed: 'ok',
      semantic: 'ok',
      ollama: 'ok',
      mcp_proxy: 'ok',
    },
  };
}

export function mockSemanticStatus(): PerfResponse['semantic'] {
  return {
    mode: 'auto',
    degraded: false,
    models: [
      { name: 'eu-pii-ner (INT8)', backend: 'onnxruntime', loaded: true, p50_ms: 38 },
      { name: 'aegis-guard', backend: 'ollama', loaded: true, p50_ms: 210 },
      { name: 'aegis-judge', backend: 'ollama', loaded: true, p50_ms: 640 },
    ],
  };
}
