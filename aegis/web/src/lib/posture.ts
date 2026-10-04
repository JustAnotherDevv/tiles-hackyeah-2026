// Posture score (Addendum A-51). The server endpoint `GET /api/stats/posture` is AUTHORITATIVE; this module
// (1) types its response page-locally and maps it to the UI shape, and (2) implements the same formula
// client-side ONLY as the mock fallback when the endpoint is missing. Every component reports its points
// so the number is never magic. Owner: dashboard-shell (B16).
import type { AuditVerifyResult, ControlView, FeedStatus, HealthResponse } from '@/api/types';

export type PostureGrade = 'A' | 'A-' | 'B+' | 'B' | 'C' | 'D';

/** Page-local type for `GET /api/stats/posture` (A-51). */
export interface PostureResponse {
  generated_at: string;
  score: number;
  grade: PostureGrade;
  policy_version: number | null;
  feed_serial: number | null;
  components: { id: string; label: string; weight: number; score: number; value: string | number | null; status: 'ok' | 'warn' | 'error' | 'off' }[];
  findings: { severity: string; message: string; control_id: string | null; link: string | null }[];
}

export interface PostureInputs {
  controls?: ControlView[] | null;
  feed?: FeedStatus | null;
  audit?: AuditVerifyResult | null;
  health?: HealthResponse | null;
  statsDegraded?: boolean | null;
  semanticDegraded?: boolean | null;
  /** passed / total self-tests when known (excluded otherwise) */
  selftests?: { passed: number; total: number } | null;
  /** approvals.rules and budgets.limits non-empty (excluded when unknown) */
  governance?: boolean | null;
}

export interface PostureFactor {
  key: string;
  label: string;
  /** weighted points earned (score·weight) */
  points: number;
  /** weight */
  max: number;
  detail: string;
  ok: boolean;
  known: boolean;
}

export interface Posture {
  score: number;
  grade: PostureGrade;
  tone: 'good' | 'warn' | 'bad';
  factors: PostureFactor[];
  toReview: number;
  findings: PostureResponse['findings'];
  source: 'server' | 'client';
}

const round1 = (n: number) => Math.round(n * 10) / 10;

export function gradeFor(score: number): PostureGrade {
  return score >= 95 ? 'A' : score >= 90 ? 'A-' : score >= 85 ? 'B+' : score >= 80 ? 'B' : score >= 70 ? 'C' : 'D';
}

export function toneFor(score: number): Posture['tone'] {
  return score >= 85 ? 'good' : score >= 70 ? 'warn' : 'bad';
}

/** Map the authoritative server response to the UI shape. */
export function postureFromServer(r: PostureResponse): Posture {
  const factors = r.components.map((c) => ({
    key: c.id,
    label: c.label,
    points: round1(c.score * c.weight),
    max: c.weight,
    detail: c.value === null || c.value === undefined ? c.status : String(c.value),
    ok: c.score >= 0.999,
    known: c.status !== 'off',
  }));
  return { score: r.score, grade: r.grade, tone: toneFor(r.score), factors, toReview: factors.filter((f) => !f.ok).length, findings: r.findings ?? [], source: 'server' };
}

const FEED_SCORE: Record<FeedStatus['status'], number> = { ok: 1, seed: 0.7, rejected: 0.6, unreachable: 0.5, stale: 0.4, disabled: 0 };

/** Client-side mirror of the A-51 formula (mock fallback only). Unknown components are excluded. */
export function computePosture(i: PostureInputs): Posture {
  const comps: { key: string; label: string; weight: number; score: number | null; detail: string }[] = [];

  {
    const all = i.controls ?? null;
    const enforce = all?.filter((c) => c.implemented && c.enabled && c.mode === 'enforce').length ?? 0;
    const monitor = all?.filter((c) => c.implemented && c.enabled && c.mode === 'monitor').length ?? 0;
    const n = all?.length ?? 0;
    comps.push({
      key: 'controls',
      label: 'Controls enforced',
      weight: 35,
      score: all && n ? (enforce + monitor * 0.5) / n : null,
      detail: all ? `${enforce} enforce · ${monitor} monitor of ${n}` : 'controls unknown',
    });
  }
  comps.push({
    key: 'selftests',
    label: 'Self-tests passing',
    weight: 20,
    score: i.selftests && i.selftests.total > 0 ? i.selftests.passed / i.selftests.total : null,
    detail: i.selftests ? `${i.selftests.passed}/${i.selftests.total} passed` : 'not run yet',
  });
  comps.push({
    key: 'feed',
    label: 'Threat feed',
    weight: 15,
    score: i.feed ? FEED_SCORE[i.feed.status] : null,
    detail: i.feed ? `${i.feed.status}${i.feed.serial !== null ? ` · #${i.feed.serial}` : ''}` : 'feed unknown',
  });
  comps.push({
    key: 'audit',
    label: 'Audit chain',
    weight: 15,
    score: i.audit ? (i.audit.ok ? 1 : 0) : null,
    detail: i.audit ? (i.audit.ok ? `verified · ${i.audit.records} records` : `broken at seq ${i.audit.broken_at_seq ?? '?'}`) : 'not verified yet',
  });
  {
    const known = i.statsDegraded !== undefined && i.statsDegraded !== null ? true : i.semanticDegraded !== undefined && i.semanticDegraded !== null;
    const degraded = Boolean(i.statsDegraded) || Boolean(i.semanticDegraded);
    comps.push({ key: 'models', label: 'Semantic models', weight: 10, score: known ? (degraded ? 0.5 : 1) : null, detail: degraded ? 'degraded (deterministic fallback)' : 'warm' });
  }
  comps.push({
    key: 'governance',
    label: 'Governance rules & budgets',
    weight: 5,
    score: i.governance === null || i.governance === undefined ? null : i.governance ? 1 : 0,
    detail: i.governance ? 'approval rules + budgets configured' : 'unknown',
  });

  const known = comps.filter((c) => c.score !== null);
  const wsum = known.reduce((a, c) => a + c.weight, 0);
  const score = wsum ? Math.round((100 * known.reduce((a, c) => a + c.weight * (c.score ?? 0), 0)) / wsum) : 0;
  const factors: PostureFactor[] = comps.map((c) => ({
    key: c.key,
    label: c.label,
    points: round1((c.score ?? 0) * c.weight),
    max: c.weight,
    detail: c.score === null ? `${c.detail} (excluded)` : c.detail,
    ok: c.score !== null && c.score >= 0.999,
    known: c.score !== null,
  }));
  return { score, grade: gradeFor(score), tone: toneFor(score), factors, toReview: factors.filter((f) => f.known && !f.ok).length, findings: [], source: 'client' };
}
