// Demo cast (CONTRACTS §4.5 ids are binding) for security mocks.
// Owner: dashboard-security.
import type { Agent, Identity } from '@/api/types';

export const ORG_ID = 'acme-capital';
const at = '2026-10-03T08:00:00Z';

function agent(
  id: string,
  name: string,
  team: string,
  owner: string,
  kind: Agent['kind'],
  max: Agent['max_destination'],
  models: string[],
  tools: string[],
  description: string,
): Agent {
  return {
    id,
    org_id: ORG_ID,
    team_id: team,
    owner_member_id: owner,
    name,
    kind,
    description,
    profile: null,
    allowed_models: models,
    allowed_tools: tools,
    denied_tools: [],
    max_destination: max,
    active: true,
    created_at: at,
    last_seen: null,
    meta: {},
    status: 'active',
    spend_today_usd: 0,
  };
}

export const MOCK_AGENTS: Agent[] = [
  agent('claude-code@platform', 'Claude Code', 'platform', 'u_tomasz', 'claude-code', 'remote', ['claude-sonnet-*', 'claude-haiku-*', 'mock-*'], ['Bash', 'Read', 'Edit', 'WebFetch', 'mcp__*'], 'Claude Code via ANTHROPIC_BASE_URL + hooks + MCP proxy'),
  agent('research-agent@research', 'Research agent', 'research', 'u_agnieszka', 'scripted', 'local', ['aegis-judge', 'qwen3:0.6b'], ['acme-db.query', 'web.fetch_url'], 'Local-first Ollama agent'),
  agent('trading-copilot@trading', 'Trading copilot', 'trading', 'u_piotr', 'sdk', 'remote', ['gpt-4.1-mini', 'mock-*'], ['marketpulse.*', 'acme-db.query', 'mailer.send_email'], 'Spends on MarketPulse, reads customers, emails clients'),
  agent('chaos-agent@platform', 'Chaos agent', 'platform', 'u_tomasz', 'other', 'remote', ['mock-*'], ['*'], 'Red-team / runaway-loop agent with tiny budgets'),
];

export const AGENT_IDS = MOCK_AGENTS.map((a) => a.id);

export function agentIdentity(agentId: string): Identity {
  const a = MOCK_AGENTS.find((x) => x.id === agentId);
  return {
    org_id: ORG_ID,
    team_id: a?.team_id ?? null,
    member_id: a?.owner_member_id ?? null,
    agent_id: agentId,
    role: 'agent',
    display_name: agentId,
    authenticated: true,
  };
}

const MEMBER_TEAM: Record<string, [string, Identity['role']]> = {
  u_katarzyna: ['platform', 'owner'],
  u_marek: ['platform', 'admin'],
  u_emily: ['trading', 'admin'],
  u_piotr: ['trading', 'member'],
  u_olivia: ['trading', 'member'],
  u_james: ['research', 'member'],
  u_agnieszka: ['research', 'member'],
  u_tomasz: ['platform', 'member'],
};

export function memberIdentity(memberId: string): Identity {
  const [team, role] = MEMBER_TEAM[memberId] ?? ['platform', 'member'];
  return { org_id: ORG_ID, team_id: team, member_id: memberId, agent_id: null, role, display_name: memberId, authenticated: true };
}

export function mockAgents(): { items: Agent[] } {
  return { items: MOCK_AGENTS };
}
