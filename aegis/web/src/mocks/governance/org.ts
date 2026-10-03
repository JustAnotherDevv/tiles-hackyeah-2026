// Mock factories for /api/org, /api/members, /api/agents, /api/whoami and their mutations.
// Owner: B18-dashboard-gov-approvals.
import type { Agent, ApproverLevel, Member, OrgResponse, Permissions, WhoAmI } from '@/api/types';
import { orgResponse } from './fixtures';
import { govStore, MockApiError } from './store';

export function mockOrg(): OrgResponse {
  return orgResponse(govStore.getMembers(), govStore.getAgents());
}

export function mockMembersList(): { items: Member[] } {
  return { items: govStore.getMembers() };
}

export function mockAgentsList(): { items: Agent[] } {
  return { items: govStore.getAgents() };
}

export function permissionsFor(role: Member['role'] | 'agent'): Permissions {
  const levels: ApproverLevel[] = role === 'owner' ? ['self', 'admin', 'owner'] : role === 'admin' ? ['self', 'admin'] : role === 'member' ? ['self'] : [];
  return {
    can_apply_policy: role === 'owner' ? 'yes' : role === 'agent' ? 'no' : 'approval',
    can_manage_members: role === 'owner' || role === 'admin',
    can_killswitch: role === 'owner' || role === 'admin',
    can_export_audit: role === 'owner' || role === 'admin',
    approver_levels: levels,
  };
}

export function mockWhoAmI(viewerId: string | null): WhoAmI {
  const members = govStore.getMembers();
  const m = members.find((x) => x.id === viewerId) ?? members.find((x) => x.role === 'owner') ?? null;
  return {
    identity: {
      org_id: 'acme-capital',
      team_id: m?.team_id ?? null,
      member_id: m?.id ?? null,
      agent_id: null,
      role: m?.role ?? 'owner',
      display_name: m?.name ?? null,
      authenticated: false,
    },
    member: m,
    permissions: permissionsFor(m?.role ?? 'owner'),
  };
}

export function mockPatchMember(id: string, patch: { role?: Member['role']; team_id?: string | null; active?: boolean }, viewerId: string | null): Member {
  return govStore.patchMember(id, patch, viewerId);
}

export function mockPatchAgent(id: string, patch: { active?: boolean }, viewerId: string | null): Agent {
  return govStore.patchAgent(id, patch, viewerId);
}

export function mockCreateMember(): Member {
  throw new MockApiError(501, 'not_implemented', 'Inviting members is not available in demo data.');
}
