// Decision trace model (plan 16 §2.3 "Decision trace"). PURE module, node-testable.
// Rows = detail.decisions ∪ applicable catalog controls; deterministic phase sequential, semantic concurrent.
import type { Action, Decision, DecisionDetail } from '@/api/types';
import type { CatalogControl, ControlKind, Phase, StageStatus, TraceModel, TraceStage } from '../types';

const RANK: Record<Action, number> = { allow: 0, log: 1, redact: 2, require_approval: 3, block: 4 };
const SEMANTIC_KINDS = new Set(['semantic', 'hybrid']);
const PREFIX_KIND: Record<string, ControlKind> = { EXE: 'deterministic', DLP: 'deterministic', INJ: 'deterministic' };
const KNOWN_SEMANTIC = new Set(['DLP-07', 'INJ-02', 'INJ-03']);
const KNOWN_HYBRID = new Set(['DLP-04', 'INJ-04', 'INJ-05', 'MCP-02', 'CUS-01']);
const KNOWN_STATEFUL = new Set(['EXE-03', 'EXE-04', 'MCP-03']);

function guessKind(id: string): ControlKind {
  if (KNOWN_SEMANTIC.has(id)) return 'semantic';
  if (KNOWN_HYBRID.has(id)) return 'hybrid';
  if (KNOWN_STATEFUL.has(id)) return 'stateful';
  return PREFIX_KIND[id.split('-')[0] ?? ''] ?? 'deterministic';
}

function phaseOfKind(kind: string): Phase {
  return SEMANTIC_KINDS.has(kind) ? 'semantic' : 'deterministic';
}

/** Upper bound of a score bar: probabilities use 0..1, entropy/counts scale around the threshold. */
export function scoreScale(score: number | null, threshold: number | null): number {
  if (threshold !== null && threshold !== undefined) {
    if (threshold <= 1 && (score === null || score <= 1)) return 1;
    return Math.max(threshold * 1.5, (score ?? 0) * 1.1);
  }
  if (score === null || score === undefined) return 1;
  return score <= 1 ? 1 : score * 1.25;
}

function statusOf(d: Decision): StageStatus {
  if (d.mode === 'monitor' && d.action !== 'allow' && d.action !== 'log') return 'monitor';
  if (d.degraded) return 'degraded';
  if (d.action !== 'allow' && d.action !== 'log') return 'hit';
  return 'pass';
}

/** Pick the most severe decision when a control returned several. */
function strongest(list: Decision[]): Decision {
  return list.reduce((a, b) => {
    const ae = a.mode === 'enforce' ? 1 : 0;
    const be = b.mode === 'enforce' ? 1 : 0;
    if (be !== ae) return be > ae ? b : a;
    return RANK[b.action] > RANK[a.action] ? b : a;
  });
}

export interface BuildTraceOptions {
  /** Fallback per-control latencies (playground timings). */
  timings?: { control_id: string; ms: number }[];
  /** Include catalog controls that ran without a decision (default true). */
  includeQuiet?: boolean;
}

export type TraceInput = Pick<DecisionDetail, 'decisions' | 'surface' | 'action' | 'control_id' | 'latency_ms'>;

export function buildTrace(detail: TraceInput, catalog: CatalogControl[], opts: BuildTraceOptions = {}): TraceModel {
  const includeQuiet = opts.includeQuiet !== false;
  const timing = new Map<string, number>();
  for (const t of opts.timings ?? []) timing.set(t.control_id, (timing.get(t.control_id) ?? 0) + t.ms);
  const catIndex = new Map<string, number>();
  catalog.forEach((c, i) => catIndex.set(c.id, i));
  const byId = new Map<string, Decision[]>();
  for (const d of detail.decisions ?? []) {
    const list = byId.get(d.control_id) ?? [];
    list.push(d);
    byId.set(d.control_id, list);
  }

  const ids: string[] = [];
  const seen = new Set<string>();
  if (includeQuiet) {
    for (const c of catalog) {
      if (c.enabled === false || c.mode === 'off') continue;
      if (!c.surfaces.includes(detail.surface)) continue;
      ids.push(c.id);
      seen.add(c.id);
    }
  }
  for (const id of [...byId.keys(), ...timing.keys()]) {
    if (seen.has(id)) continue;
    ids.push(id);
    seen.add(id);
  }

  const primaryId = detail.control_id ?? null;
  const stages: TraceStage[] = ids.map((id) => {
    const cat = catalog[catIndex.get(id) ?? -1];
    const kind: ControlKind = cat?.kind ?? guessKind(id);
    const list = byId.get(id);
    const d = list && list.length ? strongest(list) : null;
    const latency = d ? (d.latency_ms ?? timing.get(id) ?? null) : (timing.get(id) ?? null);
    const score = d?.score ?? null;
    const threshold = d?.threshold ?? (cat?.threshold ?? null);
    return {
      key: id,
      controlId: id,
      name: cat?.name ?? id,
      kind,
      phase: phaseOfKind(kind),
      status: d ? statusOf(d) : 'quiet',
      action: d?.action ?? null,
      mode: d?.mode ?? null,
      reason: d?.reason ?? null,
      score,
      threshold: d ? threshold : null,
      scaleMax: scoreScale(score, d ? threshold : null),
      latencyMs: latency,
      offsetMs: 0,
      primary: id === primaryId,
      degraded: d?.degraded ?? false,
      findings: list ? list.reduce((n, x) => n + (x.findings?.length ?? 0), 0) : 0,
      skippedReason: null,
    };
  });

  const order = (s: TraceStage) => catIndex.get(s.controlId) ?? 1000;
  const det = stages.filter((s) => s.phase === 'deterministic').sort((a, b) => order(a) - order(b) || a.controlId.localeCompare(b.controlId));
  const sem = stages.filter((s) => s.phase === 'semantic').sort((a, b) => order(a) - order(b) || a.controlId.localeCompare(b.controlId));

  // short-circuit: final block from a deterministic control and no semantic decision at all
  const primaryStage = stages.find((s) => s.primary) ?? null;
  const semHasDecision = sem.some((s) => s.action !== null);
  let shortCircuitAfter: string | null = null;
  if (detail.action === 'block' && primaryStage && primaryStage.phase === 'deterministic' && !semHasDecision) {
    shortCircuitAfter = primaryStage.controlId;
    for (const s of sem) {
      s.status = 'skipped';
      s.skippedReason = `short-circuit after ${primaryStage.controlId}`;
      s.latencyMs = null;
    }
  }

  let cursor = 0;
  for (const s of det) {
    s.offsetMs = cursor;
    cursor += s.latencyMs ?? 0;
  }
  const detTotalMs = cursor;
  let semTotalMs = 0;
  for (const s of sem) {
    s.offsetMs = detTotalMs;
    if (s.status !== 'skipped') semTotalMs = Math.max(semTotalMs, s.latencyMs ?? 0);
  }
  const ordered = [...det, ...sem];
  const totalMs = Math.max(detTotalMs + semTotalMs, 0);

  const enforceRanked = ordered
    .filter((s) => s.action !== null && s.mode === 'enforce')
    .sort((a, b) => RANK[b.action as Action] - RANK[a.action as Action] || Number(b.primary) - Number(a.primary));

  return {
    stages: ordered,
    detTotalMs,
    semTotalMs,
    totalMs,
    ranCount: ordered.filter((s) => s.status !== 'skipped').length,
    shortCircuitAfter,
    primaryId,
    monitorHits: ordered.filter((s) => s.status === 'monitor'),
    enforceRanked,
  };
}

/** `Server-Timing` header reconstructed from per-control latencies. */
export function serverTiming(trace: TraceModel, overheadMs: number, upstreamMs: number | null): string {
  const parts = [`aegis;dur=${overheadMs.toFixed(2)}`];
  for (const s of trace.stages) {
    if (s.latencyMs === null || s.status === 'skipped') continue;
    parts.push(`${s.controlId.toLowerCase().replace('-', '')};dur=${s.latencyMs.toFixed(2)}`);
  }
  if (upstreamMs !== null && upstreamMs !== undefined) parts.push(`upstream;dur=${Math.round(upstreamMs)}`);
  return `Server-Timing: ${parts.join(', ')}`;
}
