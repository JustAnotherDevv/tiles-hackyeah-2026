// Playground reveal pacing (plan 16 §2.3 "Playground"). Real latencies stretched ~25x, clamped.
// PURE module, node-testable.

export interface ScheduleStage {
  key: string;
  phase: 'deterministic' | 'semantic';
  latencyMs: number | null;
  status?: string;
}

export interface ScheduleOptions {
  minMs?: number;
  maxMs?: number;
  factor?: number;
  reduced?: boolean;
}

export interface ScheduledStage {
  key: string;
  startMs: number;
  durMs: number;
}

export function clampStageMs(latencyMs: number | null, opts: ScheduleOptions = {}): number {
  const min = opts.minMs ?? 140;
  const max = opts.maxMs ?? 700;
  const factor = opts.factor ?? 25;
  return Math.min(max, Math.max(min, (latencyMs ?? 0) * factor));
}

/** Deterministic stages one after another, semantic stages together; reduced motion → everything at 0. */
export function stageSchedule(stages: ScheduleStage[], opts: ScheduleOptions = {}): { items: ScheduledStage[]; totalMs: number } {
  if (opts.reduced) return { items: stages.map((s) => ({ key: s.key, startMs: 0, durMs: 0 })), totalMs: 0 };
  const items: ScheduledStage[] = [];
  let cursor = 0;
  for (const s of stages) {
    if (s.phase !== 'deterministic') continue;
    const dur = clampStageMs(s.latencyMs, opts);
    items.push({ key: s.key, startMs: cursor, durMs: dur });
    cursor += dur;
  }
  let semEnd = cursor;
  for (const s of stages) {
    if (s.phase === 'deterministic') continue;
    const dur = s.status === 'skipped' ? 0 : clampStageMs(s.latencyMs, opts);
    items.push({ key: s.key, startMs: cursor, durMs: dur });
    semEnd = Math.max(semEnd, cursor + dur);
  }
  const order = new Map(stages.map((s, i) => [s.key, i]));
  items.sort((a, b) => (order.get(a.key) ?? 0) - (order.get(b.key) ?? 0));
  return { items, totalMs: semEnd };
}
