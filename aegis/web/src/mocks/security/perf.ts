// Mock GET /api/perf (latencies from staging/models/RESULTS.md, overhead from the prototype).
// Owner: dashboard-security.
import type { PerfResponse } from '@/api/types';
import type { BenchReport } from '@/components/security/types';
import { FALLBACK_CONTROLS } from '@/components/security/lib/catalog';
import { mockControls } from './controls';

export function mockBench(): BenchReport & Record<string, unknown> {
  return {
    schema: 'aegis.bench/1',
    generated_at: '2026-10-04T02:10:00Z',
    machine: { cpu: 'Apple M2', ram_gb: 8, os: 'macOS 27.0', python: '3.13.1' },
    profiles: [
      { name: 'guard-det-c1', description: 'deterministic, 1 client', concurrency: 1, requests: 1500, rps: 612.4, overhead_ms: { p50: 0.9, p95: 2.1, p99: 3.4 } },
      { name: 'guard-det-c16', description: 'deterministic, 16 clients', concurrency: 16, requests: 6000, rps: 1480.2, overhead_ms: { p50: 1.6, p95: 4.8, p99: 8.9 } },
      { name: 'proxy-det-c4', description: 'model proxy, mock upstream 800 ms', concurrency: 4, requests: 400, rps: 4.9, overhead_ms: { p50: 2.3, p95: 5.1, p99: 9.7 }, upstream_ms: { p50: 801, p95: 812 } },
      { name: 'guard-sem-c1', description: 'semantic (ONNX + heuristics)', concurrency: 1, requests: 300, rps: 41.0, overhead_ms: { p50: 21.0, p95: 48.0, p99: 66.2 } },
    ],
    headline: {
      det_overhead_p50_ms: 0.9,
      det_overhead_p95_ms: 2.1,
      sem_overhead_p50_ms: 21.0,
      sem_overhead_p95_ms: 48.0,
      rps_det: 612.4,
      overhead_share_pct: 0.26,
      reload_p95_ms: 330,
    },
  };
}

export function mockPerf(): PerfResponse {
  const controls = mockControls().items;
  return {
    generated_at: new Date().toISOString(),
    overhead_ms: { p50: 2.1, p95: 14.8, p99: 41.2, count: 18422 },
    by_control: controls
      .filter((c) => c.implemented)
      .map((c) => ({
        control_id: c.id,
        kind: FALLBACK_CONTROLS.find((x) => x.id === c.id)?.kind ?? c.kind,
        p50_ms: Math.round((c.p95_ms ?? 0.1) * 0.42 * 100) / 100,
        p95_ms: c.p95_ms ?? 0.1,
        count: c.hits_24h * 7 + 120,
      })),
    upstream_ms: [
      { provider: 'anthropic', model: 'claude-sonnet-4-5', p50: 812, p95: 1940, count: 412 },
      { provider: 'mock', model: 'mock-sonnet', p50: 801, p95: 815, count: 2231 },
      { provider: 'ollama', model: 'aegis-judge', p50: 420, p95: 910, count: 188 },
      { provider: 'mcp:acme-db', model: null, p50: 6, p95: 14, count: 96 },
    ],
    rps_1m: 4.2,
    semantic: {
      mode: 'auto',
      degraded: false,
      models: [
        { name: 'pi-horizon-small (INJ-02)', backend: 'onnxruntime', loaded: true, p50_ms: 14.4 },
        { name: 'prompt-guard-2-22m', backend: 'onnxruntime', loaded: true, p50_ms: 6.1 },
        { name: 'eu-pii-ner (DLP-07)', backend: 'onnxruntime', loaded: true, p50_ms: 13.2 },
        { name: 'minilm-l12-multi', backend: 'onnxruntime', loaded: true, p50_ms: 3.1 },
        { name: 'aegis-guard (Qwen3Guard-0.6B)', backend: 'ollama', loaded: false, p50_ms: 182 },
        { name: 'aegis-judge (Qwen3.5-0.8B)', backend: 'ollama', loaded: false, p50_ms: 420 },
      ],
    },
    bench: mockBench(),
  };
}
