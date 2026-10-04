import { http } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { ApprovalItem, PostureStats } from '../model/Models';
import { VoteBody, WireMember, WireWhoAmI } from '../model/Wire';
import { Log } from '../common/Format';
import { ApprovalsPage, ApprovalsRepository, ConnectionInfo, RepoError } from './ApprovalsRepository';
import { LiveMapping, NET_TIMEOUT } from './LiveMapping';

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
    try {
      const page: ApprovalsPage = LiveMapping.parseApprovals(body);
      if (page.skipped > 0) {
        Log.warn('Skipped ' + page.skipped.toString() + ' malformed approval entries from the gateway');
      }
      return page;
    } catch (e) {
      throw LiveRepository.noted(e as Error, 'approvals', body);
    }
  }

  async getApproval(id: string, viewAs: string): Promise<ApprovalItem> {
    const body: string = await this.request(http.RequestMethod.GET, '/api/approvals/' + encodeURIComponent(id),
      viewAs, '');
    try {
      return LiveMapping.mapChecked(LiveMapping.parse(body, 'approval'));
    } catch (e) {
      throw LiveRepository.noted(e as Error, 'approval', body);
    }
  }

  async getStats(viewAs: string): Promise<PostureStats> {
    const body: string = await this.request(http.RequestMethod.GET, '/api/stats?window=24h', viewAs, '');
    try {
      return LiveMapping.parseStats(body);
    } catch (e) {
      throw LiveRepository.noted(e as Error, 'stats', body);
    }
  }

  async vote(id: string, decision: string, viewAs: string, comment: string): Promise<ApprovalItem> {
    const vb: VoteBody = new VoteBody();
    vb.comment = comment.length > 0 ? comment : null;
    const path: string = '/api/approvals/' + encodeURIComponent(id) + '/' + (decision === 'deny' ? 'deny' : 'approve');
    const body: string = await this.request(http.RequestMethod.POST, path, viewAs, JSON.stringify(vb));
    // A 2xx whose body cannot be parsed/mapped throws RepoError kind 'parse': the vote was most likely applied.
    try {
      return LiveMapping.mapChecked(LiveMapping.parse(body, 'vote result'));
    } catch (e) {
      throw LiveRepository.noted(e as Error, 'vote result', body);
    }
  }

  async testConnection(viewAs: string): Promise<ConnectionInfo> {
    try {
      const body: string = await this.request(http.RequestMethod.GET, '/api/whoami', viewAs, '');
      const who: WireWhoAmI = LiveMapping.parse(body, 'whoami') as WireWhoAmI;
      let name: string = viewAs;
      let role: string = '?';
      const member: WireMember | null = who.member;
      if (member !== null && member !== undefined && LiveMapping.isObj(member)) {
        name = LiveMapping.text(member.name, viewAs);
        role = LiveMapping.text(member.role, '?');
      } else if (LiveMapping.isObj(who.identity)) {
        role = LiveMapping.text(who.identity.role, '?');
      }
      return new ConnectionInfo(true, 'Connected to ' + this.baseUrl + ' as ' + name + ' (' + role + ')');
    } catch (e) {
      const msg: string = e instanceof RepoError ? (e as RepoError).message : 'Connection test failed';
      return new ConnectionInfo(false, msg);
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
      throw new RepoError(LiveMapping.errorMessage(text, resp.responseCode), resp.responseCode, 'http');
    } catch (e) {
      if (e instanceof RepoError) {
        throw e as RepoError;
      }
      const be: BusinessError = e as BusinessError;
      const code: number = (be !== undefined && be !== null && typeof be.code === 'number') ? be.code : -1;
      Log.warn('HTTP ' + method + ' ' + path + ' failed: code=' + code.toString() + ' ' +
        ((be !== undefined && be !== null) ? String(be.message) : ''));
      throw new RepoError(LiveMapping.friendly(code, this.baseUrl), 0,
        code === NET_TIMEOUT ? 'timeout' : 'network');
    } finally {
      req.destroy();
    }
  }

  /** Logs a decode failure (size only, never the body: it may hold payload data) and returns it for rethrow. */
  private static noted(e: Error, what: string, body: string): Error {
    Log.warn('Gateway ' + what + ' could not be decoded (' + body.length.toString() + ' bytes): ' + e.message);
    return e;
  }
}
