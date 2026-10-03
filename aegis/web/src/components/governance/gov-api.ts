// Typed governance API: path builders (always `?view_as=<member>`, CONTRACTS §5.2), wrappers over
// the shell client (`@/api/client`) with mock factories from web/src/mocks/governance, and
// `parseApiError` (duck-types the shell error, mock errors and fetch failures).
// 403/402/409 are REAL answers and are never replaced by mocks (the shell client only mocks
// 404/405/501/network). Owner: B18-dashboard-gov-approvals. B19 imports this read-only.
import { api, type ApiResult } from '@/api/client';
import type {
  Agent,
  ApprovalRequest,
  ApprovalRoute,
  ApprovalRulesResponse,
  ApprovalSimulateRequest,
  ApprovalsResponse,
  ApproverLevel,
  Member,
  OrgResponse,
  PolicyChange,
  WhoAmI,
} from '@/api/types';
import { mockApproval, mockApprovals, mockCancel, mockSimulate, mockVote, type ApprovalStatusFilter } from '@/mocks/governance/approvals';
import { mockAgentsList, mockCreateMember, mockMembersList, mockOrg, mockPatchAgent, mockPatchMember, mockWhoAmI } from '@/mocks/governance/org';
import { mockRules } from '@/mocks/governance/rules';

export type { ApprovalStatusFilter };

/** Append `view_as=<id>` (and keep existing query). */
export function withViewer(path: string, viewerId: string | null | undefined): string {
  if (!viewerId) return path;
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}view_as=${encodeURIComponent(viewerId)}`;
}

export const govPaths = {
  approvals: (viewerId: string | null, status: ApprovalStatusFilter = 'pending', kind?: string | null) =>
    withViewer(`/api/approvals?status=${status}&limit=500${kind ? `&kind=${encodeURIComponent(kind)}` : ''}`, viewerId),
  approval: (id: string, viewerId: string | null) => withViewer(`/api/approvals/${encodeURIComponent(id)}`, viewerId),
  approvalRules: () => '/api/approvals/rules',
  org: (viewerId: string | null) => withViewer('/api/org', viewerId),
  members: (viewerId: string | null) => withViewer('/api/members', viewerId),
  agents: (viewerId: string | null) => withViewer('/api/agents', viewerId),
  whoami: (viewerId: string | null) => withViewer('/api/whoami', viewerId),
};

/** Mock factories keyed like govPaths (for useApi `mock`). */
export const govMocks = {
  approvals: (viewerId: string | null, status: ApprovalStatusFilter = 'pending', kind?: string | null) => () => mockApprovals(viewerId, status, kind),
  approval: (id: string, viewerId: string | null) => () => mockApproval(id, viewerId),
  approvalRules: () => mockRules,
  org: () => mockOrg,
  members: () => mockMembersList,
  agents: () => mockAgentsList,
  whoami: (viewerId: string | null) => () => mockWhoAmI(viewerId),
};

/** ApprovalSimulateRequest + the G2 extension fields (ignored by a backend that doesn't know them). */
export interface ApprovalSimulateRequestExt extends ApprovalSimulateRequest {
  labels?: Record<string, string>;
  scope_type?: string | null;
  increase_pct?: number | null;
  changes?: PolicyChange[];
  /** Addendum A-28 extras */
  control_id?: string | null;
  loosening?: boolean | null;
  profile?: string | null;
}

export const govApi = {
  approvals: (viewerId: string | null, status: ApprovalStatusFilter = 'pending'): Promise<ApiResult<ApprovalsResponse>> =>
    api.get<ApprovalsResponse>(govPaths.approvals(viewerId, status), govMocks.approvals(viewerId, status)),
  approval: (id: string, viewerId: string | null): Promise<ApiResult<ApprovalRequest>> =>
    api.get<ApprovalRequest>(govPaths.approval(id, viewerId), govMocks.approval(id, viewerId)),
  approve: (id: string, viewerId: string | null, comment?: string | null): Promise<ApiResult<ApprovalRequest>> =>
    api.post<ApprovalRequest>(withViewer(`/api/approvals/${encodeURIComponent(id)}/approve`, viewerId), { comment: comment || null }, () =>
      mockVote(id, viewerId, 'approve', comment ?? null),
    ),
  deny: (id: string, viewerId: string | null, comment: string): Promise<ApiResult<ApprovalRequest>> =>
    api.post<ApprovalRequest>(withViewer(`/api/approvals/${encodeURIComponent(id)}/deny`, viewerId), { comment }, () => mockVote(id, viewerId, 'deny', comment)),
  cancel: (id: string, viewerId: string | null): Promise<ApiResult<ApprovalRequest>> =>
    api.post<ApprovalRequest>(withViewer(`/api/approvals/${encodeURIComponent(id)}/cancel`, viewerId), {}, () => mockCancel(id, viewerId)),
  rules: (): Promise<ApiResult<ApprovalRulesResponse>> => api.get<ApprovalRulesResponse>(govPaths.approvalRules(), mockRules),
  simulate: (req: ApprovalSimulateRequestExt, viewerId: string | null): Promise<ApiResult<ApprovalRoute>> =>
    api.post<ApprovalRoute>(withViewer('/api/approvals/simulate', viewerId), req, () => mockSimulate(req)),
  org: (viewerId: string | null): Promise<ApiResult<OrgResponse>> => api.get<OrgResponse>(govPaths.org(viewerId), mockOrg),
  whoami: (viewerId: string | null): Promise<ApiResult<WhoAmI>> => api.get<WhoAmI>(govPaths.whoami(viewerId), () => mockWhoAmI(viewerId)),
  patchMember: (id: string, patch: { role?: Member['role']; team_id?: string | null; active?: boolean }, viewerId: string | null): Promise<ApiResult<Member>> =>
    api.patch<Member>(withViewer(`/api/members/${encodeURIComponent(id)}`, viewerId), patch, () => mockPatchMember(id, patch, viewerId)),
  createMember: (body: { name: string; email: string; role: Member['role']; team_id: string | null }, viewerId: string | null): Promise<ApiResult<Member>> =>
    api.post<Member>(withViewer('/api/members', viewerId), body, mockCreateMember),
  patchAgent: (id: string, patch: { active?: boolean; allowed_models?: string[]; profile?: string | null }, viewerId: string | null): Promise<ApiResult<Agent>> =>
    api.patch<Agent>(withViewer(`/api/agents/${encodeURIComponent(id)}`, viewerId), patch, () => mockPatchAgent(id, patch, viewerId)),
};

// ------------------------------------------------------------------ errors

export interface ParsedApiError {
  status: number | null;
  type: string | null;
  message: string;
  required_role: ApproverLevel | null;
  approval_id: string | null;
  decision_id: string | null;
  expires_at: string | null;
}

interface EnvelopeLike {
  error?: { type?: string; message?: string; required_role?: ApproverLevel | null; approval_id?: string | null; decision_id?: string | null; expires_at?: string | null } | string;
  message?: string;
  detail?: unknown;
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return typeof v === 'object' && v !== null ? (v as Record<string, unknown>) : null;
}

/** Normalize anything thrown by api.* / mocks / fetch into one shape. */
export function parseApiError(e: unknown): ParsedApiError {
  const out: ParsedApiError = { status: null, type: null, message: 'Request failed', required_role: null, approval_id: null, decision_id: null, expires_at: null };
  const rec = asRecord(e);
  if (!rec) {
    out.message = typeof e === 'string' ? e : String(e);
    return out;
  }
  if (typeof rec.status === 'number') out.status = rec.status;
  // shell ApiRequestError / MockApiError: `envelope`; raw responses: `body`; or the envelope itself
  const env = (asRecord(rec.envelope) ?? asRecord(rec.body) ?? (rec.error !== undefined ? rec : null)) as EnvelopeLike | null;
  const inner = env && typeof env.error === 'object' && env.error !== null ? env.error : null;
  if (inner) {
    out.type = inner.type ?? null;
    out.message = inner.message ?? out.message;
    out.required_role = inner.required_role ?? null;
    out.approval_id = inner.approval_id ?? null;
    out.decision_id = inner.decision_id ?? null;
    out.expires_at = inner.expires_at ?? null;
  } else if (env && typeof env.error === 'string') {
    out.type = env.error;
  }
  if (!inner) {
    const detail = env?.detail;
    if (typeof detail === 'string') out.message = detail;
    else if (typeof rec.message === 'string' && rec.message) out.message = rec.message;
  }
  if (!out.type && typeof rec.type === 'string') out.type = rec.type;
  if (out.status === 0 || (out.status === null && /fetch|network/i.test(out.message))) out.message = 'Gateway unreachable — is it running on :8787?';
  return out;
}

/** Short human title for a parsed error. */
export function errorTitle(p: ParsedApiError): string {
  switch (p.type) {
    case 'forbidden':
      return 'Not allowed for this role';
    case 'approval_required':
      return `Approval required${p.required_role ? ` · needs ${p.required_role}` : ''}`;
    case 'approval_denied':
      return 'Approval denied';
    case 'conflict':
      return 'Conflict';
    case 'invalid_request':
      return 'Invalid request';
    case 'budget_exceeded':
      return 'Budget exceeded';
    case 'killed':
      return 'Kill switch active';
    default:
      return p.status ? `Request failed (${p.status})` : 'Request failed';
  }
}
