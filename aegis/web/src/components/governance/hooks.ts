// Governance data hooks on top of the shell hooks (`@/api/hooks`: useApi, useViewAs, useEvents).
// Every path carries `?view_as=` so a persona switch changes the path and refetches.
// Mock-store changes (UIG-11) trigger a refresh so offline approve/deny/vote flows update live.
// Owner: B18-dashboard-gov-approvals. (useProbeRunner lives in B19's policy/ folder.)
import { useEffect, useMemo, useState } from 'react';
import { useApi, useViewAs } from '@/api/hooks';
import type {
  Agent,
  ApprovalRequest,
  ApprovalRuleView,
  ApprovalRulesResponse,
  ApprovalsResponse,
  Member,
  OrgResponse,
  Role,
  WhoAmI,
} from '@/api/types';
import type { ViewRole } from '@/lib/page';
import { govStore } from '@/mocks/governance/store';
import { govMocks, govPaths, type ApprovalStatusFilter } from './gov-api';
import type { Viewer } from './lib/eligibility';

/** Re-run `refresh` whenever the offline mock store changes. */
function useMockStoreRefresh(refresh: () => void, enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    return govStore.subscribe(refresh);
  }, [refresh, enabled]);
}

export interface ViewerInfo {
  viewerId: string | null;
  role: ViewRole;
  member: Member | null;
  members: Member[];
  setViewAs: (id: string) => void;
  /** Input for lib/eligibility. */
  viewer: Viewer;
}

/** The "view as" persona (wraps the shell's useViewAs). */
export function useViewer(): ViewerInfo {
  const { member, role, members, setViewAs } = useViewAs();
  const viewerId = member?.id ?? null;
  const viewer = useMemo<Viewer>(() => ({ member_id: viewerId, role: role as Role }), [viewerId, role]);
  return { viewerId, role, member, members, setViewAs, viewer };
}

export function useWhoAmI() {
  const { viewerId } = useViewer();
  const res = useApi<WhoAmI>(govPaths.whoami(viewerId), { mock: govMocks.whoami(viewerId), refreshOn: ['org.updated'] });
  useMockStoreRefresh(res.refresh, res.isMock);
  return res;
}

export interface Directory {
  members: Member[];
  agents: Agent[];
  memberById: Map<string, Member>;
  agentById: Map<string, Agent>;
  isMock: boolean;
  loading: boolean;
  error: Error | null;
  refresh: () => void;
  /** Display name for a member or agent id. */
  nameOf: (id: string | null | undefined) => string;
  /** Sponsor member of an agent. */
  sponsorOf: (agentId: string | null | undefined) => Member | undefined;
}

/** Members + agents (for names, sponsors and eligible-approver lists). */
export function useDirectory(): Directory {
  const { viewerId } = useViewer();
  const m = useApi<{ items: Member[] }>(govPaths.members(viewerId), { mock: govMocks.members(), refreshOn: ['org.updated'] });
  const a = useApi<{ items: Agent[] }>(govPaths.agents(viewerId), { mock: govMocks.agents(), refreshOn: ['org.updated', 'killswitch'] });
  useMockStoreRefresh(m.refresh, m.isMock);
  useMockStoreRefresh(a.refresh, a.isMock);
  const members = useMemo(() => m.data?.items ?? [], [m.data]);
  const agents = useMemo(() => a.data?.items ?? [], [a.data]);
  return useMemo(() => {
    const memberById = new Map(members.map((x) => [x.id, x]));
    const agentById = new Map(agents.map((x) => [x.id, x]));
    return {
      members,
      agents,
      memberById,
      agentById,
      isMock: m.isMock || a.isMock,
      loading: m.loading || a.loading,
      error: m.error ?? a.error,
      refresh: () => {
        m.refresh();
        a.refresh();
      },
      nameOf: (id) => (id ? (memberById.get(id)?.name ?? agentById.get(id)?.name ?? id) : '—'),
      sponsorOf: (agentId) => {
        const ag = agentId ? agentById.get(agentId) : undefined;
        return ag?.owner_member_id ? memberById.get(ag.owner_member_id) : undefined;
      },
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [members, agents, m.isMock, a.isMock, m.loading, a.loading, m.error, a.error]);
}

export function useOrg() {
  const { viewerId } = useViewer();
  const res = useApi<OrgResponse>(govPaths.org(viewerId), { mock: govMocks.org(), refreshOn: ['org.updated'] });
  useMockStoreRefresh(res.refresh, res.isMock);
  return res;
}

export interface RulesInfo {
  data: ApprovalRulesResponse | undefined;
  all: ApprovalRuleView[];
  ruleById: Map<string, ApprovalRuleView>;
  isMock: boolean;
  loading: boolean;
  error: Error | null;
  refresh: () => void;
}

export function useApprovalRules(): RulesInfo {
  const res = useApi<ApprovalRulesResponse>(govPaths.approvalRules(), { mock: govMocks.approvalRules(), refreshOn: ['policy.applied'] });
  return useMemo(() => {
    const all = [...(res.data?.rules ?? []), ...(res.data?.config_rules ?? [])];
    return {
      data: res.data,
      all,
      ruleById: new Map(all.map((r) => [r.id, r])),
      isMock: res.isMock,
      loading: res.loading,
      error: res.error,
      refresh: res.refresh,
    };
  }, [res.data, res.isMock, res.loading, res.error, res.refresh]);
}

/** Approvals list for the current viewer (status filter), live via SSE + polling. */
export function useApprovals(status: ApprovalStatusFilter = 'pending') {
  const { viewerId } = useViewer();
  const res = useApi<ApprovalsResponse>(govPaths.approvals(viewerId, status), {
    mock: govMocks.approvals(viewerId, status),
    refreshOn: ['approval.created', 'approval.updated'],
    refreshMs: 10000,
  });
  useMockStoreRefresh(res.refresh, res.isMock);
  return res;
}

/** Single approval (deep link fallback when it isn't in the current list). */
export function useApproval(id: string | null) {
  const { viewerId } = useViewer();
  const res = useApi<ApprovalRequest>(id ? govPaths.approval(id, viewerId) : null, {
    mock: id ? govMocks.approval(id, viewerId) : undefined,
    refreshOn: ['approval.updated'],
  });
  useMockStoreRefresh(res.refresh, res.isMock);
  return res;
}

/** Ticking clock (ms) for countdowns. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** Capability check that tolerates both `permissions` (frozen type) and a future `capabilities` map. */
export function hasCapability(who: WhoAmI | undefined, cap: 'members.manage' | 'killswitch' | 'audit.export', role: ViewRole): boolean {
  const caps = (who as unknown as { capabilities?: Record<string, boolean> } | undefined)?.capabilities;
  if (caps && typeof caps[cap] === 'boolean') return caps[cap];
  const p = who?.permissions;
  if (p) {
    if (cap === 'members.manage') return p.can_manage_members;
    if (cap === 'killswitch') return p.can_killswitch;
    if (cap === 'audit.export') return p.can_export_audit;
  }
  return role === 'owner' || role === 'admin';
}
