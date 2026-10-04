import { ApprovalItem, CheckItem, KeyValue, PostureStats, VoteView } from '../model/Models';
import {
  WireApprovalRequest,
  WireApprovalsResponse,
  WireApprovalVote,
  WireErrorEnvelope,
  WireStatsKpis,
  WireStatsResponse
} from '../model/Wire';
import { ApprovalsPage, RepoError } from './ApprovalsRepository';

// Network Kit HTTP error codes (API reference: Network Kit > 错误码 > HTTP错误码, errorcode-net-http).
export const NET_URL_MALFORMED: number = 2300003; // URL格式错误
export const NET_DNS: number = 2300006; // 域名解析失败
export const NET_CONNECT: number = 2300007; // 无法连接到服务器
export const NET_TIMEOUT: number = 2300028; // 操作超时
export const NET_EMPTY_REPLY: number = 2300052; // 服务器没有返回内容
export const NET_SEND: number = 2300055; // 发送网络数据失败
export const NET_RECV: number = 2300056; // 接收网络数据失败
export const NET_CLEARTEXT_BLOCKED: number = 2300997; // 明文HTTP被拦截
export const PERMISSION_DENIED: number = 201;

/**
 * Pure (kit-free, host-testable) parsing and mapping of Aegis gateway responses for LiveRepository.
 * Gateway JSON is untrusted: every field is type-checked so a schema drift (null vote member, "50" as amount,
 * a null check entry) cannot crash a build() or fail the whole list. Errors are RepoError with a `kind`.
 */
export class LiveMapping {
  /** Message for a non-2xx answer: the Aegis error envelope if present, else a per-status default. */
  static errorMessage(text: string, code: number): string {
    try {
      const env: WireErrorEnvelope = JSON.parse(text) as WireErrorEnvelope;
      if (LiveMapping.isObj(env) && LiveMapping.isObj(env.error) && typeof env.error.message === 'string' &&
        env.error.message.length > 0) {
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

  /** User-facing message for a Network Kit request failure (no raw platform text). */
  static friendly(code: number, baseUrl: string): string {
    const where: string = baseUrl.length > 0 ? baseUrl : 'the gateway';
    if (code === NET_DNS) {
      return 'Cannot resolve host for ' + where + '. Check the gateway URL in Settings.';
    }
    if (code === NET_CONNECT) {
      return 'Cannot connect to ' + where + ': is the gateway running and is 10.0.2.2 (emulator) or the LAN IP right?';
    }
    if (code === NET_TIMEOUT) {
      return 'Gateway timed out (' + where + ').';
    }
    if (code === NET_URL_MALFORMED) {
      return 'Gateway URL is invalid (' + where + '). Use http://host:port.';
    }
    if (code === NET_EMPTY_REPLY || code === NET_SEND || code === NET_RECV) {
      return 'Connection to ' + where + ' was interrupted.';
    }
    if (code === NET_CLEARTEXT_BLOCKED) {
      return 'Plain HTTP to ' + where + ' was blocked by the system.';
    }
    if (code === PERMISSION_DENIED) {
      return 'Network permission denied.';
    }
    return 'Cannot reach the gateway at ' + where + '.';
  }

  /** JSON.parse that throws RepoError kind 'parse' (never a raw SyntaxError) and requires a JSON object. */
  static parse(body: string, what: string): Object {
    let v: Object | null = null;
    try {
      v = JSON.parse(body) as Object | null;
    } catch (e) {
      v = null;
    }
    if (!LiveMapping.isObj(v)) {
      throw new RepoError('Gateway returned non-JSON ' + what + ' (is this the Aegis gateway?)', 0, 'parse');
    }
    return v as Object;
  }

  /** Parses an `/api/approvals` body. Malformed entries are skipped and logged; the rest are returned. */
  static parseApprovals(body: string): ApprovalsPage {
    const res: WireApprovalsResponse = LiveMapping.parse(body, 'approvals') as WireApprovalsResponse;
    const page: ApprovalsPage = new ApprovalsPage();
    const raw: Object | null | undefined = res.items as Object | null | undefined;
    if (raw === undefined || raw === null || !Array.isArray(raw)) {
      throw new RepoError('Gateway returned an unexpected approvals list', 0, 'parse');
    }
    const items: Object[] = raw as Object[];
    let skipped: number = 0;
    for (const w of items) {
      try {
        const it: ApprovalItem = LiveMapping.mapChecked(w);
        page.items.push(it);
        if (it.status === 'pending') {
          page.pending++;
        }
      } catch (e) {
        skipped++;
      }
    }
    page.skipped = skipped;
    page.items.sort((a: ApprovalItem, b: ApprovalItem) => b.createdAtMs - a.createdAtMs);
    return page;
  }

  /** Parses an `/api/stats` body; non-numeric KPIs fall back to 0. */
  static parseStats(body: string): PostureStats {
    const res: WireStatsResponse = LiveMapping.parse(body, 'stats') as WireStatsResponse;
    const s: PostureStats = new PostureStats();
    if (LiveMapping.isObj(res.kpis)) {
      const k: WireStatsKpis = res.kpis;
      s.requests = LiveMapping.num(k.requests, 0);
      s.blocked = LiveMapping.num(k.blocked, 0);
      s.redacted = LiveMapping.num(k.redacted, 0);
      s.approvalsPending = LiveMapping.num(k.approvals_pending, 0);
      s.spendTodayUsd = LiveMapping.num(k.spend_today_usd, 0);
      s.budgetUsedPct = LiveMapping.num(k.org_budget_used_pct, 0);
      s.activeAgents = LiveMapping.num(k.active_agents, 0);
      s.costAvoidedUsd = LiveMapping.num(k.cost_avoided_usd, 0);
      s.p50OverheadMs = LiveMapping.num(k.p50_overhead_ms, 0);
      s.degraded = k.degraded === true;
    }
    s.updatedAtMs = Date.now();
    s.source = 'live';
    return s;
  }

  // ------------------------------------------------------------------ mapping

  /** map() for untrusted JSON: rejects non-objects and entries without a string id (RepoError kind 'parse'). */
  static mapChecked(v: Object | null | undefined): ApprovalItem {
    if (!LiveMapping.isObj(v)) {
      throw new RepoError('Malformed approval entry', 0, 'parse');
    }
    const w: WireApprovalRequest = v as WireApprovalRequest;
    const id: Object | null | undefined = w.id as Object | null | undefined;
    if (typeof id !== 'string' || (id as string).length === 0) {
      throw new RepoError('Approval entry without an id', 0, 'parse');
    }
    try {
      return LiveMapping.map(w);
    } catch (e) {
      throw new RepoError('Malformed approval ' + (id as string), 0, 'parse');
    }
  }

  /**
   * Maps a gateway approval to the UI model. Every field is type-checked because the body is untrusted JSON:
   * a string amount ("50") is coerced, null vote fields become '', and non-object entries are skipped.
   */
  static map(w: WireApprovalRequest): ApprovalItem {
    const it: ApprovalItem = new ApprovalItem();
    it.id = LiveMapping.text(w.id, '');
    it.kind = LiveMapping.text(w.kind, 'action');
    it.actionType = LiveMapping.text(w.action_type, '');
    it.title = LiveMapping.text(w.title, it.actionType.length > 0 ? it.actionType : it.id);
    it.summary = LiveMapping.text(w.summary, '');
    if (LiveMapping.isObj(w.requester)) {
      it.requesterAgent = LiveMapping.text(w.requester.agent_id, '');
      it.requesterMember = LiveMapping.text(w.requester.member_id, '');
    }
    it.teamId = LiveMapping.text(w.team_id, '');
    it.amountUsd = LiveMapping.num(w.amount_usd, -1);
    it.resource = LiveMapping.text(w.resource, '');
    it.requiredRole = LiveMapping.text(w.required_role, 'admin');
    it.twoPerson = w.two_person === true;
    it.ruleId = LiveMapping.text(w.rule_id, '');
    it.controlId = LiveMapping.text(w.control_id, '');
    it.status = LiveMapping.text(w.status, 'pending');
    it.createdAtMs = LiveMapping.parseIso(LiveMapping.text(w.created_at, ''));
    it.expiresAtMs = LiveMapping.parseIso(LiveMapping.text(w.expires_at, ''));
    it.decidedAtMs = LiveMapping.parseIso(LiveMapping.text(w.decided_at, ''));
    it.canVote = w.can_vote === true;
    it.whyNot = LiveMapping.text(w.why_not, '');
    const votes: VoteView[] = [];
    const rawVotes: Object | null | undefined = w.votes as Object | null | undefined;
    if (rawVotes !== undefined && rawVotes !== null && Array.isArray(rawVotes)) {
      for (const o of (rawVotes as Object[])) {
        if (!LiveMapping.isObj(o)) {
          continue;
        }
        const v: WireApprovalVote = o as WireApprovalVote;
        votes.push(new VoteView(LiveMapping.text(v.member_id, ''), LiveMapping.text(v.role, ''),
          LiveMapping.text(v.decision, ''), LiveMapping.text(v.comment, ''),
          LiveMapping.parseIso(LiveMapping.text(v.ts, ''))));
      }
    }
    it.votes = votes;
    LiveMapping.mapPayload(w, it);
    return it;
  }

  private static mapPayload(w: WireApprovalRequest, it: ApprovalItem): void {
    const payloadObj: Object | null | undefined = w.payload as Object | null | undefined;
    if (!LiveMapping.isObj(payloadObj) || Array.isArray(payloadObj)) {
      LiveMapping.mapLabels(w, it);
      return;
    }
    const payload: Record<string, Object> = payloadObj as Record<string, Object>;
    const factsObj: Object | null | undefined = payload['facts'];
    if (LiveMapping.isObj(factsObj) && !Array.isArray(factsObj)) {
      const facts: Record<string, Object> = factsObj as Record<string, Object>;
      for (const k of Object.keys(facts)) {
        it.facts.push(new KeyValue(k, LiveMapping.str(facts[k])));
      }
    }
    const checksObj: Object | null | undefined = payload['checks'];
    if (checksObj !== undefined && checksObj !== null && Array.isArray(checksObj)) {
      for (const c of (checksObj as Object[])) {
        if (!LiveMapping.isObj(c)) {
          continue; // P2-3: one bad entry must not fail the whole list
        }
        const rec: Record<string, Object> = c as Record<string, Object>;
        const okVal: Object | undefined = rec['ok'];
        it.checks.push(new CheckItem(LiveMapping.str(rec['name']), okVal === true,
          LiveMapping.str(rec['detail'])));
      }
    }
    const note: Object | undefined = payload['agent_note'];
    if (note !== undefined && note !== null) {
      it.agentNote = LiveMapping.str(note);
    }
    // Budget raise shapes (A-24): payload.before/after or payload.budget.{before,after}.
    let budget: Record<string, Object> = payload;
    const budgetObj: Object | null | undefined = payload['budget'];
    if (LiveMapping.isObj(budgetObj) && !Array.isArray(budgetObj)) {
      budget = budgetObj as Record<string, Object>;
    }
    const before: number = LiveMapping.num(budget['before'], NaN);
    const after: number = LiveMapping.num(budget['after'], NaN);
    if (!isNaN(before) && !isNaN(after)) {
      it.budgetBefore = before;
      it.budgetAfter = after;
      it.budgetScope = LiveMapping.str(budget['scope']);
    }
    LiveMapping.mapLabels(w, it);
  }

  private static mapLabels(w: WireApprovalRequest, it: ApprovalItem): void {
    const labelsObj: Object | null | undefined = w.labels as Object | null | undefined;
    if (it.facts.length === 0 && LiveMapping.isObj(labelsObj) && !Array.isArray(labelsObj)) {
      const labels: Record<string, Object> = labelsObj as Record<string, Object>;
      for (const k of Object.keys(labels)) {
        it.facts.push(new KeyValue(k, LiveMapping.str(labels[k])));
      }
    }
  }

  /** ISO-8601 to epoch ms; 0 for empty or unparseable (same as Fmt.parseIso, kept here so this file has no kit imports). */
  static parseIso(iso: string): number {
    if (iso.length === 0) {
      return 0;
    }
    const t: number = Date.parse(iso);
    return isNaN(t) ? 0 : t;
  }

  /** True for a non-null JSON object (or array). */
  static isObj(v: Object | null | undefined): boolean {
    return v !== undefined && v !== null && typeof v === 'object';
  }

  /** A finite number, a numeric string ("50", "12.5") coerced, otherwise `dflt`. */
  static num(v: Object | null | undefined, dflt: number): number {
    if (typeof v === 'number') {
      return isFinite(v as number) ? (v as number) : dflt;
    }
    if (typeof v === 'string') {
      const t: string = (v as string).trim();
      if (t.length === 0) {
        return dflt;
      }
      const n: number = Number(t);
      return isFinite(n) ? n : dflt;
    }
    return dflt;
  }

  /** A string value, otherwise `dflt` (null, missing, number, object). */
  static text(v: Object | null | undefined, dflt: string): string {
    return typeof v === 'string' ? (v as string) : dflt;
  }

  static str(v: Object | undefined | null): string {
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
