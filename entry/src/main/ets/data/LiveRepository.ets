import { http } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { ApprovalItem, CheckItem, KeyValue, PostureStats, VoteView } from '../model/Models';
import {
  VoteBody,
  WireApprovalRequest,
  WireApprovalsResponse,
  WireErrorEnvelope,
  WireStatsResponse,
  WireWhoAmI
} from '../model/Wire';
import { Fmt, Log } from '../common/Format';
import { ApprovalsPage, ApprovalsRepository, ConnectionInfo, RepoError } from './ApprovalsRepository';

const TIMEOUT_MS = 6000;

/**
 * LIVE MODE. Talks to the Aegis gateway dashboard API (aegis/docs/CONTRACTS.md §5.4, Addendum A.28)
 * with Network Kit HTTP. The viewer persona is sent as `X-Aegis-View-As`; the gateway decides
 * eligibility (`can_vote` / `why_not`) and returns 403/409 for refused votes.
 */
export class LiveRepository implements ApprovalsRepository {
  readonly mode: string = 'live';
  private baseUrl: string;

  constructor(baseUrl: string) {
    let u: string = baseUrl.trim();
    while (u.endsWith('/')) {
      u = u.substring(0, u.length - 1);
    }
    this.baseUrl = u;
  }

  async listApprovals(viewAs: string): Promise<ApprovalsPage> {
    const body: string = await this.request(http.RequestMethod.GET, '/api/approvals?status=all&limit=100', viewAs, '');
    const res: WireApprovalsResponse = JSON.parse(body) as WireApprovalsResponse;
    const page: ApprovalsPage = new ApprovalsPage();
    const items: WireApprovalRequest[] = res.items ?? [];
    for (const w of items) {
      const it: ApprovalItem = LiveRepository.map(w);
      page.items.push(it);
      if (it.status === 'pending') {
        page.pending++;
      }
    }
    page.items.sort((a: ApprovalItem, b: ApprovalItem) => b.createdAtMs - a.createdAtMs);
    return page;
  }

  async getApproval(id: string, viewAs: string): Promise<ApprovalItem> {
    const body: string = await this.request(http.RequestMethod.GET, '/api/approvals/' + encodeURIComponent(id),
      viewAs, '');
    return LiveRepository.map(JSON.parse(body) as WireApprovalRequest);
  }

  async getStats(viewAs: string): Promise<PostureStats> {
    const body: string = await this.request(http.RequestMethod.GET, '/api/stats?window=24h', viewAs, '');
    const res: WireStatsResponse = JSON.parse(body) as WireStatsResponse;
    const s: PostureStats = new PostureStats();
    if (res.kpis !== undefined && res.kpis !== null) {
      s.requests = res.kpis.requests ?? 0;
      s.blocked = res.kpis.blocked ?? 0;
      s.redacted = res.kpis.redacted ?? 0;
      s.approvalsPending = res.kpis.approvals_pending ?? 0;
      s.spendTodayUsd = res.kpis.spend_today_usd ?? 0;
      s.budgetUsedPct = res.kpis.org_budget_used_pct ?? 0;
      s.activeAgents = res.kpis.active_agents ?? 0;
      s.costAvoidedUsd = res.kpis.cost_avoided_usd ?? 0;
      s.p50OverheadMs = res.kpis.p50_overhead_ms ?? 0;
      s.degraded = res.kpis.degraded ?? false;
    }
    s.updatedAtMs = Date.now();
    s.source = 'live';
    return s;
  }

  async vote(id: string, decision: string, viewAs: string, comment: string): Promise<ApprovalItem> {
    const vb: VoteBody = new VoteBody();
    vb.comment = comment.length > 0 ? comment : null;
    const path: string = '/api/approvals/' + encodeURIComponent(id) + '/' + (decision === 'deny' ? 'deny' : 'approve');
    const body: string = await this.request(http.RequestMethod.POST, path, viewAs, JSON.stringify(vb));
    return LiveRepository.map(JSON.parse(body) as WireApprovalRequest);
  }

  async testConnection(viewAs: string): Promise<ConnectionInfo> {
    try {
      const body: string = await this.request(http.RequestMethod.GET, '/api/whoami', viewAs, '');
      const who: WireWhoAmI = JSON.parse(body) as WireWhoAmI;
      let name: string = viewAs;
      let role: string = '?';
      if (who.member !== null && who.member !== undefined) {
        name = who.member.name;
        role = who.member.role;
      } else if (who.identity !== undefined && who.identity !== null) {
        role = who.identity.role;
      }
      return new ConnectionInfo(true, 'Connected to ' + this.baseUrl + ' as ' + name + ' (' + role + ')');
    } catch (e) {
      const err: RepoError = e as RepoError;
      return new ConnectionInfo(false, err.message);
    }
  }

  tick(nowMs: number): void {
    // Live data comes from polling; nothing to simulate.
  }

  // ------------------------------------------------------------------ HTTP

  private async request(method: http.RequestMethod, path: string, viewAs: string, json: string): Promise<string> {
    const url: string = this.baseUrl + path;
    const req: http.HttpRequest = http.createHttp();
    const headers: Record<string, string> = {
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      'X-Aegis-View-As': viewAs
    };
    const opts: http.HttpRequestOptions = {
      method: method,
      header: headers,
      connectTimeout: TIMEOUT_MS,
      readTimeout: TIMEOUT_MS,
      expectDataType: http.HttpDataType.STRING
    };
    if (json.length > 0) {
      opts.extraData = json;
    }
    try {
      const resp: http.HttpResponse = await req.request(url, opts);
      const text: string = typeof resp.result === 'string' ? (resp.result as string) : '';
      if (resp.responseCode >= 200 && resp.responseCode < 300) {
        return text;
      }
      throw new RepoError(LiveRepository.errorMessage(text, resp.responseCode), resp.responseCode);
    } catch (e) {
      if (e instanceof RepoError) {
        throw e as RepoError;
      }
      const be: BusinessError = e as BusinessError;
      Log.warn('HTTP ' + path + ' failed: ' + JSON.stringify(be));
      throw new RepoError('Cannot reach the gateway at ' + this.baseUrl + ' (' + (be.message ?? 'network error') + ')', 0);
    } finally {
      req.destroy();
    }
  }

  private static errorMessage(text: string, code: number): string {
    try {
      const env: WireErrorEnvelope = JSON.parse(text) as WireErrorEnvelope;
      if (env.error !== undefined && env.error !== null && env.error.message !== undefined) {
        return env.error.message;
      }
    } catch (e) {
      // not an Aegis envelope
    }
    if (code === 403) {
      return 'Not allowed for this persona';
    }
    if (code === 409) {
      return 'Already decided';
    }
    if (code === 404) {
      return 'Not found (is this the Aegis gateway?)';
    }
    return 'Gateway answered HTTP ' + code.toString();
  }

  // ------------------------------------------------------------------ mapping

  static map(w: WireApprovalRequest): ApprovalItem {
    const it: ApprovalItem = new ApprovalItem();
    it.id = w.id;
    it.kind = w.kind ?? 'action';
    it.actionType = w.action_type ?? '';
    it.title = w.title ?? w.action_type ?? w.id;
    it.summary = w.summary ?? '';
    if (w.requester !== undefined && w.requester !== null) {
      it.requesterAgent = w.requester.agent_id ?? '';
      it.requesterMember = w.requester.member_id ?? '';
    }
    it.teamId = w.team_id ?? '';
    it.amountUsd = (w.amount_usd === null || w.amount_usd === undefined) ? -1 : w.amount_usd;
    it.resource = w.resource ?? '';
    it.requiredRole = w.required_role ?? 'admin';
    it.twoPerson = w.two_person ?? false;
    it.ruleId = w.rule_id ?? '';
    it.controlId = w.control_id ?? '';
    it.status = w.status ?? 'pending';
    it.createdAtMs = Fmt.parseIso(w.created_at);
    it.expiresAtMs = Fmt.parseIso(w.expires_at);
    it.decidedAtMs = Fmt.parseIso(w.decided_at);
    it.canVote = w.can_vote ?? false;
    it.whyNot = w.why_not ?? '';
    const votes: VoteView[] = [];
    for (const v of (w.votes ?? [])) {
      votes.push(new VoteView(v.member_id, v.role, v.decision, v.comment ?? '', Fmt.parseIso(v.ts)));
    }
    it.votes = votes;
    LiveRepository.mapPayload(w, it);
    return it;
  }

  private static mapPayload(w: WireApprovalRequest, it: ApprovalItem): void {
    const payload: Record<string, Object> | undefined = w.payload;
    if (payload === undefined || payload === null) {
      return;
    }
    const facts: Record<string, Object> | undefined = payload['facts'] as Record<string, Object> | undefined;
    if (facts !== undefined && facts !== null) {
      for (const k of Object.keys(facts)) {
        it.facts.push(new KeyValue(k, LiveRepository.str(facts[k])));
      }
    }
    const checks: Object[] | undefined = payload['checks'] as Object[] | undefined;
    if (checks !== undefined && checks !== null && Array.isArray(checks)) {
      for (const c of checks) {
        const rec: Record<string, Object> = c as Record<string, Object>;
        const okVal: Object | undefined = rec['ok'];
        it.checks.push(new CheckItem(LiveRepository.str(rec['name']), okVal === true,
          LiveRepository.str(rec['detail'])));
      }
    }
    const note: Object | undefined = payload['agent_note'];
    if (note !== undefined && note !== null) {
      it.agentNote = LiveRepository.str(note);
    }
    // Budget raise shapes (A-24): payload.before/after or payload.budget.{before,after}.
    let budget: Record<string, Object> | undefined = payload['budget'] as Record<string, Object> | undefined;
    if (budget === undefined || budget === null) {
      budget = payload;
    }
    const before: Object | undefined = budget['before'];
    const after: Object | undefined = budget['after'];
    if (typeof before === 'number' && typeof after === 'number') {
      it.budgetBefore = before as number;
      it.budgetAfter = after as number;
      it.budgetScope = LiveRepository.str(budget['scope']);
    }
    if (it.facts.length === 0 && w.labels !== undefined && w.labels !== null) {
      for (const k of Object.keys(w.labels)) {
        it.facts.push(new KeyValue(k, w.labels[k]));
      }
    }
  }

  private static str(v: Object | undefined | null): string {
    if (v === undefined || v === null) {
      return '';
    }
    if (typeof v === 'string') {
      return v as string;
    }
    if (typeof v === 'number' || typeof v === 'boolean') {
      return String(v);
    }
    return JSON.stringify(v);
  }
}
