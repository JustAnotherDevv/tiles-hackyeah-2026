// Page-local view types for the Security section (docs/plan/16-dashboard-security.md §2.1).
// Never re-declare CONTRACTS §5.5 types here; derive from '@/api/types' instead.
// Owner: dashboard-security.
import type {
  Action,
  ControlView,
  DataClass,
  DestClass,
  Kind,
  McpToolView,
  Mode,
  Surface,
} from '@/api/types';

// ------------------------------------------------------------------ control catalog
export type ControlKind = ControlView['kind'];
export type Phase = 'deterministic' | 'semantic';

/** Minimal control description used by the trace (from GET /api/controls or the fallback catalog). */
export interface CatalogControl {
  id: string;
  name: string;
  family: string;
  kind: ControlKind;
  owner: string;
  surfaces: Surface[];
  enabled?: boolean;
  mode?: Mode;
  action?: Action;
  threshold?: number | null;
  owasp?: string[];
  description?: string;
}

// ------------------------------------------------------------------ decision trace
export type StageStatus = 'hit' | 'monitor' | 'degraded' | 'pass' | 'quiet' | 'skipped';

export interface TraceStage {
  key: string;
  controlId: string;
  name: string;
  kind: ControlKind;
  phase: Phase;
  status: StageStatus;
  /** Decision action (null when the control produced no decision). */
  action: Action | null;
  mode: 'enforce' | 'monitor' | null;
  reason: string | null;
  score: number | null;
  threshold: number | null;
  /** Upper bound of the score bar (1 for probabilities, larger for entropy/counts). */
  scaleMax: number;
  latencyMs: number | null;
  /** Start offset (ms) inside the waterfall. */
  offsetMs: number;
  primary: boolean;
  degraded: boolean;
  findings: number;
  skippedReason: string | null;
}

export interface TraceModel {
  stages: TraceStage[];
  detTotalMs: number;
  semTotalMs: number;
  totalMs: number;
  ranCount: number;
  shortCircuitAfter: string | null;
  primaryId: string | null;
  monitorHits: TraceStage[];
  enforceRanked: TraceStage[];
}

// ------------------------------------------------------------------ redaction diff
export type DiffPartKind = 'text' | 'entity' | 'placeholder' | 'dropped' | 'masked' | 'restored';

export interface DiffPart {
  kind: DiffPartKind;
  text: string;
  /** Shared hover key "{seg}:{n}" linking original span, outbound placeholder and table row. */
  key?: string;
  entity?: string;
  dataClass?: DataClass | null;
  placeholder?: string;
  reversible?: boolean;
}

// ------------------------------------------------------------------ live feed filters
export interface DecisionFilter {
  actions: Action[];
  surface: string;
  kind: string;
  agent: string;
  member: string;
  team: string;
  source: string;
  dest: string;
  control: string;
  q: string;
  nonAllow: boolean;
}

// ------------------------------------------------------------------ MCP (G2 extras; optional on the wire)
export interface McpToolDiff {
  changed_fields: string[];
  description_diff?: string[];
  params_added?: string[];
  params_removed?: string[];
}

export type McpToolViewX = McpToolView & {
  pinned_hash?: string | null;
  diff?: McpToolDiff | null;
  approval_id?: string | null;
};

// ------------------------------------------------------------------ perf (G3)
export interface BenchProfile {
  name: string;
  description?: string;
  concurrency: number;
  requests: number;
  rps: number;
  overhead_ms: { p50: number; p95: number; p99: number };
  upstream_ms?: { p50: number; p95: number };
  by_control?: { control_id: string; p50_ms: number; p95_ms: number }[];
}

export interface BenchReport {
  schema: 'aegis.bench/1';
  generated_at: string;
  machine: { cpu: string; ram_gb: number; os: string; python: string };
  profiles: BenchProfile[];
}

// ------------------------------------------------------------------ playground
export interface PlaygroundPreset {
  id: string;
  label: string;
  group: 'Data' | 'Injection' | 'Tools' | 'MCP' | 'Governance' | 'Benign';
  hint: string;
  /** Expected verdict (documentation only). */
  expect: Action;
  surface: Surface;
  kind?: Kind;
  destination: DestClass | string;
  agent_id?: string | null;
  tool_name?: string | null;
  /** Generated lazily so secret-shaped strings are never committed. */
  text: () => string;
  tool_args?: () => Record<string, unknown>;
}

// ------------------------------------------------------------------ threat feed
export type FeedStepState = 'ok' | 'fail' | 'skipped' | 'pending';

export interface FeedStep {
  key: string;
  label: string;
  state: FeedStepState;
  detail: string | null;
}
