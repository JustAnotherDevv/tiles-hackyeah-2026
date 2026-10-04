// Viewer-aware mock factories for /api/approvals* (CONTRACTS §5.4). `can_vote` / `why_not` are
// computed per viewer with lib/eligibility so the "view as" switch works offline.
// Owner: B18-dashboard-gov-approvals.
import type { ApprovalRequest, ApprovalRoute, ApprovalSimulateRequest, ApprovalStatus, ApprovalsResponse } from '@/api/types';
import { govStore } from './store';

export type ApprovalStatusFilter = ApprovalStatus | 'all';

export function mockApprovals(viewerId: string | null, status: ApprovalStatusFilter = 'pending', kind?: string | null): ApprovalsResponse {
  const all = govStore.getApprovals();
  const counts: Record<ApprovalStatus, number> = { pending: 0, approved: 0, denied: 0, expired: 0, cancelled: 0 };
  for (const a of all) counts[a.status] += 1;
  const items = all
    .filter((a) => status === 'all' || a.status === status)
    .filter((a) => !kind || a.kind === kind)
    .map((a) => govStore.forViewer(a, viewerId));
  return { items, counts };
}

export function mockApproval(id: string, viewerId: string | null): ApprovalRequest {
  const a = govStore.getApproval(id);
  if (!a) throw Object.assign(new Error(`Approval ${id} not found (demo data)`), { status: 404 });
  return govStore.forViewer(a, viewerId);
}

export function mockVote(id: string, viewerId: string | null, decision: 'approve' | 'deny', comment: string | null): ApprovalRequest {
  return govStore.vote(id, viewerId, decision, comment);
}

export function mockCancel(id: string, viewerId: string | null): ApprovalRequest {
  return govStore.cancel(id, viewerId);
}

export function mockSimulate(req: ApprovalSimulateRequest): ApprovalRoute {
  return govStore.route(req);
}
