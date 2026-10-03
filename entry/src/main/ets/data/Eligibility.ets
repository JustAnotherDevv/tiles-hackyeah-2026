import { ApprovalItem, Persona, roleRank } from '../model/Models';

/** Sponsors of the demo agents (aegis/docs/CONTRACTS.md §4.5). */
export const AGENT_SPONSORS: Record<string, string> = {
  'trading-copilot@trading': 'u_piotr',
  'research-agent@research': 'u_agnieszka',
  'claude-code@platform': 'u_tomasz',
  'chaos-agent@platform': 'u_tomasz'
};

export function sponsorOf(agentId: string): string {
  const s: string | undefined = AGENT_SPONSORS[agentId];
  return s !== undefined ? s : '';
}

export class Eligibility {
  canVote: boolean;
  whyNot: string;

  constructor(canVote: boolean, whyNot: string) {
    this.canVote = canVote;
    this.whyNot = whyNot;
  }
}

/**
 * On-device mirror of the gateway's approval eligibility rules (CONTRACTS Addendum A-20):
 * role rank must satisfy the level, separation of duties for admin/owner levels,
 * agents never vote, and the two-person rule (one approver satisfies the level, the other is admin+).
 * Used by the mock repository; in live mode the gateway's `can_vote` / `why_not` are authoritative.
 */
export function checkEligibility(item: ApprovalItem, viewer: Persona): Eligibility {
  if (item.status !== 'pending') {
    return new Eligibility(false, 'Already ' + item.status);
  }
  for (const v of item.votes) {
    if (v.memberId === viewer.id) {
      return new Eligibility(false, 'You already voted on this request');
    }
  }
  if (item.requiredRole === 'deny') {
    return new Eligibility(false, 'Blocked by policy: nobody can approve this');
  }
  if (item.requiredRole === 'auto') {
    return new Eligibility(false, 'Auto-approved by policy');
  }
  const rank: number = roleRank(viewer.role);
  const isSponsor: boolean = viewer.id === item.requesterMember ||
    (item.requesterAgent.length > 0 && sponsorOf(item.requesterAgent) === viewer.id);

  if (item.requiredRole === 'self') {
    if (isSponsor || rank >= 2) {
      return new Eligibility(true, '');
    }
    return new Eligibility(false, 'Requires the agent sponsor or an admin');
  }

  const need: number = roleRank(item.requiredRole);
  if (isSponsor) {
    return new Eligibility(false, 'Separation of duties: you requested or sponsor this');
  }
  if (!item.twoPerson) {
    if (rank < need) {
      return new Eligibility(false, 'Requires ' + item.requiredRole + ' (you are ' + viewer.role + ')');
    }
    return new Eligibility(true, '');
  }
  // Two-person rule: both approvers must be admin+, and at least one must satisfy the level.
  if (rank < 2) {
    return new Eligibility(false, 'Requires ' + item.requiredRole + ' + admin (two-person rule)');
  }
  let levelSatisfied: boolean = false;
  let approveVotes: number = 0;
  for (const v of item.votes) {
    if (v.decision === 'approve') {
      approveVotes++;
      if (roleRank(v.role) >= need) {
        levelSatisfied = true;
      }
    }
  }
  if (approveVotes >= 1 && !levelSatisfied && rank < need) {
    return new Eligibility(false, 'Second approver must be ' + item.requiredRole);
  }
  return new Eligibility(true, '');
}

/** True when the approve votes complete the request. */
export function approvalComplete(item: ApprovalItem): boolean {
  let approveVotes: number = 0;
  let levelSatisfied: boolean = false;
  const need: number = roleRank(item.requiredRole);
  for (const v of item.votes) {
    if (v.decision === 'approve') {
      approveVotes++;
      if (item.requiredRole === 'self' || roleRank(v.role) >= need) {
        levelSatisfied = true;
      }
    }
  }
  if (item.twoPerson) {
    return approveVotes >= 2 && levelSatisfied;
  }
  return approveVotes >= 1 && levelSatisfied;
}
