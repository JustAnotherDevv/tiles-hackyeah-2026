// Approval eligibility — pure, erasable TS (Node type-stripping friendly: type-only imports, no enums,
// no relative value imports). Encodes CONTRACTS §3.5 "Approval semantics" + seed-fix SF-01
// (two-person = two distinct admin+ approvers, at least one satisfying the required level).
// The server's `can_vote` / `why_not` always win; this is the client fallback (SSE upserts, mocks,
// eligible-approver lists, pre-disabling buttons). Owner: B18-dashboard-gov-approvals.
import type { ApprovalRequest, ApproverLevel, Member, Role } from '@/api/types';

export interface Viewer {
  member_id: string | null;
  role: Role;
}

export interface VoteCheck {
  ok: boolean;
  reason: string | null;
  /** Machine code so callers can pick icons/tones without parsing prose. */
  code:
    | 'ok'
    | 'agent'
    | 'no_viewer'
    | 'not_pending'
    | 'expired'
    | 'already_voted'
    | 'deny_rule'
    | 'auto_rule'
    | 'sod'
    | 'role_too_low'
    | 'second_slot_needs_level';
}

export interface EligibilityOpts {
  /** Sponsor (owner_member_id) of an agent requester when `requester.member_id` is missing. */
  sponsorId?: string | null;
  /** Display names for nicer reasons. */
  sponsorName?: string | null;
  requesterName?: string | null;
}

const RANK: Record<string, number> = { agent: 0, member: 1, admin: 2, owner: 3 };

const LEVEL_WORD: Record<ApproverLevel, string> = {
  auto: 'nobody (auto)',
  self: 'the requester',
  admin: 'an admin',
  owner: 'an owner',
  deny: 'nobody',
};

function rank(role: Role | string | null | undefined): number {
  return role ? (RANK[role] ?? 0) : 0;
}

/** True when a person with `role` satisfies an approver `level` on its own (ignores SoD/self). */
export function roleSatisfies(role: Role | string, level: ApproverLevel | null | undefined): boolean {
  if (!level) return true;
  switch (level) {
    case 'auto':
      return true;
    case 'deny':
      return false;
    case 'self':
      return rank(role) >= 1;
    case 'admin':
      return rank(role) >= 2;
    case 'owner':
      return rank(role) >= 3;
    default:
      return false;
  }
}

export function approvalsNeeded(req: Pick<ApprovalRequest, 'two_person'>): number {
  return req.two_person ? 2 : 1;
}

export function approveCount(req: Pick<ApprovalRequest, 'votes'>): number {
  return (req.votes ?? []).filter((v) => v.decision === 'approve').length;
}

export function isExpired(req: Pick<ApprovalRequest, 'expires_at' | 'status'>, now: number): boolean {
  if (req.status === 'expired') return true;
  if (!req.expires_at) return false;
  const t = Date.parse(req.expires_at);
  return Number.isFinite(t) && t <= now;
}

export function isAgentRequest(req: Pick<ApprovalRequest, 'requester'>): boolean {
  return Boolean(req.requester?.agent_id) || req.requester?.role === 'agent';
}

/** The member who "owns" the request: the human requester, or the agent's sponsor. */
export function requesterMemberId(req: Pick<ApprovalRequest, 'requester'>, opts: EligibilityOpts = {}): string | null {
  return req.requester?.member_id ?? opts.sponsorId ?? null;
}

function agentLabel(req: Pick<ApprovalRequest, 'requester'>): string {
  return req.requester?.agent_id ?? req.requester?.display_name ?? 'this agent';
}

export function capitalLevel(level: ApproverLevel): string {
  const w = LEVEL_WORD[level];
  return w.charAt(0).toUpperCase() + w.slice(1);
}

/**
 * Level check without request state (status/expiry/votes): can this person ever fill a slot?
 * Used for eligible-approver lists and as the core of `canVote`.
 */
export function levelCheck(viewer: Viewer, req: ApprovalRequest, opts: EligibilityOpts = {}): VoteCheck {
  const level = req.required_role;
  if (viewer.role === 'agent') return { ok: false, code: 'agent', reason: 'Agents are service identities — they can request approvals but never approve.' };
  if (!viewer.member_id) return { ok: false, code: 'no_viewer', reason: 'Pick a person in "View as" to vote.' };
  if (level === 'deny') {
    return { ok: false, code: 'deny_rule', reason: `No one can approve this — rule ${req.rule_id ?? '(default)'} denies it outright.` };
  }
  if (level === 'auto') {
    return { ok: false, code: 'auto_rule', reason: `Auto-approved by rule ${req.rule_id ?? '(default)'} — nothing to vote on.` };
  }
  const own = requesterMemberId(req, opts);
  const isOwn = own !== null && own === viewer.member_id;
  const r = rank(viewer.role);

  if (level === 'self') {
    if (isOwn || r >= 2) return { ok: true, code: 'ok', reason: null };
    const who = isAgentRequest(req)
      ? `${opts.sponsorName ?? own ?? 'the sponsor'} (sponsor of ${agentLabel(req)})`
      : (opts.requesterName ?? own ?? 'the requester');
    return { ok: false, code: 'role_too_low', reason: `Only ${who} or an admin/owner can approve this.` };
  }

  // admin / owner levels: separation of duties first — it is the most informative reason.
  if (isOwn) {
    const why = isAgentRequest(req)
      ? `you sponsor ${agentLabel(req)} (separation of duties)`
      : 'you requested this yourself (separation of duties)';
    return { ok: false, code: 'sod', reason: `Needs ${LEVEL_WORD[level]} — ${why}` };
  }

  if (req.two_person) {
    // SF-01: two distinct approvers, both admin+, at least one satisfying the level.
    if (r < 2) {
      return { ok: false, code: 'role_too_low', reason: `Needs ${LEVEL_WORD[level]} — two-person rule: ${level} + a second admin. You are a ${viewer.role}.` };
    }
    if (roleSatisfies(viewer.role, level)) return { ok: true, code: 'ok', reason: null };
    return { ok: true, code: 'ok', reason: null }; // admin may fill the second slot; refined in canVote
  }

  if (!roleSatisfies(viewer.role, level)) {
    return { ok: false, code: 'role_too_low', reason: `Needs ${LEVEL_WORD[level]} — you are viewing as ${viewer.role === 'admin' ? 'an admin' : 'a member'}.` };
  }
  return { ok: true, code: 'ok', reason: null };
}

/** Full check for the current viewer, including status, expiry, prior votes and two-person slots. */
export function canVote(viewer: Viewer, req: ApprovalRequest, now: number = Date.now(), opts: EligibilityOpts = {}): VoteCheck {
  if (viewer.role === 'agent') return levelCheck(viewer, req, opts);
  if (req.status !== 'pending') return { ok: false, code: 'not_pending', reason: `Already ${req.status}.` };
  if (isExpired(req, now)) return { ok: false, code: 'expired', reason: 'Expired — the request is closed (expired ⇒ denied).' };
  if (viewer.member_id && (req.votes ?? []).some((v) => v.member_id === viewer.member_id)) {
    return {
      ok: false,
      code: 'already_voted',
      reason: req.two_person
        ? 'You already approved — the two-person rule needs a different approver.'
        : 'You already voted on this request.',
    };
  }
  const base = levelCheck(viewer, req, opts);
  if (!base.ok) return base;

  if (req.two_person && !roleSatisfies(viewer.role, req.required_role)) {
    // Viewer is an admin on an owner-level two-person item: allowed only while the owner slot is
    // still fillable by someone else, i.e. no other non-owner approval already took the admin slot.
    const approvals = (req.votes ?? []).filter((v) => v.decision === 'approve');
    const levelFilled = approvals.some((v) => roleSatisfies(v.role, req.required_role));
    if (approvals.length >= 1 && !levelFilled) {
      return {
        ok: false,
        code: 'second_slot_needs_level',
        reason: `The remaining slot needs ${LEVEL_WORD[req.required_role]} — an admin already approved (two-person: ${req.required_role} + admin).`,
      };
    }
  }
  return base;
}

/** People who could act on this request right now (ignores expiry so locked cards still list them). */
export function eligibleApprovers(req: ApprovalRequest, members: Member[], opts: EligibilityOpts = {}): Member[] {
  const pendingReq: ApprovalRequest = { ...req, status: 'pending', expires_at: null };
  return members.filter((m) => m.active !== false && canVote({ member_id: m.id, role: m.role }, pendingReq, 0, opts).ok);
}

/** "Why this role?" paragraph. */
export function explainLevel(
  req: ApprovalRequest,
  ctx: { sponsorName?: string | null; requesterName?: string | null; ruleText?: string | null } = {},
): string {
  const rule = req.rule_id ? `Rule ${req.rule_id}` : 'The default route';
  const cond = ctx.ruleText ? ` (${ctx.ruleText})` : '';
  const agent = isAgentRequest(req);
  const owner = agent ? (ctx.sponsorName ?? 'its sponsor') : (ctx.requesterName ?? 'the requester');
  const parts: string[] = [];
  switch (req.required_role) {
    case 'deny':
      parts.push(`${rule}${cond} denies this outright — no role can approve it. The requester receives 403 approval_denied.`);
      break;
    case 'auto':
      parts.push(`${rule}${cond} approves this automatically; it is still written to the audit log.`);
      break;
    case 'self':
      parts.push(
        agent
          ? `${rule}${cond} lets the requester confirm this themselves. For an agent, its sponsor (${owner}) fills the self slot — an agent never approves itself. Any admin or owner may also approve.`
          : `${rule}${cond} lets ${owner} confirm this themselves; any admin or owner may also approve.`,
      );
      break;
    case 'admin':
    case 'owner':
      parts.push(`${rule}${cond} routes this to ${LEVEL_WORD[req.required_role]}${req.required_role === 'admin' ? ' (or an owner)' : ''}.`);
      parts.push(
        agent
          ? `Separation of duties: ${owner} sponsors ${agentLabel(req)}, so they cannot approve their own agent's request.`
          : `Separation of duties: ${owner} cannot approve their own request.`,
      );
      break;
  }
  if (req.two_person) {
    parts.push(
      `Two-person rule: ${approvalsNeeded(req)} distinct approvers — at least one ${req.required_role === 'owner' ? 'owner' : 'admin'}, the other an admin or owner. Any eligible deny rejects it.`,
    );
  }
  return parts.join(' ');
}

/** Short label for buttons/badges, e.g. "Requires admin". */
export function levelShort(level: ApproverLevel): string {
  switch (level) {
    case 'self':
      return 'Self-approve';
    case 'auto':
      return 'Auto-approved';
    case 'deny':
      return 'Denied by rule';
    default:
      return `Requires ${level}`;
  }
}

/** Label for the primary approve button for this viewer. */
export function approveLabel(req: ApprovalRequest, viewer?: Viewer | null, opts: EligibilityOpts = {}): string {
  if (req.two_person) {
    const n = approveCount(req);
    return `Approve (${Math.min(n + 1, 2)} of 2)`;
  }
  if (req.required_role === 'self' && viewer && viewer.member_id === requesterMemberId(req, opts)) return 'Self-approve';
  return 'Approve';
}
