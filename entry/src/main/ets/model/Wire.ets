/**
 * Wire types of the Aegis gateway dashboard API, copied from aegis/docs/CONTRACTS.md §5.5
 * (web/src/api/types.ts) and Addendum A.28. Only the fields Aegis Pocket reads are listed;
 * JSON from the gateway is parsed into these interfaces and then mapped to UI models.
 */

export interface WireIdentity {
  org_id: string;
  team_id: string | null;
  member_id: string | null;
  agent_id: string | null;
  role: string;
  display_name?: string | null;
}

export interface WireApprovalVote {
  member_id: string;
  role: string;
  decision: string;
  comment: string | null;
  ts: string;
}

export interface WireApprovalRequest {
  id: string;
  team_id: string | null;
  kind: string;
  action_type: string;
  title: string;
  summary: string | null;
  requester: WireIdentity;
  amount_usd: number | null;
  resource: string | null;
  labels: Record<string, string>;
  payload: Record<string, Object>;
  required_role: string;
  two_person: boolean;
  rule_id: string | null;
  votes: WireApprovalVote[];
  status: string;
  created_at: string;
  expires_at: string | null;
  decided_at: string | null;
  decided_by: string[];
  control_id: string | null;
  can_vote?: boolean;
  can_deny?: boolean;
  why_not?: string | null;
}

export interface WireApprovalsResponse {
  items: WireApprovalRequest[];
  counts: Record<string, number>;
}

export interface WireStatsKpis {
  requests: number;
  allowed: number;
  logged: number;
  redacted: number;
  blocked: number;
  approvals_pending: number;
  approvals_decided: number;
  spend_usd: number;
  spend_today_usd: number;
  org_budget_used_pct: number;
  tokens: number;
  local_compute_s: number;
  cost_avoided_usd: number;
  active_agents: number;
  p50_overhead_ms: number;
  p95_overhead_ms: number;
  degraded: boolean;
}

export interface WireStatsResponse {
  window: string;
  generated_at: string;
  kpis: WireStatsKpis;
}

export interface WireMember {
  id: string;
  name: string;
  role: string;
  team_id: string | null;
}

export interface WireWhoAmI {
  identity: WireIdentity;
  member: WireMember | null;
}

export interface WireErrorInner {
  type: string;
  message: string;
}

export interface WireErrorEnvelope {
  error: WireErrorInner;
}

/** Body for POST /api/approvals/{id}/approve|deny. */
export class VoteBody {
  comment: string | null = null;
}
