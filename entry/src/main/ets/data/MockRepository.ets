import { ApprovalItem, CheckItem, KeyValue, Persona, PostureStats, VoteView, personaById } from '../model/Models';
import { ApprovalsPage, ApprovalsRepository, ConnectionInfo, RepoError } from './ApprovalsRepository';
import { approvalComplete, checkEligibility, Eligibility } from './Eligibility';

const MIN = 60 * 1000;
const DAILY_ORG_BUDGET_USD = 400;
const MAX_SIMULATED_PENDING = 8;

class Template {
  agent: string;
  actionType: string;
  title: string;
  summary: string;
  amount: number;
  resource: string;
  role: string;
  rule: string;
  control: string;
  note: string;

  constructor(agent: string, actionType: string, title: string, summary: string, amount: number,
    resource: string, role: string, rule: string, control: string, note: string) {
    this.agent = agent;
    this.actionType = actionType;
    this.title = title;
    this.summary = summary;
    this.amount = amount;
    this.resource = resource;
    this.role = role;
    this.rule = rule;
    this.control = control;
    this.note = note;
  }
}

/** Requests the simulator emits every 20-30 s (rotating). All data is fictional. */
const TEMPLATES: Template[] = [
  new Template('research-agent@research', 'spend.charge', 'Buy dataset: EU retail footfall Q3',
    'One-off purchase from an approved data vendor', 18, 'vendor:footfall-data', 'self', 'spend-self',
    'ACT-01', 'Needed for the quarterly retail model refresh.'),
  new Template('claude-code@platform', 'code.deploy', 'terraform apply on prod (3 resources)',
    'Changes an autoscaling group and two security group rules', -1, 'env:prod', 'admin', 'exec-prod-admin',
    'ACT-04', 'Fixing the scaling bug from ticket PLAT-212.'),
  new Template('trading-copilot@trading', 'email.external', 'Email portfolio summary to 12 clients',
    'External email with account numbers redacted to placeholders', -1, 'host:mailer', 'admin', 'email-ext-admin',
    'ACT-03', 'Weekly client update, template approved by compliance.'),
  new Template('chaos-agent@platform', 'spend.subscription', 'Buy GPU credits (120 USD / month)',
    'Recurring purchase from a vendor that is not on the approved list', 120, 'vendor:gpu-cloud', 'admin',
    'spend-admin', 'ACT-01', 'Load test needs more GPUs.'),
  new Template('research-agent@research', 'db.read', 'Read clinical_trials table (health data)',
    'Bounded SELECT, 500 rows, includes HEALTH columns', -1, 'db:clinical_trials', 'admin', 'db-sensitive-admin',
    'ACT-02', 'Literature review cross-check.')
];

/**
 * MOCK MODE. Simulates the Aegis gateway on the device: seeded approval requests matching the
 * demo script, eligibility rules mirrored from the gateway, posture KPIs that drift over time,
 * and a new simulated agent request every 20-30 s. Everything here is fictional demo data.
 */
export class MockRepository implements ApprovalsRepository {
  readonly mode: string = 'mock';
  private items: ApprovalItem[] = [];
  private stats: PostureStats = new PostureStats();
  private nextSimAtMs: number = 0;
  private simCounter: number = 0;

  constructor() {
    const now: number = Date.now();
    this.seed(now);
    this.nextSimAtMs = now + 20 * 1000;
    this.stats.requests = 1284;
    this.stats.blocked = 37;
    this.stats.redacted = 212;
    this.stats.spendTodayUsd = 148.4;
    this.stats.activeAgents = 4;
    this.stats.costAvoidedUsd = 23.7;
    this.stats.p50OverheadMs = 6;
    this.stats.source = 'mock';
  }

  async listApprovals(viewAs: string): Promise<ApprovalsPage> {
    const viewer: Persona = personaById(viewAs);
    this.expire(Date.now());
    const page: ApprovalsPage = new ApprovalsPage();
    for (const it of this.items) {
      const view: ApprovalItem = this.viewFor(it, viewer);
      page.items.push(view);
      if (view.status === 'pending') {
        page.pending++;
      }
    }
    page.items.sort((a: ApprovalItem, b: ApprovalItem) => b.createdAtMs - a.createdAtMs);
    return page;
  }

  async getApproval(id: string, viewAs: string): Promise<ApprovalItem> {
    const it: ApprovalItem | undefined = this.find(id);
    if (it === undefined) {
      throw new RepoError('Approval ' + id + ' not found', 404);
    }
    return this.viewFor(it, personaById(viewAs));
  }

  async getStats(viewAs: string): Promise<PostureStats> {
    const s: PostureStats = new PostureStats();
    s.requests = this.stats.requests;
    s.blocked = this.stats.blocked;
    s.redacted = this.stats.redacted;
    s.spendTodayUsd = this.stats.spendTodayUsd;
    s.activeAgents = this.stats.activeAgents;
    s.costAvoidedUsd = this.stats.costAvoidedUsd;
    s.p50OverheadMs = this.stats.p50OverheadMs;
    s.budgetUsedPct = Math.min(100, this.stats.spendTodayUsd / DAILY_ORG_BUDGET_USD * 100);
    let pending: number = 0;
    for (const it of this.items) {
      if (it.status === 'pending') {
        pending++;
      }
    }
    s.approvalsPending = pending;
    s.updatedAtMs = Date.now();
    s.source = 'mock';
    return s;
  }

  async vote(id: string, decision: string, viewAs: string, comment: string): Promise<ApprovalItem> {
    const it: ApprovalItem | undefined = this.find(id);
    if (it === undefined) {
      throw new RepoError('Approval ' + id + ' not found', 404);
    }
    this.expire(Date.now());
    if (it.status !== 'pending') {
      throw new RepoError('Already ' + it.status, 409);
    }
    const viewer: Persona = personaById(viewAs);
    const el: Eligibility = checkEligibility(it, viewer);
    if (!el.canVote) {
      throw new RepoError(el.whyNot, 403);
    }
    const now: number = Date.now();
    it.votes.push(new VoteView(viewer.id, viewer.role, decision, comment, now));
    if (decision === 'deny') {
      it.status = 'denied';
      it.decidedAtMs = now;
    } else if (approvalComplete(it)) {
      it.status = 'approved';
      it.decidedAtMs = now;
      if (it.amountUsd > 0) {
        this.stats.spendTodayUsd += it.amountUsd;
      }
    }
    return this.viewFor(it, viewer);
  }

  async testConnection(viewAs: string): Promise<ConnectionInfo> {
    return new ConnectionInfo(true, 'Mock mode: simulated gateway on this device, no network used');
  }

  tick(nowMs: number): void {
    // Posture KPIs drift so the dashboard and widget look alive.
    this.stats.requests += 2 + Math.floor(Math.random() * 9);
    if (Math.random() < 0.35) {
      this.stats.redacted += 1 + Math.floor(Math.random() * 3);
    }
    if (Math.random() < 0.12) {
      this.stats.blocked += 1;
    }
    this.stats.costAvoidedUsd += Math.random() * 0.05;
    this.stats.p50OverheadMs = 5 + Math.floor(Math.random() * 4);

    if (nowMs >= this.nextSimAtMs) {
      this.nextSimAtMs = nowMs + (20 + Math.floor(Math.random() * 11)) * 1000;
      this.simulateRequest(nowMs);
    }
  }

  // ------------------------------------------------------------------ internals

  private find(id: string): ApprovalItem | undefined {
    for (const it of this.items) {
      if (it.id === id) {
        return it;
      }
    }
    return undefined;
  }

  private viewFor(it: ApprovalItem, viewer: Persona): ApprovalItem {
    const v: ApprovalItem = it.clone();
    const el: Eligibility = checkEligibility(it, viewer);
    v.canVote = el.canVote;
    v.whyNot = el.whyNot;
    return v;
  }

  private expire(nowMs: number): void {
    for (const it of this.items) {
      if (it.status === 'pending' && it.expiresAtMs > 0 && it.expiresAtMs <= nowMs) {
        it.status = 'expired';
        it.decidedAtMs = it.expiresAtMs;
      }
    }
  }

  private simulateRequest(nowMs: number): void {
    let pending: number = 0;
    for (const it of this.items) {
      if (it.status === 'pending') {
        pending++;
      }
    }
    if (pending >= MAX_SIMULATED_PENDING) {
      return;
    }
    const t: Template = TEMPLATES[this.simCounter % TEMPLATES.length];
    this.simCounter++;
    const it: ApprovalItem = new ApprovalItem();
    it.id = 'apr_sim' + this.simCounter.toString() + '_' + (nowMs % 100000).toString();
    it.kind = 'action';
    it.actionType = t.actionType;
    it.title = t.title;
    it.summary = t.summary;
    it.requesterAgent = t.agent;
    it.teamId = t.agent.split('@')[1];
    it.amountUsd = t.amount;
    it.resource = t.resource;
    it.requiredRole = t.role;
    it.ruleId = t.rule;
    it.controlId = t.control;
    it.createdAtMs = nowMs;
    it.expiresAtMs = nowMs + (10 + Math.floor(Math.random() * 6)) * MIN;
    it.agentNote = t.note;
    it.facts = [new KeyValue('agent', t.agent), new KeyValue('resource', t.resource),
      new KeyValue('rule', t.rule)];
    if (t.amount > 0) {
      it.facts.push(new KeyValue('amount', '$' + t.amount.toFixed(2)));
    }
    it.checks = [new CheckItem('Agent key valid and active', true, 'GOV-01'),
      new CheckItem('Within the agent\'s tool allow-list', true, 'GOV-02')];
    this.items.push(it);
  }

  private seed(now: number): void {
    const a: ApprovalItem = new ApprovalItem();
    a.id = 'apr_demo_mp50';
    a.actionType = 'spend.subscription';
    a.title = 'Buy MarketPulse Pro (mp-pro-monthly)';
    a.summary = 'Recurring $50 / month market-data subscription for the trading desk';
    a.requesterAgent = 'trading-copilot@trading';
    a.teamId = 'trading';
    a.amountUsd = 50;
    a.resource = 'vendor:marketpulse';
    a.requiredRole = 'admin';
    a.ruleId = 'spend-admin';
    a.controlId = 'ACT-01';
    a.createdAtMs = now - 3 * MIN;
    a.expiresAtMs = now + 14 * MIN;
    a.agentNote = 'Need real-time quotes for the EU equities desk.';
    a.facts = [new KeyValue('vendor', 'MarketPulse Pro'), new KeyValue('plan', 'mp-pro-monthly'),
      new KeyValue('price', '$50.00 / month'), new KeyValue('recurring', 'monthly'),
      new KeyValue('vendor_approved', 'true'), new KeyValue('team budget left', '$41.60 today')];
    a.checks = [new CheckItem('Vendor is on the approved list', true, 'org catalog'),
      new CheckItem('Price matches the catalog', true, '$50.00'),
      new CheckItem('Amount in $20-$200 band: admin approval', true, 'rule spend-admin')];
    this.items.push(a);

    const b: ApprovalItem = new ApprovalItem();
    b.id = 'apr_demo_mp480';
    b.actionType = 'spend.subscription';
    b.title = 'Buy MarketPulse Enterprise seats ($480)';
    b.summary = 'Annual seat bundle; above the $200 owner threshold';
    b.requesterAgent = 'trading-copilot@trading';
    b.teamId = 'trading';
    b.amountUsd = 480;
    b.resource = 'vendor:marketpulse';
    b.requiredRole = 'owner';
    b.twoPerson = true;
    b.ruleId = 'spend-owner-2p';
    b.controlId = 'ACT-01';
    b.createdAtMs = now - 1 * MIN;
    b.expiresAtMs = now + 25 * MIN;
    b.agentNote = 'Whole desk wants access, cheaper than 10 monthly plans.';
    b.facts = [new KeyValue('vendor', 'MarketPulse Pro'), new KeyValue('plan', 'enterprise-annual'),
      new KeyValue('price', '$480.00 / year'), new KeyValue('recurring', 'yearly'),
      new KeyValue('vendor_approved', 'true')];
    b.checks = [new CheckItem('Vendor is on the approved list', true, 'org catalog'),
      new CheckItem('Amount above $200: owner + admin (two-person)', false, 'rule spend-owner-2p'),
      new CheckItem('Exceeds today\'s team budget', false, '$41.60 left')];
    this.items.push(b);

    const c: ApprovalItem = new ApprovalItem();
    c.id = 'apr_demo_budget';
    c.kind = 'budget_raise';
    c.actionType = 'budget.override';
    c.title = 'Raise team:trading daily budget $60 to $150';
    c.summary = 'Proposed by Piotr after trading-copilot hit the hard limit';
    c.requesterMember = 'u_piotr';
    c.requesterAgent = '';
    c.teamId = 'trading';
    c.resource = 'budget:team:trading';
    c.requiredRole = 'owner';
    c.ruleId = 'budget-raise-large';
    c.controlId = 'BUD-01';
    c.createdAtMs = now - 7 * MIN;
    c.expiresAtMs = now + 38 * MIN;
    c.budgetScope = 'team:trading';
    c.budgetBefore = 60;
    c.budgetAfter = 150;
    c.facts = [new KeyValue('scope', 'team:trading'), new KeyValue('window', 'day'),
      new KeyValue('dimension', 'usd'), new KeyValue('before', '$60'), new KeyValue('after', '$150'),
      new KeyValue('increase', '+150%')];
    c.checks = [new CheckItem('Increase above 100%: owner approval', false, 'rule budget-raise-large'),
      new CheckItem('Proposer is a member (cannot self-approve)', true, 'separation of duties')];
    this.items.push(c);

    const d: ApprovalItem = new ApprovalItem();
    d.id = 'apr_demo_pii';
    d.actionType = 'db.read';
    d.title = 'Read customers table (contains PII)';
    d.summary = 'SELECT name, email, phone, pesel FROM customers LIMIT 200';
    d.requesterAgent = 'trading-copilot@trading';
    d.teamId = 'trading';
    d.resource = 'db:customers';
    d.requiredRole = 'admin';
    d.ruleId = 'db-sensitive-admin';
    d.controlId = 'ACT-02';
    d.createdAtMs = now - 12 * MIN;
    d.expiresAtMs = now + 6 * MIN;
    d.agentNote = 'Preparing the client outreach list.';
    d.facts = [new KeyValue('table', 'customers'), new KeyValue('sensitivity', 'CONFIDENTIAL'),
      new KeyValue('env', 'prod'), new KeyValue('columns', 'name, email, phone, pesel'),
      new KeyValue('row limit', '200')];
    d.checks = [new CheckItem('Query is bounded (LIMIT 200)', true, 'ACT-02'),
      new CheckItem('Result contains PII columns', false, 'EMAIL, PHONE, PESEL'),
      new CheckItem('PII is redacted before it reaches the remote model', true, 'DLP-01')];
    this.items.push(d);

    const e: ApprovalItem = new ApprovalItem();
    e.id = 'apr_demo_pkg';
    e.actionType = 'package.install';
    e.title = 'pip install pandas==2.2.3';
    e.summary = 'Known package, pinned version';
    e.requesterAgent = 'claude-code@platform';
    e.teamId = 'platform';
    e.requiredRole = 'self';
    e.ruleId = 'pkg-known-self';
    e.controlId = 'SIG-03';
    e.status = 'approved';
    e.createdAtMs = now - 95 * MIN;
    e.decidedAtMs = now - 94 * MIN;
    e.votes = [new VoteView('u_tomasz', 'member', 'approve', 'fine', now - 94 * MIN)];
    this.items.push(e);

    const f: ApprovalItem = new ApprovalItem();
    f.id = 'apr_demo_exfil';
    f.actionType = 'egress.post';
    f.title = 'Upload customer list to paste.example';
    f.summary = 'POST of 2,140 rows to an unknown third-party host';
    f.requesterAgent = 'chaos-agent@platform';
    f.teamId = 'platform';
    f.requiredRole = 'admin';
    f.ruleId = 'egress-unknown-admin';
    f.controlId = 'EXE-03';
    f.status = 'denied';
    f.createdAtMs = now - 150 * MIN;
    f.decidedAtMs = now - 148 * MIN;
    f.votes = [new VoteView('u_marek', 'admin', 'deny', 'exfiltration attempt', now - 148 * MIN)];
    this.items.push(f);
  }
}
