/**
 * UI models used by every screen. Repositories (mock or live) produce these, so the
 * views never depend on the gateway's wire format.
 */

export class KeyValue {
  key: string;
  value: string;

  constructor(key: string, value: string) {
    this.key = key;
    this.value = value;
  }
}

export class CheckItem {
  name: string;
  ok: boolean;
  detail: string;

  constructor(name: string, ok: boolean, detail: string) {
    this.name = name;
    this.ok = ok;
    this.detail = detail;
  }
}

export class VoteView {
  memberId: string;
  role: string;
  decision: string; // 'approve' | 'deny'
  comment: string;
  tsMs: number;

  constructor(memberId: string, role: string, decision: string, comment: string, tsMs: number) {
    this.memberId = memberId;
    this.role = role;
    this.decision = decision;
    this.comment = comment;
    this.tsMs = tsMs;
  }
}

export class ApprovalItem {
  id: string = '';
  kind: string = 'action'; // action | config_change | budget_raise | mcp_pin
  actionType: string = '';
  title: string = '';
  summary: string = '';
  requesterAgent: string = '';
  requesterMember: string = '';
  teamId: string = '';
  amountUsd: number = -1; // -1 = no amount
  resource: string = '';
  requiredRole: string = 'admin'; // auto | self | admin | owner | deny
  twoPerson: boolean = false;
  ruleId: string = '';
  controlId: string = '';
  status: string = 'pending'; // pending | approved | denied | expired | cancelled
  createdAtMs: number = 0;
  expiresAtMs: number = 0;
  decidedAtMs: number = 0;
  votes: VoteView[] = [];
  canVote: boolean = false;
  whyNot: string = '';
  facts: KeyValue[] = [];
  checks: CheckItem[] = [];
  agentNote: string = '';
  budgetBefore: number = -1;
  budgetAfter: number = -1;
  budgetScope: string = '';
  /** Local-only flag while an optimistic vote is in flight. */
  syncing: boolean = false;

  clone(): ApprovalItem {
    const c: ApprovalItem = new ApprovalItem();
    c.id = this.id;
    c.kind = this.kind;
    c.actionType = this.actionType;
    c.title = this.title;
    c.summary = this.summary;
    c.requesterAgent = this.requesterAgent;
    c.requesterMember = this.requesterMember;
    c.teamId = this.teamId;
    c.amountUsd = this.amountUsd;
    c.resource = this.resource;
    c.requiredRole = this.requiredRole;
    c.twoPerson = this.twoPerson;
    c.ruleId = this.ruleId;
    c.controlId = this.controlId;
    c.status = this.status;
    c.createdAtMs = this.createdAtMs;
    c.expiresAtMs = this.expiresAtMs;
    c.decidedAtMs = this.decidedAtMs;
    c.votes = this.votes.slice();
    c.canVote = this.canVote;
    c.whyNot = this.whyNot;
    c.facts = this.facts.slice();
    c.checks = this.checks.slice();
    c.agentNote = this.agentNote;
    c.budgetBefore = this.budgetBefore;
    c.budgetAfter = this.budgetAfter;
    c.budgetScope = this.budgetScope;
    c.syncing = this.syncing;
    return c;
  }

  isPending(): boolean {
    return this.status === 'pending';
  }
}

export class PostureStats {
  requests: number = 0;
  blocked: number = 0;
  redacted: number = 0;
  approvalsPending: number = 0;
  spendTodayUsd: number = 0;
  budgetUsedPct: number = 0;
  activeAgents: number = 0;
  costAvoidedUsd: number = 0;
  p50OverheadMs: number = 0;
  degraded: boolean = false;
  updatedAtMs: number = 0;
  source: string = 'mock'; // mock | live

}

export class Persona {
  id: string;
  name: string;
  role: string; // member | admin | owner
  team: string;

  constructor(id: string, name: string, role: string, team: string) {
    this.id = id;
    this.name = name;
    this.role = role;
    this.team = team;
  }
}

/** The demo cast from aegis/docs/CONTRACTS.md §4.5 (ids are binding for the gateway). */
export const PERSONAS: Persona[] = [
  new Persona('u_piotr', 'Piotr', 'member', 'trading'),
  new Persona('u_emily', 'Emily', 'admin', 'trading'),
  new Persona('u_marek', 'Marek', 'admin', 'platform'),
  new Persona('u_katarzyna', 'Katarzyna', 'owner', 'all teams')
];

export function personaById(id: string): Persona {
  for (const p of PERSONAS) {
    if (p.id === id) {
      return p;
    }
  }
  return PERSONAS[1];
}

export const ROLE_RANK: Record<string, number> = {
  'agent': 0,
  'member': 1,
  'admin': 2,
  'owner': 3
};

export function roleRank(role: string): number {
  const r: number | undefined = ROLE_RANK[role];
  return r !== undefined ? r : 0;
}

/** Result of a vote attempt, used for toasts. */
export class VoteOutcome {
  ok: boolean;
  message: string;

  constructor(ok: boolean, message: string) {
    this.ok = ok;
    this.message = message;
  }
}

// Free helpers used by views (do not rely on class methods surviving AppStorage / @Prop copies).

export function renderKeyOf(it: ApprovalItem): string {
  return it.id + '|' + it.status + '|' + it.votes.length.toString() + '|' +
    (it.canVote ? '1' : '0') + '|' + (it.syncing ? 's' : '');
}

export function glyphOf(it: ApprovalItem): string {
  if (it.kind === 'budget_raise' || it.actionType.startsWith('budget')) {
    return 'B';
  }
  if (it.actionType.startsWith('spend')) {
    return '$';
  }
  if (it.actionType.startsWith('db')) {
    return 'DB';
  }
  if (it.actionType.startsWith('email')) {
    return '@';
  }
  if (it.actionType.startsWith('code') || it.actionType.startsWith('package')) {
    return '>_';
  }
  if (it.actionType.startsWith('egress')) {
    return '↗';
  }
  if (it.kind === 'config_change') {
    return 'P';
  }
  return '!';
}

const ACTION_LABELS: Record<string, string> = {
  'spend.subscription': 'Subscription purchase',
  'spend.charge': 'Card charge',
  'spend.transfer': 'Money transfer',
  'db.read': 'Database read',
  'db.write': 'Database write',
  'email.external': 'External email',
  'egress.post': 'Upload to third party',
  'code.exec': 'Code execution',
  'code.deploy': 'Deployment',
  'package.install': 'Package install',
  'budget.override': 'Budget raise',
  'budget.raise': 'Budget raise',
  'control.disable': 'Disable a control',
  'mcp.repin': 'MCP tool change'
};

export function actionLabelOf(it: ApprovalItem): string {
  const v: string | undefined = ACTION_LABELS[it.actionType];
  return v !== undefined ? v : it.actionType;
}

export function requesterOf(it: ApprovalItem): string {
  if (it.requesterAgent.length > 0) {
    return it.requesterAgent;
  }
  if (it.requesterMember.length > 0) {
    return personaName(it.requesterMember);
  }
  return 'unknown requester';
}

export function personaName(memberId: string): string {
  for (const p of PERSONAS) {
    if (p.id === memberId) {
      return p.name;
    }
  }
  return memberId.startsWith('u_') ? memberId.substring(2, 3).toUpperCase() + memberId.substring(3) : memberId;
}

export function budgetLeftPctOf(s: PostureStats): number {
  return Math.max(0, Math.min(100, 100 - s.budgetUsedPct));
}
