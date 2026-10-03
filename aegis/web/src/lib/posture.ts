// Explainable posture score (docs/plan/15 §2.7; contract gap G1 — computed client-side from existing
// endpoints, not part of the API). 100 points over 6 factors; each factor reports its points so the
// number is never magic. Owner: dashboard-shell (B16).
import type { AuditVerifyResult, ControlView, CoverageResponse, FeedStatus, HealthResponse } from '@/api/types';

export interface PostureInputs {
  controls?: ControlView[] | null;
  coverage?: CoverageResponse | null;
  feed?: FeedStatus | null;
  audit?: AuditVerifyResult | null;
  health?: HealthResponse | null;
  statsDegraded?: boolean | null;
  semanticDegraded?: boolean | null;
}

export interface PostureFactor {
  key: 'controls' | 'coverage' | 'feed' | 'audit' | 'runtime' | 'semantic';
  label: string;
  points: number;
  max: number;
  detail: string;
  ok: boolean;
  known: boolean;
}

export interface Posture {
  score: number;
  grade: 'A' | 'B' | 'C' | 'D';
  tone: 'good' | 'warn' | 'bad';
  factors: PostureFactor[];
  toReview: number;
}

const round1 = (n: number) => Math.round(n * 10) / 10;

export function computePosture(i: PostureInputs): Posture {
  const factors: PostureFactor[] = [];

  // Controls enforced (30)
  {
    const impl = (i.controls ?? []).filter((c) => c.implemented);
    const enforce = impl.filter((c) => c.enabled && c.mode === 'enforce').length;
    const monitor = impl.filter((c) => c.enabled && c.mode === 'monitor').length;
    const share = impl.length ? (enforce + monitor * 0.5) / impl.length : 0;
    const points = i.controls ? round1(share * 30) : 24;
    factors.push({
      key: 'controls',
      label: 'Controls enforced',
      points,
      max: 30,
      detail: i.controls ? `${enforce} enforce · ${monitor} monitor of ${impl.length}` : 'controls unknown',
      ok: points >= 27,
      known: Boolean(i.controls),
    });
  }

  // Framework coverage (20)
  {
    const items = (i.coverage?.frameworks ?? []).flatMap((f) => f.items);
    const covered = items.filter((x) => x.status === 'covered').length;
    const partial = items.filter((x) => x.status === 'partial').length;
    const share = items.length ? (covered + partial * 0.5) / items.length : 0;
    const points = i.coverage ? round1(share * 20) : 16;
    factors.push({
      key: 'coverage',
      label: 'Framework coverage',
      points,
      max: 20,
      detail: i.coverage ? `${covered} covered · ${partial} partial of ${items.length}` : 'coverage unknown',
      ok: points >= 16,
      known: Boolean(i.coverage),
    });
  }

  // Threat feed (15)
  {
    const s = i.feed?.status;
    const points = !i.feed ? 10 : s === 'ok' ? 15 : s === 'seed' ? 10 : s === 'disabled' ? 0 : 8;
    factors.push({
      key: 'feed',
      label: 'Threat feed',
      points,
      max: 15,
      detail: i.feed ? `${s}${i.feed.serial !== null ? ` · #${i.feed.serial}` : ''}` : 'feed unknown',
      ok: s === 'ok',
      known: Boolean(i.feed),
    });
  }

  // Audit chain (15)
  {
    const points = i.audit ? (i.audit.ok ? 15 : 0) : 12;
    factors.push({
      key: 'audit',
      label: 'Audit chain',
      points,
      max: 15,
      detail: i.audit ? (i.audit.ok ? `verified · ${i.audit.records} records` : `broken at seq ${i.audit.broken_at_seq ?? '?'}`) : 'not verified yet',
      ok: Boolean(i.audit?.ok),
      known: Boolean(i.audit),
    });
  }

  // Runtime health (10)
  {
    let points = 8;
    if (i.health) {
      const down = Object.values(i.health.components).filter((v) => v === 'down').length;
      points = Math.max(0, (i.health.status === 'ok' ? 10 : 5) - 2 * down);
    }
    factors.push({
      key: 'runtime',
      label: 'Runtime health',
      points,
      max: 10,
      detail: i.health ? `${i.health.status} · ${Object.keys(i.health.components).length} components` : 'health unknown',
      ok: points >= 10,
      known: Boolean(i.health),
    });
  }

  // Semantic guardrails (10)
  {
    const degraded = Boolean(i.statsDegraded) || Boolean(i.semanticDegraded);
    const points = degraded ? 5 : 10;
    factors.push({
      key: 'semantic',
      label: 'Semantic guardrails',
      points,
      max: 10,
      detail: degraded ? 'degraded (deterministic fallback)' : 'warm',
      ok: !degraded,
      known: i.statsDegraded !== undefined || i.semanticDegraded !== undefined,
    });
  }

  const score = Math.round(factors.reduce((a, f) => a + f.points, 0));
  const grade = score >= 90 ? 'A' : score >= 80 ? 'B' : score >= 70 ? 'C' : 'D';
  const tone = score >= 85 ? 'good' : score >= 70 ? 'warn' : 'bad';
  return { score, grade, tone, factors, toReview: factors.filter((f) => !f.ok).length };
}
