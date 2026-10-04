// Governance demo fixtures: the Acme Capital cast (CONTRACTS §4.5 ids; names/titles/colours from
// staging/seed/org.seed.yaml), teams, agents, approval rules (docs/seed-fixes/approvals.yaml ids)
// and the F4/F5 approval scenarios (SCENARIOS Appendix A). Read-only data + factories; mutable
// state lives in ./store.ts. Owner: B18-dashboard-gov-approvals.
import type {
  Agent,
  ApprovalRequest,
  ApprovalRuleView,
  ApprovalRulesResponse,
  Identity,
  Member,
  OrgResponse,
  Team,
} from '@/api/types';

export const ORG_ID = 'acme-capital';
const CREATED = '2026-10-03T09:00:00Z';

// ------------------------------------------------------------------ teams
export const TEAMS: Team[] = [
  { id: 'trading', org_id: ORG_ID, name: 'Trading', color: '#f59e0b', description: 'Equities and FX desk. Remote AI copilot, market-data SaaS, client comms.', meta: { lead: 'u_emily', data_ceiling: 'CONFIDENTIAL', default_destination: 'remote' } },
  { id: 'research', org_id: ORG_ID, name: 'Research', color: '#10b981', description: 'Equity research. Local-first — prefers Ollama so client data never leaves the laptop.', meta: { lead: 'u_emily', data_ceiling: 'CONFIDENTIAL', default_destination: 'local' } },
  { id: 'platform', org_id: ORG_ID, name: 'Platform', color: '#3b82f6', description: 'Internal engineering, infra and the AI platform itself (runs Aegis).', meta: { lead: 'u_marek', data_ceiling: 'INTERNAL', default_destination: 'remote' } },
];

// ------------------------------------------------------------------ members
function member(
  id: string,
  name: string,
  role: Member['role'],
  teams: string[],
  title: string,
  avatar_color: string,
  agents: string[] = [],
): Member {
  const local = name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/ł/g, 'l')
    .replace(/'/g, '')
    .toLowerCase()
    .split(' ')
    .join('.');
  return {
    id,
    org_id: ORG_ID,
    team_id: teams[0] ?? null,
    name,
    email: `${local}@acme-capital.example`,
    role,
    title,
    avatar_url: null,
    active: true,
    created_at: CREATED,
    meta: { teams, avatar_color, view_as_label: `${role.charAt(0).toUpperCase()}${role.slice(1)} - ${name.split(' ')[0]}` },
    agents,
  };
}

export const MEMBERS: Member[] = [
  member('u_katarzyna', 'Katarzyna Wiśniewska', 'owner', ['trading', 'research', 'platform'], 'Managing Partner & Chief Risk Officer', '#7c3aed'),
  member('u_marek', 'Marek Kowalczyk', 'admin', ['platform'], 'Head of Platform & AI Security', '#3b82f6'),
  member('u_emily', 'Emily Carter', 'admin', ['trading', 'research'], 'Head of Trading & Research', '#f59e0b'),
  member('u_piotr', 'Piotr Zieliński', 'member', ['trading'], 'Senior Trader', '#ef4444', ['trading-copilot@trading']),
  member('u_olivia', 'Olivia Bennett', 'member', ['trading'], 'Quant Analyst', '#ec4899'),
  member('u_agnieszka', 'Agnieszka Lewandowska', 'member', ['research'], 'Equity Research Analyst', '#10b981', ['research-agent@research']),
  member('u_james', "James O'Connor", 'member', ['research'], 'Research Data Scientist', '#14b8a6'),
  member('u_tomasz', 'Tomasz Wójcik', 'member', ['platform'], 'Platform / SRE Engineer (red team rota)', '#64748b', ['claude-code@platform', 'chaos-agent@platform']),
];

// ------------------------------------------------------------------ agents
export function seedAgents(now: number): Agent[] {
  const ago = (s: number) => new Date(now - s * 1000).toISOString();
  return [
    {
      id: 'claude-code@platform', org_id: ORG_ID, team_id: 'platform', owner_member_id: 'u_tomasz', name: 'Claude Code (Platform)', kind: 'claude-code',
      description: 'Claude Code CLI via ANTHROPIC_BASE_URL, fail-closed PreToolUse hook and the Aegis MCP proxy.',
      profile: null, allowed_models: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-4-5', 'qwen3.5:0.8b'],
      allowed_tools: ['Read', 'Glob', 'Grep', 'Edit', 'Write', 'Bash', 'mcp__acme-db__query'], denied_tools: ['WebFetch', 'mcp__acme-crm__export_*'],
      max_destination: 'remote', active: true, created_at: CREATED, last_seen: ago(42), meta: { action_types: ['spend', 'data_access', 'external_send', 'code_exec', 'deploy'] },
      status: 'active', spend_today_usd: 3.42,
    },
    {
      id: 'research-agent@research', org_id: ORG_ID, team_id: 'research', owner_member_id: 'u_agnieszka', name: 'Research Agent (local)', kind: 'scripted',
      description: 'Local-first Python agent on Ollama (Qwen3.5 0.8B). Nothing it sees leaves the laptop unless approved.',
      profile: null, allowed_models: ['qwen3.5:0.8b'], allowed_tools: ['mcp__acme-db__query', 'mcp__filesystem__read_*', 'mcp__marketpulse__get_quote'], denied_tools: ['http.post:*', 'mcp__*__send_*'],
      max_destination: 'local', active: true, created_at: CREATED, last_seen: ago(180), meta: { action_types: ['spend', 'data_access'] },
      status: 'active', spend_today_usd: 0.18,
    },
    {
      id: 'trading-copilot@trading', org_id: ORG_ID, team_id: 'trading', owner_member_id: 'u_piotr', name: 'Trading Copilot (remote)', kind: 'sdk',
      description: 'Desk copilot on a remote model. Drafts client emails, looks up positions, subscribes to data feeds. Client PII is tokenized before it leaves.',
      profile: null, allowed_models: ['claude-haiku-4-5', 'claude-sonnet-5-5', 'meta-llama/llama-3.3-70b-instruct', 'qwen3.5:0.8b'],
      allowed_tools: ['mcp__acme-crm__lookup_*', 'mcp__acme-db__query', 'mcp__marketpulse__*', 'mcp__mailer__send_email'], denied_tools: ['mcp__acme-crm__delete_*', 'trade.execute'],
      max_destination: 'remote', active: true, created_at: CREATED, last_seen: ago(8), meta: { action_types: ['spend', 'data_access', 'external_send'] },
      status: 'active', spend_today_usd: 7.85,
    },
    {
      id: 'chaos-agent@platform', org_id: ORG_ID, team_id: 'platform', owner_member_id: 'u_tomasz', name: 'Chaos Agent (red team)', kind: 'other',
      description: 'Scripted adversarial agent: prompt injection, PII exfiltration, runaway loops, $5k purchases. Tiny budgets so it trips fast.',
      profile: null, allowed_models: ['qwen3.5:0.8b', 'claude-haiku-4-5'], allowed_tools: ['*'], denied_tools: [],
      max_destination: 'remote', active: true, created_at: CREATED, last_seen: ago(1500), meta: { demo: true },
      status: 'idle', spend_today_usd: 0.41,
    },
  ];
}

export function orgResponse(members: Member[], agents: Agent[]): OrgResponse {
  return {
    org: { id: ORG_ID, name: 'Acme Capital' },
    teams: TEAMS.map((t) => ({
      ...t,
      member_count: members.filter((m) => ((m.meta?.teams as string[] | undefined) ?? [m.team_id]).includes(t.id)).length,
      agent_count: agents.filter((a) => a.team_id === t.id).length,
    })),
    counts: { members: members.length, agents: agents.length, teams: TEAMS.length },
  };
}

// ------------------------------------------------------------------ approval rules (seed-fixes ids)
function rule(set: ApprovalRuleView['set'], id: string, when: string, approver: ApprovalRuleView['approver'], description: string | null = null, two_person = false, ttl_s: number | null = null): ApprovalRuleView {
  return { id, set, when, approver, description, two_person, ttl_s };
}

export const RULES: ApprovalRulesResponse = {
  rules: [
    rule('rules', 'org-owner-grants', 'action org.role.promote_owner | demote_owner | member.create_owner', 'owner', 'Granting or revoking the owner role always needs an owner', false, 3600),
    rule('rules', 'org-privileged', 'action org.role.* | org.member.create_admin | org.agent.widen_destination', 'owner', 'Promote/demote admins, widen an agent\'s destination', false, 3600),
    rule('rules', 'org-routine', 'action org.member.* | org.agent.*', 'admin', 'Routine member/agent administration'),
    rule('rules', 'spend-owner-2p', 'action spend.*, amount > $1,000', 'owner', 'Over $1,000: owner plus a second admin (two-person rule)', true, 7200),
    rule('rules', 'spend-owner', 'action spend.*, amount > $200', 'owner', 'Over $200 (e.g. the $480 GPU reservation)'),
    rule('rules', 'spend-admin', 'action spend.*, amount > $20', 'admin', '$20.01–$200 (e.g. the $50/month MarketPulse Pro subscription)'),
    rule('rules', 'spend-self', 'action spend.* (≤ $20)', 'self', 'Up to $20: the member (or the agent\'s sponsor) confirms'),
    rule('rules', 'db-restricted', 'action db.*, labels sensitivity ∈ {RESTRICTED, SECRET}', 'deny', 'PCI: no agent may read raw card data, whoever approves'),
    rule('rules', 'db-prod-ddl', 'action db.schema, labels env = prod', 'deny', 'Schema changes on prod go through migrations, never an agent'),
    rule('rules', 'db-prod-write', 'action db.write, labels env = prod', 'owner', 'Any agent write to a production database'),
    rule('rules', 'db-staging-write', 'action db.write, labels env = staging', 'self'),
    rule('rules', 'db-write', 'action db.write | db.schema', 'admin', 'Writes/DDL outside prod/staging labels (fail closed)'),
    rule('rules', 'db-pii-read', 'action db.read, labels sensitivity = CONFIDENTIAL', 'admin', 'E.g. SELECT * FROM customers (PII)', false, 3600),
    rule('rules', 'db-internal-read', 'action db.read, labels sensitivity = INTERNAL (strict, balanced)', 'self'),
    rule('rules', 'db-read', 'action db.read, labels sensitivity ∈ {PUBLIC, INTERNAL}', 'auto', 'Public data'),
    rule('rules', 'send-restricted', 'action email.external | egress.post, data_class ∈ {RESTRICTED, SECRET}', 'deny', 'Card data or secrets to a third party: never'),
    rule('rules', 'send-tainted', 'action email.* | egress.post, signals ∋ lethal_trifecta', 'admin', 'Session read private data AND saw untrusted content'),
    rule('rules', 'send-confidential', 'action email.external | egress.post, data_class = CONFIDENTIAL', 'admin', 'Client data (even tokenized) leaving the firm'),
    rule('rules', 'send-internal', 'action email.internal', 'auto'),
    rule('rules', 'external-send', 'action email.external | egress.post', 'self'),
    rule('rules', 'code-exec-remote-shell', 'action code.exec, labels pattern = remote_shell', 'admin'),
    rule('rules', 'pkg-install', 'action package.install', 'self'),
    rule('rules', 'deploy-prod', 'action code.deploy, labels env = prod', 'owner'),
    rule('rules', 'deploy-mainline', 'action code.deploy, labels env = mainline', 'admin', 'Push to main/release (stands in for code review)'),
    rule('rules', 'deploy', 'action code.deploy', 'admin'),
    rule('rules', 'budget-override', 'kind budget_raise', 'admin', 'Agent hit a hard budget with on_hard: require_approval'),
    rule('rules', 'mcp-repin', 'kind mcp_pin', 'admin', 'Changed/new third-party MCP tool (possible rug pull)'),
  ],
  config_rules: [
    rule('config_rules', 'approval-rules', 'change approval.rule', 'owner', 'Who-may-approve-what is owner territory'),
    rule('config_rules', 'protect-more', 'change control.enable | control.add | *.tighten | model.disallow', 'auto', 'Turning protection ON is always free'),
    rule('config_rules', 'disable-control-strict', 'change control.disable | remove | mode | action.loosen (strict, paranoid)', 'owner', 'Strict: owner + a second admin', true, 3600),
    rule('config_rules', 'disable-control-critical', 'change control.disable | remove | mode | action.loosen, control severity critical', 'owner', 'Critical controls (DLP-02, EXE-01, SIG-01, SIG-02)'),
    rule('config_rules', 'disable-control', 'change control.disable | remove | mode | action.loosen', 'admin'),
    rule('config_rules', 'raise-org-2x', 'change budget.raise, scope org, increase > 100%', 'owner', null, true),
    rule('config_rules', 'raise-org', 'change budget.raise, scope org', 'owner'),
    rule('config_rules', 'raise-large', 'change budget.raise, scope team, increase > 100%', 'owner', 'Team budget more than doubled (e.g. 60 → 150)'),
    rule('config_rules', 'raise-team-small', 'change budget.raise, scope team (≤ 2×)', 'admin', 'Team budget raised up to 2× (e.g. 60 → 75)'),
    rule('config_rules', 'raise-agent-large', 'change budget.raise, scope member | agent | session, increase > 50%', 'admin'),
    rule('config_rules', 'raise-small', 'change budget.raise, scope member | agent | session (≤ +50%)', 'self', 'Sponsor gives their own agent up to +50%'),
    rule('config_rules', 'budget-tighten', 'change budget.lower | budget.add', 'admin'),
    rule('config_rules', 'profile-down', 'change profile.change, loosening', 'owner'),
    rule('config_rules', 'killswitch-release-global', 'change killswitch.off, scope global', 'owner'),
    rule('config_rules', 'loosen-threshold', 'change control.threshold.loosen | killswitch.off', 'admin', 'Loosen a threshold or release a (non-global) kill switch'),
    rule('config_rules', 'killswitch-own-agent', 'change killswitch.on, requester is the sponsor', 'auto', 'Anyone may pull the brake on an agent they sponsor'),
    rule('config_rules', 'tighten', 'change killswitch.on', 'admin', 'Kill switch on anything else (incl. global)'),
    rule('config_rules', 'model-allow', 'change model.allow', 'admin'),
    rule('config_rules', 'policy-loosen', 'any loosening change', 'admin'),
    rule('config_rules', 'policy-neutral', 'change control.params | other', 'self', 'Descriptions, comments, new examples'),
  ],
  defaults: { ttl_s: 900, default_approver: 'admin', default_config_approver: 'owner' },
};

// ------------------------------------------------------------------ approvals (F4 / F5 scenarios)
function agentIdentity(agent_id: string, member_id: string, team_id: string, display_name: string): Identity {
  return { org_id: ORG_ID, team_id, member_id, agent_id, role: 'agent', display_name, authenticated: true };
}
function memberIdentity(member_id: string, role: Identity['role'], team_id: string, display_name: string): Identity {
  return { org_id: ORG_ID, team_id, member_id, agent_id: null, role, display_name, authenticated: true };
}

const TRADING_COPILOT = agentIdentity('trading-copilot@trading', 'u_piotr', 'trading', 'trading-copilot@trading');
const RESEARCH_AGENT = agentIdentity('research-agent@research', 'u_agnieszka', 'research', 'research-agent@research');
const CLAUDE_CODE = agentIdentity('claude-code@platform', 'u_tomasz', 'platform', 'claude-code@platform');
const CHAOS = agentIdentity('chaos-agent@platform', 'u_tomasz', 'platform', 'chaos-agent@platform');

function base(now: number, p: Partial<ApprovalRequest> & Pick<ApprovalRequest, 'id' | 'kind' | 'action_type' | 'title' | 'requester' | 'required_role'>, createdAgoS: number, ttlS: number): ApprovalRequest {
  return {
    org_id: ORG_ID,
    team_id: p.requester.team_id,
    summary: null,
    amount_usd: null,
    resource: null,
    labels: {},
    payload: {},
    fingerprint: `fp_${p.id.slice(4)}`,
    two_person: false,
    rule_id: null,
    votes: [],
    status: 'pending',
    created_at: new Date(now - createdAgoS * 1000).toISOString(),
    expires_at: new Date(now - createdAgoS * 1000 + ttlS * 1000).toISOString(),
    decided_at: null,
    decided_by: [],
    request_id: `req_${p.id.slice(4)}`,
    decision_id: `dec_${p.id.slice(4)}`,
    control_id: null,
    uses: 0,
    max_uses: 1,
    execution: null,
    ...p,
  };
}

/** Fresh approval set relative to `now` (store init). Pending first, then history. */
export function seedApprovals(now: number): ApprovalRequest[] {
  return [
    base(now, {
      id: 'apr_01JD8MKT50SPEND', kind: 'action', action_type: 'spend.subscription', control_id: 'ACT-01',
      title: 'trading-copilot@trading wants to spend $50.00 on MarketPulse Pro',
      summary: 'Monthly subscription mp-pro-monthly via marketpulse.purchase_subscription',
      requester: TRADING_COPILOT, amount_usd: 50, resource: 'vendor:marketpulse',
      labels: { vendor_approved: 'true', recurring: 'monthly', dest: 'third_party' },
      payload: {
        tool_name: 'marketpulse.purchase_subscription',
        tool_args: { vendor: 'marketpulse', plan: 'mp-pro-monthly', amount_usd: 50, currency: 'USD', billing_email: '[EMAIL_1]' },
        justification: 'Need real-time L2 quotes for the EUR/PLN desk this month. Approve quickly please, the market opens soon.',
      },
      required_role: 'admin', rule_id: 'spend-admin',
    }, 95, 900),
    base(now, {
      id: 'apr_01JD8MKT12DATA', kind: 'action', action_type: 'spend.charge', control_id: 'ACT-01',
      title: 'research-agent@research wants to spend $12.00 on an OpenData Shop dataset',
      summary: 'One-off purchase eu-equities-2025-csv',
      requester: RESEARCH_AGENT, amount_usd: 12, resource: 'vendor:opendata-shop',
      labels: { vendor_approved: 'true', recurring: 'none', dest: 'third_party' },
      payload: { tool_name: 'payments.charge', tool_args: { vendor: 'opendata-shop', sku: 'eu-equities-2025-csv', amount_usd: 12 }, justification: 'Coverage refresh for the Q3 note.' },
      required_role: 'self', rule_id: 'spend-self',
    }, 610, 900),
    base(now, {
      id: 'apr_01JD8MKT480GPU', kind: 'action', action_type: 'spend.charge', control_id: 'ACT-01',
      title: 'claude-code@platform wants to spend $480.00 on a 24 h A100 reservation',
      summary: 'BurstGPU Cloud a100-24h-reservation',
      requester: CLAUDE_CODE, amount_usd: 480, resource: 'vendor:gpucloud',
      labels: { vendor_approved: 'true', recurring: 'none', dest: 'third_party' },
      payload: { tool_name: 'gpucloud.reserve', tool_args: { vendor: 'gpucloud', plan: 'a100-24h-reservation', amount_usd: 480, region: 'eu-central' }, justification: 'Fine-tune the injection classifier on the new corpus.' },
      required_role: 'owner', rule_id: 'spend-owner',
    }, 300, 3600),
    base(now, {
      id: 'apr_01JD8MKT4800ENT', kind: 'action', action_type: 'spend.subscription', control_id: 'ACT-01',
      title: 'trading-copilot@trading wants to spend $4,800.00 on MarketPulse Enterprise',
      summary: 'Annual plan mp-enterprise-annual — over $1,000 ⇒ owner + a second admin',
      requester: TRADING_COPILOT, amount_usd: 4800, resource: 'vendor:marketpulse',
      labels: { vendor_approved: 'true', recurring: 'yearly', dest: 'third_party' },
      payload: { tool_name: 'marketpulse.purchase_subscription', tool_args: { vendor: 'marketpulse', plan: 'mp-enterprise-annual', amount_usd: 4800, currency: 'USD' }, justification: 'Desk-wide license for 2027 — cheaper than 8 monthly seats.' },
      required_role: 'owner', two_person: true, rule_id: 'spend-owner-2p',
      votes: [{ member_id: 'u_katarzyna', role: 'owner', decision: 'approve', comment: 'OK from risk — needs a trading admin to co-sign.', ts: new Date(now - 240_000).toISOString() }],
    }, 1200, 7200),
    base(now, {
      id: 'apr_01JD8MKTDBCUST', kind: 'action', action_type: 'db.read', control_id: 'ACT-02',
      title: 'research-agent@research wants to read db:customers (PII)',
      summary: 'acme-db.query on a CONFIDENTIAL production table',
      requester: RESEARCH_AGENT, resource: 'db:customers',
      labels: { sensitivity: 'CONFIDENTIAL', env: 'prod', categories: 'pii' },
      payload: { tool_name: 'acme-db.query', tool_args: { database: 'acme-prod-pg', sql: "SELECT name, email, segment FROM customers WHERE coverage = 'PL-banks' LIMIT 50" }, justification: 'Build the coverage list for the PL banks note.' },
      required_role: 'admin', rule_id: 'db-pii-read',
    }, 420, 3600),
    base(now, {
      id: 'apr_01JD8MKTRAISE75', kind: 'config_change', action_type: 'budget.raise', control_id: 'GOV-05',
      title: 'Raise team:trading daily USD budget $60 → $75 (+25%)',
      summary: 'Proposed by Piotr from the Budgets page',
      requester: memberIdentity('u_piotr', 'member', 'trading', 'Piotr Zieliński'),
      resource: 'budget:team:trading', labels: { scope: 'team:trading', scope_type: 'team' },
      payload: {
        changes: [{ kind: 'budget.raise', path: 'budgets.limits[scope=team:trading,window=day].usd', before: 60, after: 75, control_id: null, scope: 'team:trading', dimension: 'usd', increase_pct: 25, loosening: true, summary: 'team:trading daily usd 60 → 75 (+25%)' }],
        patch: [{ op: 'set', path: 'budgets.limits[scope=team:trading,window=day].usd', value: 75 }],
        base_version: 12,
        reason: 'Earnings week — copilot traffic roughly doubles until Friday.',
      },
      required_role: 'admin', rule_id: 'raise-team-small',
    }, 180, 900),
    base(now, {
      id: 'apr_01JD8MKTDLP02OF', kind: 'config_change', action_type: 'control.disable', control_id: 'GOV-05',
      title: 'Disable DLP-02 (secrets & credentials detector)',
      summary: 'Proposed by Marek in the policy editor — loosening, critical control',
      requester: memberIdentity('u_marek', 'admin', 'platform', 'Marek Kowalczyk'),
      resource: 'control:DLP-02', labels: { control_severity: 'critical', loosening: 'true' },
      payload: {
        changes: [{ kind: 'control.disable', path: 'controls[id=DLP-02].enabled', before: true, after: false, control_id: 'DLP-02', scope: null, dimension: null, increase_pct: null, loosening: true, summary: 'DLP-02 enabled: true → false' }],
        unified: '--- active v12\n+++ draft\n@@ -212,6 +212,6 @@\n   - id: DLP-02\n     name: Secrets & credentials (AWS, GitHub, Stripe, private keys)\n-    enabled: true\n+    enabled: false\n     action: block\n     severity: critical\n     fail_mode: closed',
        base_version: 12,
        reason: 'False positives on the test fixtures in the platform repo.',
      },
      required_role: 'owner', rule_id: 'disable-control-critical',
    }, 700, 3600),

    // ---------------- history
    base(now, {
      id: 'apr_01JD8MKTCARDSX', kind: 'action', action_type: 'db.read', control_id: 'ACT-02',
      title: 'chaos-agent@platform wants to read db:payment_cards',
      requester: CHAOS, resource: 'db:payment_cards', labels: { sensitivity: 'RESTRICTED', env: 'prod', categories: 'pci' },
      payload: { tool_name: 'acme-db.query', tool_args: { database: 'acme-prod-pg', sql: 'SELECT * FROM payment_cards' } },
      required_role: 'deny', rule_id: 'db-restricted', status: 'denied', decided_at: new Date(now - 1_500_000).toISOString(),
    }, 1500, 900),
    base(now, {
      id: 'apr_01JD8MKT8OPEND', kind: 'action', action_type: 'spend.charge', control_id: 'ACT-01',
      title: 'research-agent@research wants to spend $8.00 on an OpenData Shop sample',
      requester: RESEARCH_AGENT, amount_usd: 8, resource: 'vendor:opendata-shop',
      payload: { tool_name: 'payments.charge', tool_args: { vendor: 'opendata-shop', sku: 'eu-equities-sample', amount_usd: 8 } },
      required_role: 'self', rule_id: 'spend-self', status: 'approved', uses: 1,
      votes: [{ member_id: 'u_agnieszka', role: 'member', decision: 'approve', comment: 'Fine — sample set.', ts: new Date(now - 3_000_000).toISOString() }],
      decided_at: new Date(now - 3_000_000).toISOString(), decided_by: ['u_agnieszka'], execution: { granted: true, grant_expires_at: new Date(now - 2_400_000).toISOString() },
    }, 3100, 900),
    base(now, {
      id: 'apr_01JD8MKTRESTOK', kind: 'config_change', action_type: 'budget.raise', control_id: 'GOV-05',
      title: 'Raise team:research daily tokens 1.5M → 2M (+33%)',
      requester: memberIdentity('u_agnieszka', 'member', 'research', 'Agnieszka Lewandowska'), resource: 'budget:team:research',
      labels: { scope: 'team:research', scope_type: 'team' },
      payload: { changes: [{ kind: 'budget.raise', path: 'budgets.limits[scope=team:research,window=day].tokens', before: 1500000, after: 2000000, control_id: null, scope: 'team:research', dimension: 'tokens', increase_pct: 33.3, loosening: true, summary: 'team:research daily tokens 1.5M → 2M (+33%)' }], base_version: 11 },
      required_role: 'admin', rule_id: 'raise-team-small', status: 'approved',
      votes: [{ member_id: 'u_emily', role: 'admin', decision: 'approve', comment: 'Earnings season.', ts: new Date(now - 5_400_000).toISOString() }],
      decided_at: new Date(now - 5_400_000).toISOString(), decided_by: ['u_emily'], execution: { status: 'applied', policy_version: 12, previous_version: 11, latency_ms: 162 },
    }, 5600, 900),
    base(now, {
      id: 'apr_01JD8MKTMAILEX', kind: 'action', action_type: 'email.external', control_id: 'ACT-03',
      title: 'trading-copilot@trading wants to email a client portfolio summary',
      requester: TRADING_COPILOT, resource: 'host:client-portal.example', labels: { data_class: 'CONFIDENTIAL' },
      payload: { tool_name: 'mailer.send_email', tool_args: { to: '[EMAIL_2]', subject: 'Your Q3 portfolio summary', body: 'Dear [PERSON_1], …' } },
      required_role: 'admin', rule_id: 'send-confidential', status: 'denied',
      votes: [{ member_id: 'u_emily', role: 'admin', decision: 'deny', comment: 'Client comms go through the CRM template, not the copilot.', ts: new Date(now - 7_000_000).toISOString() }],
      decided_at: new Date(now - 7_000_000).toISOString(), decided_by: ['u_emily'],
    }, 7300, 900),
  ];
}
