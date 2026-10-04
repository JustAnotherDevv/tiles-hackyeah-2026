// Approvals page helpers: resolve the vote state (server truth first), list filtering and toasts.
// Owner: B18-dashboard-gov-approvals.
import { displayTitle } from '@/components/governance/lib/format-gov';
import { toast } from 'sonner';
import type { ApprovalRequest } from '@/api/types';
import type { Directory } from '../hooks';
import { approveCount, canVote, roleSatisfies, type Viewer, type VoteCheck } from '../lib/eligibility';

export type InboxTab = 'needs' | 'pending' | 'mine' | 'history';
export type KindFilter = 'all' | ApprovalRequest['kind'];

export interface VoteState {
  ok: boolean;
  reason: string | null;
  /** 'server' when can_vote/why_not came from the API for this viewer. */
  source: 'server' | 'client';
  code: VoteCheck['code'] | 'server';
}

export function sponsorIdOf(req: ApprovalRequest, dir: Directory): string | null {
  return req.requester.member_id ?? (req.requester.agent_id ? (dir.agentById.get(req.requester.agent_id)?.owner_member_id ?? null) : null);
}

/** Server `can_vote` / `why_not` win when they were fetched for the current viewer. */
export function resolveVote(req: ApprovalRequest, viewer: Viewer, dir: Directory, serverFresh: boolean, now: number): VoteState {
  const sponsorId = sponsorIdOf(req, dir);
  const client = canVote(viewer, req, now, { sponsorId, sponsorName: sponsorId ? dir.memberById.get(sponsorId)?.name : null });
  if (serverFresh && typeof req.can_vote === 'boolean') {
    // An expired-but-not-yet-swept item is locked client-side even if the server said yes a moment ago.
    if (req.can_vote && !client.ok && client.code === 'expired') return { ok: false, reason: client.reason, source: 'client', code: 'expired' };
    return { ok: req.can_vote, reason: req.can_vote ? null : (req.why_not ?? client.reason ?? 'Not allowed for this role.'), source: 'server', code: 'server' };
  }
  return { ok: client.ok, reason: client.reason, source: 'client', code: client.code };
}

export function isMine(req: ApprovalRequest, viewerId: string | null, dir: Directory): boolean {
  if (!viewerId) return false;
  return sponsorIdOf(req, dir) === viewerId;
}

export function sortInbox(items: ApprovalRequest[]): ApprovalRequest[] {
  return [...items].sort((a, b) => {
    if (a.status === 'pending' && b.status !== 'pending') return -1;
    if (b.status === 'pending' && a.status !== 'pending') return 1;
    if (a.status === 'pending') return Date.parse(b.created_at) - Date.parse(a.created_at);
    return Date.parse(b.decided_at ?? b.created_at) - Date.parse(a.decided_at ?? a.created_at);
  });
}

function timeOf(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '—';
}

/** Result toast for approve/deny/cancel (sonner id `apr-<id>` so it updates in place). */
export function toastDecision(res: ApprovalRequest, action: 'approve' | 'deny' | 'cancel', actorName: string): void {
  const id = `apr-${res.id}`;
  if (action === 'cancel') {
    toast.info('Request cancelled', { id, description: `${displayTitle(res.title)} — the requester receives 403 approval_denied (cancelled).` });
    return;
  }
  if (action === 'deny' || res.status === 'denied') {
    toast.error('Denied', { id, description: 'The requester receives 403 approval_denied with your reason. Audited as approval.denied.' });
    return;
  }
  if (res.status === 'pending') {
    const n = approveCount(res);
    const levelFilled = res.votes.some((v) => v.decision === 'approve' && roleSatisfies(v.role, res.required_role));
    const needs = levelFilled ? 'another admin or owner' : `an ${res.required_role}`;
    toast.success(`First approval recorded (${n} of 2)`, { id, description: `Two-person rule — needs ${needs} to co-sign.` });
    return;
  }
  const ex = (res.execution ?? {}) as Record<string, unknown>;
  const pv = typeof ex.policy_version === 'number' ? ex.policy_version : null;
  if (pv !== null) {
    const ms = typeof ex.latency_ms === 'number' ? ` in ${Math.round(ex.latency_ms)} ms` : '';
    toast.success(`Applied as policy v${pv}${ms}`, { id, description: `${displayTitle(res.title)} · approved by ${actorName}` });
    return;
  }
  const until = typeof ex.grant_expires_at === 'string' ? ex.grant_expires_at : res.expires_at;
  toast.success('Approved', {
    id,
    description: `Grant valid until ${timeOf(until)}, ${res.max_uses} use${res.max_uses === 1 ? '' : 's'} — the held call proceeds. Audited as approval.granted.`,
  });
}
