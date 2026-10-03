// PlaygroundResponse → DecisionDetail-shaped object so the playground reuses the decision trace + Wire diff.
import type {
  ControlHit,
  DecisionDetail,
  DestClass,
  Direction,
  Kind,
  PlaygroundRequest,
  PlaygroundResponse,
  Surface,
} from '@/api/types';

const IN_SURFACES = new Set<Surface>(['model.response', 'tool.output', 'mcp.result', 'mcp.list', 'egress.response', 'a2a.result']);
const UNTRUSTED = new Set<Surface>(['tool.output', 'mcp.result', 'mcp.list', 'egress.response']);

export function destClassOf(dest: PlaygroundRequest['destination']): DestClass {
  if (dest === 'local' || dest === 'ollama') return 'local';
  if (dest === 'third_party') return 'third_party';
  return 'remote';
}

export function kindOf(surface: Surface): Kind {
  if (surface.startsWith('tool.')) return 'tool_call';
  if (surface.startsWith('mcp.')) return 'mcp';
  if (surface.startsWith('egress.')) return 'egress';
  if (surface.startsWith('a2a.')) return 'a2a';
  if (surface === 'config.change') return 'config_change';
  return 'model_call';
}

export function detailFromPlayground(resp: PlaygroundResponse, req: PlaygroundRequest, viewerId?: string | null): DecisionDetail {
  const v = resp.verdict;
  const surface: Surface = req.surface ?? 'prompt.user';
  const direction: Direction = IN_SURFACES.has(surface) ? 'in' : 'out';
  const destClass = destClassOf(req.destination);
  const primary = v.primary ?? null;
  const controls: ControlHit[] = (v.decisions ?? [])
    .filter((d) => d.action !== 'allow')
    .map((d) => ({ control_id: d.control_id, action: d.action, mode: d.mode, score: d.score, latency_ms: d.latency_ms, degraded: d.degraded }));
  const redactions = resp.redactions ?? v.redactions ?? [];
  const entities = [...new Set(redactions.map((r) => r.entity))];
  const amount = req.tool_args && typeof req.tool_args.amount_usd === 'number' ? (req.tool_args.amount_usd as number) : null;
  const seg = (text: string) => ({ path: 'text', text, role: direction === 'in' ? 'tool' : 'user', trusted: !UNTRUSTED.has(surface), redactable: true });
  return {
    id: resp.decision_id || v.id,
    ts: v.ts,
    request_id: v.request_id,
    action: v.action,
    kind: req.kind ?? kindOf(surface),
    surface,
    direction,
    destination: {
      name: resp.response?.provider ?? (typeof req.destination === 'string' && !['local', 'remote', 'third_party'].includes(req.destination) ? req.destination : destClass),
      dest_class: destClass,
      provider: resp.response?.provider ?? null,
    },
    model: resp.response?.model ?? req.model ?? null,
    tool_name: req.tool_name ?? null,
    action_type: null,
    amount_usd: amount,
    identity: {
      org_id: 'acme-capital',
      team_id: null,
      member_id: req.agent_id ? null : (viewerId ?? null),
      agent_id: req.agent_id ?? null,
      role: req.agent_id ? 'agent' : 'member',
    },
    session_id: 'playground',
    source: 'playground',
    control_id: primary?.control_id ?? null,
    reason: primary?.reason ?? (v.action === 'allow' ? 'No control fired — request allowed.' : ''),
    score: primary?.score ?? null,
    threshold: primary?.threshold ?? null,
    controls,
    redaction_count: redactions.length,
    entities,
    approval_id: v.approval?.id ?? primary?.approval_id ?? null,
    latency_ms: v.latency_ms ?? resp.timings?.total_ms ?? 0,
    upstream_ms: null,
    policy_version: v.policy_version,
    feed_serial: v.feed_serial,
    degraded: v.degraded,
    cost_usd: null,
    tokens: null,
    preview: (resp.outbound || resp.original || '').slice(0, 200),
    dry_run: v.dry_run,
    decisions: v.decisions ?? [],
    redactions,
    mutations: v.mutations ?? [],
    usage: null,
    wire: {
      decision_id: resp.decision_id,
      original: [seg(resp.original ?? req.text)],
      outbound: [seg(resp.outbound ?? req.text)],
      response_raw: resp.response?.raw ?? null,
      response_local: resp.response?.local ?? null,
      upstream_request_preview: null,
    },
    audit_seq: null,
    audit_hash: null,
  };
}
