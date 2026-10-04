// Org mutation helpers (UIG-10): client-side pre-checks that mirror CONTRACTS §5.4 PATCH rules (the
// server stays authoritative) and one result handler that turns 403 approval_required into a
// "Sent for owner approval" toast with an Open link. Owner: B18-dashboard-gov-approvals.
import { toast } from 'sonner';
import type { Member } from '@/api/types';
import type { ViewRole } from '@/lib/page';
import { assertApplied, errorTitle, parseApiError } from '../gov-api';

export interface Gate {
  ok: boolean;
  reason: string | null;
  /** The change is allowed to be *requested*, but needs someone else's approval. */
  needsApproval?: 'owner' | 'admin' | null;
}

const OK: Gate = { ok: true, reason: null, needsApproval: null };

export function canManage(viewerRole: ViewRole, capability: boolean): Gate {
  if (!capability || (viewerRole !== 'owner' && viewerRole !== 'admin'))
    return {
      ok: false,
      reason: 'Managing members and agents requires an admin or owner.',
    };
  return OK;
}

/** Can the viewer move `target` to `to`? (role menu items) */
export function roleChangeGate(viewerRole: ViewRole, viewerId: string | null, target: Member, to: Member['role'], ownerCount: number): Gate {
  if (viewerRole !== 'owner' && viewerRole !== 'admin') return { ok: false, reason: 'Managing members requires an admin.' };
  if (to === target.role) return { ok: false, reason: 'Current role' };
  if (target.id === viewerId)
    return {
      ok: false,
      reason: 'You cannot change your own role (separation of duties).',
    };
  if ((to === 'owner' || target.role === 'owner') && viewerRole !== 'owner')
    return {
      ok: false,
      reason: 'Only owners can grant or remove the owner role.',
    };
  if (target.role === 'owner' && ownerCount <= 1) return { ok: false, reason: 'The organization needs at least one owner.' };
  // org.role.* routes to `org-privileged` (owner); an admin may request it, an owner applies directly.
  if (viewerRole === 'admin') return { ok: true, reason: null, needsApproval: 'owner' };
  return OK;
}

export interface MutationOpts {
  pendingId: string;
  success: string;
  description?: string;
  openApproval: (approvalId: string) => void;
}

/** Run an org mutation and toast the real answer (403/409 are never mocked away). */
export async function runOrgMutation<T>(fn: () => Promise<T>, opts: MutationOpts): Promise<T | null> {
  try {
    const res = assertApplied(await fn());
    toast.success(opts.success, {
      id: opts.pendingId,
      description: opts.description,
    });
    return res;
  } catch (e) {
    const p = parseApiError(e);
    if (p.type === 'approval_required' && p.approval_id) {
      const approvalId = p.approval_id;
      toast.message(`Sent for ${p.required_role ?? 'owner'} approval`, {
        id: opts.pendingId,
        description: p.message,
        action: { label: 'Open', onClick: () => opts.openApproval(approvalId) },
      });
      return null;
    }
    toast.error(errorTitle(p), { id: opts.pendingId, description: p.message });
    return null;
  }
}

/** Team ids of a member (`meta.teams`, else `team_id`). */
export function memberTeams(m: Member): string[] {
  const t = m.meta?.teams;
  return Array.isArray(t) ? (t as string[]) : m.team_id ? [m.team_id] : [];
}
