// ASI09 (human-agent trust exploitation) helpers for the approval card. PURE + type-only imports so
// node:test can load it (tests/unit/dashboard_governance/asi09_review.test.mjs).
//
// The server attaches `review` to every approval (src/aegis/approvals/serialize_review.py): the exact
// bound action, agent-written (untrusted) text, risk signals and a destructive flag. `reviewOf` uses
// it when present and otherwise derives the same shape from the payload — the real backend shape
// (`payload.bound.{tool_name,args_masked}`, `payload.tool/args/agent_note`) first, then the legacy
// mock shape (`tool_name/tool_args/justification`).
import type { ApprovalRequest } from '@/api/types';

export interface AgentText {
  field: string;
  text: string;
  source: string;
  untrusted: true;
}

export interface FailedCheck {
  name: string | null;
  detail: string | null;
  value?: unknown;
  limit?: unknown;
  param?: string | null;
}

export interface ApprovalReview {
  bound: {
    present: boolean;
    tool: string | null;
    args: Record<string, unknown> | null;
    amount_usd: number | null;
    destination: string | null;
    resource: string | null;
    surface: string | null;
    mcp_server: string | null;
    method: string | null;
    url: string | null;
    fingerprint: string | null;
    params_hash: string | null;
    max_uses: number | null;
    grant_ttl_s: number | null;
  };
  agent_text: AgentText[];
  risk: {
    control_id: string | null;
    reason: string | null;
    rule_id: string | null;
    rule_when: string | null;
    rule_description: string | null;
    failed_checks: FailedCheck[];
    flood_cap: string | null;
    replay_of: unknown;
  };
  destructive: boolean;
  destructive_reason: string | null;
  title_agent_fields: string[];
}

export const AGENT_TEXT_ARGS = ['justification', 'reason', 'rationale', 'note', 'notes', 'why', 'explanation', 'comment', 'message_to_approver', 'context'];
const DEST_ARGS = ['to', 'recipient', 'recipients', 'email', 'destination', 'dest', 'url', 'host', 'channel', 'account', 'iban', 'payee', 'vendor', 'bucket', 'target', 'repo', 'environment', 'env'];
const DESTRUCTIVE_RX = /(delete|drop|destroy|purge|wipe|truncate|terminate|revoke|remove|rm_|export|transfer|wire|deploy|kill|reset|disable)/i;
const DESTRUCTIVE_SQL_RX = /\b(delete\s+from|drop\s+(table|database|schema)|truncate|alter\s+table|update\s+\w+\s+set)\b/i;

function rec(v: unknown): Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function str(v: unknown): string | null {
  return typeof v === 'string' && v.trim() ? v : null;
}
function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function destinationOf(args: Record<string, unknown>, bound: Record<string, unknown>, labels: Record<string, string>): string | null {
  for (const k of DEST_ARGS) {
    const v = args[k];
    if (typeof v === 'string' && v.trim()) return `${k}: ${v}`;
    if (Array.isArray(v) && v.length && v.every((x) => typeof x === 'string')) return `${k}: ${v.slice(0, 5).join(', ')}${v.length > 5 ? ' …' : ''}`;
  }
  if (str(bound.url)) return `url: ${bound.url as string}`;
  if (str(bound.resource)) return `resource: ${bound.resource as string}`;
  if (str(labels.dest)) return `dest: ${labels.dest}`;
  return null;
}

export function destructiveReason(kind: string, actionType: string, tool: string | null, args: Record<string, unknown>, labels: Record<string, string>): string | null {
  if (String(labels.loosening ?? '').toLowerCase() === 'true') return 'loosens a security control';
  if (kind === 'action') {
    for (const [what, name] of [['tool', tool], ['action', actionType]] as const) {
      const m = name ? DESTRUCTIVE_RX.exec(name) : null;
      if (m) return `${what} '${name}' is irreversible or high-impact (${m[1].toLowerCase()})`;
    }
    for (const v of Object.values(args)) if (typeof v === 'string' && DESTRUCTIVE_SQL_RX.test(v)) return 'SQL statement modifies or deletes data';
    if (String(labels.env ?? '').toLowerCase() === 'prod') return 'targets production';
  }
  return null;
}

/** Client-side derivation (mocks / older servers); mirrors serialize_review.review_block. */
export function deriveReview(req: ApprovalRequest): ApprovalReview {
  const p = rec(req.payload);
  const bound = rec(p.bound);
  const routing = rec(p.routing);
  const explain = rec(p.explain);
  const labels = req.labels ?? {};
  const tool = str(bound.tool_name) ?? str(p.tool) ?? str(p.tool_name);
  const argsSrc = 'args_masked' in bound ? bound.args_masked : 'args' in p ? p.args : p.tool_args;
  const args = rec(argsSrc);
  const agentText: AgentText[] = [];
  const seen = new Set<string>();
  const add = (field: string, v: unknown, source: string) => {
    const t = str(v);
    if (!t || seen.has(t)) return;
    seen.add(t);
    agentText.push({ field, text: t.slice(0, 600), source, untrusted: true });
  };
  add('agent_note', p.agent_note, 'payload.agent_note');
  add('justification', p.justification, 'payload.justification');
  for (const k of AGENT_TEXT_ARGS) add(k, args[k], 'args_masked' in bound ? 'bound.args' : 'payload.args');
  const checks = (Array.isArray(p.checks) ? p.checks : Array.isArray(explain.checks) ? explain.checks : []).map(rec);
  const failed = checks
    .filter((c) => c.ok === false || c.result === 'fail')
    .slice(0, 8)
    .map((c) => ({ name: str(c.name) ?? str(c.label) ?? str(c.id), detail: str(c.detail), value: c.value, limit: c.limit, param: str(c.param) }));
  const title = req.title ?? '';
  const titleFields = Object.entries(args)
    .filter(([k, v]) => k !== 'amount_usd' && typeof v === 'string' && v.trim().length >= 3 && title.includes(v.trim()))
    .map(([k]) => k)
    .sort();
  const fp = req.fingerprint && req.fingerprint !== '-' ? req.fingerprint : null;
  const reason = destructiveReason(req.kind, req.action_type, tool, args, labels);
  return {
    bound: {
      present: Object.keys(bound).length > 0,
      tool,
      args: argsSrc && typeof argsSrc === 'object' && !Array.isArray(argsSrc) ? (argsSrc as Record<string, unknown>) : null,
      amount_usd: num(bound.amount_usd) ?? req.amount_usd ?? null,
      destination: destinationOf(args, bound, labels),
      resource: str(bound.resource) ?? req.resource ?? null,
      surface: str(bound.surface),
      mcp_server: str(bound.mcp_server),
      method: str(bound.method),
      url: str(bound.url),
      fingerprint: fp,
      params_hash: fp ? fp.slice(0, 16) : null,
      max_uses: req.max_uses ?? null,
      grant_ttl_s: num(routing.grant_ttl_s),
    },
    agent_text: agentText,
    risk: {
      control_id: req.control_id ?? str(p.control_id),
      reason: str(explain.summary) ?? (req.kind === 'action' ? str(p.reason) : null) ?? req.summary ?? null,
      rule_id: req.rule_id,
      rule_when: str(routing.when),
      rule_description: str(routing.description),
      failed_checks: failed,
      flood_cap: str(routing.flood_cap),
      replay_of: p.replay_of ?? null,
    },
    destructive: reason !== null,
    destructive_reason: reason,
    title_agent_fields: titleFields,
  };
}

/** Server `review` when present (live), else derived from the payload (mocks / older servers). */
export function reviewOf(req: ApprovalRequest): ApprovalReview {
  const server = (req as ApprovalRequest & { review?: ApprovalReview | null }).review;
  if (server && typeof server === 'object' && server.bound && Array.isArray(server.agent_text)) return server;
  return deriveReview(req);
}

/** Arg keys that hold agent-written prose (rendered with an "agent-written" tag in the args table). */
export function isAgentTextKey(key: string): boolean {
  return AGENT_TEXT_ARGS.includes(key);
}

// ------------------------------------------------------------------ anti approval-fatigue (flooding)
export interface FloodSignal {
  key: string;
  label: string;
  count: number;
  windowMin: number;
  pending: number;
  floodDenied: number;
  ids: string[];
}

export const FLOOD_WINDOW_MS = 5 * 60_000;
export const FLOOD_THRESHOLD = 5;

export function requesterKey(req: ApprovalRequest): string {
  return req.requester.agent_id ? `agent:${req.requester.agent_id}` : `member:${req.requester.member_id ?? req.requester.display_name ?? 'unknown'}`;
}

/** Requesters with >= threshold approval requests created within the window ending at `now`
 * (counting ones the engine auto-denied by its flood cap). Map key = requesterKey. */
export function floodSignals(items: ApprovalRequest[], now: number, opts: { windowMs?: number; threshold?: number } = {}): Map<string, FloodSignal> {
  const windowMs = opts.windowMs ?? FLOOD_WINDOW_MS;
  const threshold = opts.threshold ?? FLOOD_THRESHOLD;
  const groups = new Map<string, ApprovalRequest[]>();
  for (const r of items) {
    if (r.kind !== 'action' && r.kind !== 'mcp_pin') continue;
    const t = Date.parse(r.created_at);
    if (!Number.isFinite(t) || now - t > windowMs || t - now > 60_000) continue;
    const k = requesterKey(r);
    const g = groups.get(k);
    if (g) g.push(r);
    else groups.set(k, [r]);
  }
  const out = new Map<string, FloodSignal>();
  for (const [key, rs] of groups) {
    const floodDenied = rs.filter((r) => str(rec(rec(r.payload).routing).flood_cap)).length;
    if (rs.length < threshold && floodDenied === 0) continue;
    out.set(key, {
      key,
      label: rs[0].requester.agent_id ?? rs[0].requester.display_name ?? rs[0].requester.member_id ?? 'unknown',
      count: rs.length,
      windowMin: Math.round(windowMs / 60_000),
      pending: rs.filter((r) => r.status === 'pending').length,
      floodDenied,
      ids: rs.map((r) => r.id),
    });
  }
  return out;
}

export function floodText(f: FloodSignal): string {
  const denied = f.floodDenied ? ` (${f.floodDenied} auto-denied by the flood cap)` : '';
  return `${f.count} request${f.count === 1 ? '' : 's'} in ${f.windowMin} min${denied} — possible approval flooding`;
}

// ------------------------------------------------------------------ explicit confirmation
/** Phrase the approver must type before approving: the bound tool (or action type). */
export function confirmPhrase(req: ApprovalRequest, review: ApprovalReview = reviewOf(req)): string {
  return review.bound.tool ?? req.action_type ?? 'approve';
}

/** Destructive actions, and any request from a flooding requester, need a typed confirmation. */
export function needsTypedConfirm(review: ApprovalReview, flooded: boolean): boolean {
  return review.destructive || flooded;
}

export function confirmMatches(typed: string, phrase: string): boolean {
  return typed.trim().toLowerCase() === phrase.trim().toLowerCase();
}
