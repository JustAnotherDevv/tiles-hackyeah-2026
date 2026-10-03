// Demo cast (CONTRACTS §4.5 ids are binding; names/titles from docs/seed-fixes/org.seed.yaml).
// Mock fallback for /api/members, /api/whoami, /api/org, /api/agents. Owner: dashboard-shell (B16).
import type { Agent, ApprovalsResponse, Identity, Member, OrgResponse, Permissions, WhoAmI } from '@/api/types';

export const ORG_ID = 'acme-capital';
export const ORG_NAME = 'Acme Capital';
const at = '2026-10-01T08:00:00Z';

function m(id: string, name: string, role: Member['role'], team_id: string, title: string, teams: string[] = [team_id]): Member {
  const handle = id.slice(2);
  return {
    id,
    org_id: ORG_ID,
    team_id,
    name,
    email: `${handle}@acme-capital.example`,
    role,
    title,
    avatar_url: null,
    active: true,
    created_at: at,
    meta: { teams },
    agents: [],
  };
}

export const MOCK_MEMBERS: Member[] = [
  m('u_katarzyna', 'Katarzyna Wiśniewska', 'owner', 'trading', 'Managing Partner & Chief Risk Officer', ['trading', 'research', 'platform']),
  m('u_marek', 'Marek Kowalczyk', 'admin', 'platform', 'Head of Platform & AI Security'),
  m('u_emily', 'Emily Carter', 'admin', 'trading', 'Head of Trading & Research', ['trading', 'research']),
  m('u_piotr', 'Piotr Zieliński', 'member', 'trading', 'Senior Trader'),
  m('u_olivia', 'Olivia Bennett', 'member', 'trading', 'Quant Analyst'),
  m('u_agnieszka', 'Agnieszka Lewandowska', 'member', 'research', 'Equity Research Analyst'),
  m('u_james', "James O'Connor", 'member', 'research', 'Research Data Scientist'),
  m('u_tomasz', 'Tomasz Wójcik', 'member', 'platform', 'Platform / SRE Engineer'),
];
MOCK_MEMBERS.find((x) => x.id === 'u_piotr')!.agents = ['trading-copilot@trading'];
MOCK_MEMBERS.find((x) => x.id === 'u_agnieszka')!.agents = ['research-agent@research'];
MOCK_MEMBERS.find((x) => x.id === 'u_tomasz')!.agents = ['claude-code@platform', 'chaos-agent@platform'];

/** Quick picks for the topbar "View as" segmented control. */
export const VIEW_AS_QUICK: { role: Member['role']; id: string }[] = [
  { role: 'owner', id: 'u_katarzyna' },
  { role: 'admin', id: 'u_emily' },
  { role: 'member', id: 'u_piotr' },
];

export const DEFAULT_VIEWER = 'u_katarzyna';

function agent(id: string, name: string, team_id: string, owner: string, kind: Agent['kind'], maxDest: Agent['max_destination'], spend: number, models: string[]): Agent {
  return {
    id,
    org_id: ORG_ID,
    team_id,
    owner_member_id: owner,
    name,
    kind,
    description: null,
    profile: null,
    allowed_models: models,
    allowed_tools: [],
    denied_tools: [],
    max_destination: maxDest,
    active: true,
    created_at: at,
    last_seen: new Date().toISOString(),
    meta: {},
    status: 'active',
    spend_today_usd: spend,
  };
}

export const MOCK_AGENTS: Agent[] = [
  agent('claude-code@platform', 'Claude Code (Platform)', 'platform', 'u_tomasz', 'claude-code', 'remote', 6.42, ['claude-sonnet-4-5', 'claude-haiku-4-5']),
  agent('research-agent@research', 'Research Agent (local)', 'research', 'u_agnieszka', 'scripted', 'local', 0.38, ['aegis-judge']),
  agent('trading-copilot@trading', 'Trading Copilot (remote)', 'trading', 'u_piotr', 'sdk', 'remote', 4.91, ['gpt-4o-mini', 'aegis-judge']),
  agent('chaos-agent@platform', 'Chaos Agent (red team)', 'platform', 'u_tomasz', 'other', 'remote', 0.47, ['mock-echo']),
];

export const AGENT_IDS = MOCK_AGENTS.map((a) => a.id);

export function mockMembers(): { items: Member[] } {
  return { items: MOCK_MEMBERS };
}

export function mockAgents(): { items: Agent[] } {
  return { items: MOCK_AGENTS };
}

export function memberById(id: string | null | undefined): Member | undefined {
  return MOCK_MEMBERS.find((x) => x.id === id);
}

export function identityForAgent(agentId: string): Identity {
  const a = MOCK_AGENTS.find((x) => x.id === agentId);
  return { org_id: ORG_ID, team_id: a?.team_id ?? null, member_id: a?.owner_member_id ?? null, agent_id: agentId, role: 'agent', display_name: agentId, authenticated: true };
}

export function identityForMember(memberId: string): Identity {
  const mem = memberById(memberId);
  return { org_id: ORG_ID, team_id: mem?.team_id ?? null, member_id: memberId, agent_id: null, role: mem?.role ?? 'member', display_name: mem?.name ?? memberId, authenticated: true };
}

function permissionsFor(role: Member['role']): Permissions {
  return {
    can_apply_policy: role === 'owner' ? 'yes' : role === 'admin' ? 'approval' : 'approval',
    can_manage_members: role !== 'member',
    can_killswitch: role !== 'member',
    can_export_audit: role !== 'member',
    approver_levels: role === 'owner' ? ['auto', 'self', 'admin', 'owner'] : role === 'admin' ? ['auto', 'self', 'admin'] : ['auto', 'self'],
  };
}

export function whoamiFor(id: string | null): WhoAmI {
  const mem = memberById(id) ?? memberById(DEFAULT_VIEWER)!;
  return { identity: identityForMember(mem.id), member: mem, permissions: permissionsFor(mem.role) };
}

export function mockOrg(): OrgResponse {
  const teams = [
    { id: 'trading', name: 'Trading', description: 'Front-office trading desk' },
    { id: 'research', name: 'Research', description: 'Equity research (local-first)' },
    { id: 'platform', name: 'Platform', description: 'Platform engineering & AI security' },
  ];
  return {
    org: { id: ORG_ID, name: ORG_NAME },
    teams: teams.map((t) => ({
      ...t,
      org_id: ORG_ID,
      color: null,
      meta: {},
      member_count: MOCK_MEMBERS.filter((x) => x.team_id === t.id).length,
      agent_count: MOCK_AGENTS.filter((x) => x.team_id === t.id).length,
    })),
    counts: { members: MOCK_MEMBERS.length, agents: MOCK_AGENTS.length, teams: teams.length },
  };
}

/** Minimal pending-approvals mock for the shell badge (governance pages own the rich mocks). */
export function mockApprovalsPending(): ApprovalsResponse {
  const now = Date.now();
  const base = {
    org_id: ORG_ID,
    labels: {},
    payload: {},
    fingerprint: 'fp_mock',
    two_person: false,
    rule_id: null,
    votes: [],
    status: 'pending' as const,
    expires_at: new Date(now + 3600_000).toISOString(),
    decided_at: null,
    decided_by: [],
    request_id: null,
    decision_id: null,
    uses: 0,
    max_uses: 1,
    execution: null,
  };
  return {
    items: [
      {
        ...base,
        id: 'apr_mock_marketpulse',
        team_id: 'trading',
        kind: 'action',
        action_type: 'spend.subscription',
        title: 'MarketPulse Pro subscription · $50.00 / month',
        summary: 'trading-copilot@trading wants to subscribe to MarketPulse Pro',
        requester: identityForAgent('trading-copilot@trading'),
        amount_usd: 50,
        resource: 'vendor:marketpulse',
        required_role: 'admin',
        created_at: new Date(now - 4 * 60_000).toISOString(),
        control_id: 'ACT-01',
        can_vote: true,
        why_not: null,
      },
      {
        ...base,
        id: 'apr_mock_customers',
        team_id: 'platform',
        kind: 'action',
        action_type: 'db.read',
        title: 'Read customers table (CONFIDENTIAL) · acme-db',
        summary: 'claude-code@platform: SELECT * FROM customers',
        requester: identityForAgent('claude-code@platform'),
        amount_usd: null,
        resource: 'db:customers',
        required_role: 'admin',
        created_at: new Date(now - 11 * 60_000).toISOString(),
        control_id: 'ACT-02',
        can_vote: true,
        why_not: null,
      },
    ],
    counts: { pending: 2, approved: 5, denied: 1, expired: 0, cancelled: 0 },
  };
}
