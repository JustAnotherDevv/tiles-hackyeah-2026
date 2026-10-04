// PerfResponse mock (numbers in the range the bench reports for the deterministic path). Owner: B16.
import type { PerfResponse } from '@/api/types';
import { liveRand } from './rng';

export function mockPerf(): PerfResponse {
  const j = () => 0.9 + liveRand() * 0.2;
  return {
    generated_at: new Date().toISOString(),
    overhead_ms: { p50: +(0.41 * j()).toFixed(2), p95: +(1.12 * j()).toFixed(2), p99: +(2.84 * j()).toFixed(2), count: 48216 },
    by_control: [
      { control_id: 'INJ-02', kind: 'semantic', p50_ms: 0.62, p95_ms: 1.74, count: 18210 },
      { control_id: 'DLP-07', kind: 'semantic', p50_ms: 0.48, p95_ms: 1.21, count: 16880 },
      { control_id: 'DLP-01', kind: 'deterministic', p50_ms: 0.11, p95_ms: 0.31, count: 41020 },
      { control_id: 'DLP-02', kind: 'deterministic', p50_ms: 0.07, p95_ms: 0.19, count: 44210 },
      { control_id: 'INJ-01', kind: 'deterministic', p50_ms: 0.06, p95_ms: 0.17, count: 30110 },
      { control_id: 'DLP-03', kind: 'deterministic', p50_ms: 0.05, p95_ms: 0.14, count: 26840 },
      { control_id: 'EXE-04', kind: 'stateful', p50_ms: 0.03, p95_ms: 0.09, count: 47900 },
      { control_id: 'BUD-01', kind: 'deterministic', p50_ms: 0.03, p95_ms: 0.08, count: 39020 },
      { control_id: 'SIG-01', kind: 'deterministic', p50_ms: 0.04, p95_ms: 0.11, count: 48216 },
      { control_id: 'GOV-01', kind: 'deterministic', p50_ms: 0.01, p95_ms: 0.03, count: 48216 },
    ],
    upstream_ms: [
      { provider: 'anthropic', model: 'claude-sonnet-4-5', p50: 1840, p95: 4210, count: 9120 },
      { provider: 'openai', model: 'gpt-4o-mini', p50: 820, p95: 1960, count: 6410 },
      { provider: 'ollama', model: 'aegis-judge', p50: 1310, p95: 2620, count: 11280 },
      { provider: 'mock', model: 'mock-echo', p50: 12, p95: 31, count: 2210 },
    ],
    rps_1m: +(0.8 + liveRand() * 1.2).toFixed(2),
    semantic: {
      mode: 'auto',
      degraded: false,
      models: [
        { name: 'eu-pii-ner (INT8)', backend: 'onnxruntime', loaded: true, p50_ms: 38 },
        { name: 'aegis-guard', backend: 'ollama', loaded: true, p50_ms: 210 },
        { name: 'aegis-judge', backend: 'ollama', loaded: true, p50_ms: 640 },
      ],
    },
    bench: null,
  };
}
