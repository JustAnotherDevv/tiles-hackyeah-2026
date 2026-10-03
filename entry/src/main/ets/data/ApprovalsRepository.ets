import { ApprovalItem, PostureStats } from '../model/Models';

/** Error raised by a repository; `code` is the HTTP status (0 = network/parse failure). */
export class RepoError extends Error {
  code: number;

  constructor(message: string, code: number) {
    super(message);
    this.name = 'RepoError';
    this.code = code;
  }
}

export class ApprovalsPage {
  items: ApprovalItem[] = [];
  pending: number = 0;
}

export class ConnectionInfo {
  ok: boolean;
  message: string;

  constructor(ok: boolean, message: string) {
    this.ok = ok;
    this.message = message;
  }
}

/**
 * Source of approval requests and posture stats. Two implementations:
 * - MockRepository: on-device simulation (default, works without the gateway; clearly labelled "Mock mode").
 * - LiveRepository: the Aegis gateway REST API (`/api/approvals`, `/api/stats`, `/api/whoami`).
 * `viewAs` is the member id sent as `X-Aegis-View-As`.
 */
export interface ApprovalsRepository {
  readonly mode: string; // 'mock' | 'live'

  listApprovals(viewAs: string): Promise<ApprovalsPage>;

  getApproval(id: string, viewAs: string): Promise<ApprovalItem>;

  getStats(viewAs: string): Promise<PostureStats>;

  /** decision = 'approve' | 'deny'. Resolves with the updated request; rejects with RepoError (e.g. 403 forbidden). */
  vote(id: string, decision: string, viewAs: string, comment: string): Promise<ApprovalItem>;

  testConnection(viewAs: string): Promise<ConnectionInfo>;

  /** Called on every poll tick; the mock uses it to simulate new agent requests. */
  tick(nowMs: number): void;
}
