// Live-feed filter state <-> URL (plan 16 §2.3 "Live feed"). PURE module, node-testable.
// No sensitive data ever goes in a URL: only ids, enums and the free-text search the user typed.
import type { Action, DecisionSummary } from '@/api/types';
import type { DecisionFilter } from '../types';

const ACTIONS: Action[] = ['allow', 'log', 'redact', 'require_approval', 'block'];
const KEYS = ['surface', 'kind', 'agent', 'member', 'team', 'source', 'dest', 'control', 'q'] as const;

export const EMPTY_FILTER: DecisionFilter = {
  actions: [],
  surface: '',
  kind: '',
  agent: '',
  member: '',
  team: '',
  source: '',
  dest: '',
  control: '',
  q: '',
  nonAllow: false,
};

export function paramsToFilter(p: URLSearchParams): DecisionFilter {
  const f: DecisionFilter = { ...EMPTY_FILTER, actions: [] };
  const raw = p.get('action');
  if (raw) {
    f.actions = raw
      .split(',')
      .map((s) => s.trim())
      .filter((s): s is Action => (ACTIONS as string[]).includes(s));
  }
  for (const k of KEYS) f[k] = p.get(k) ?? '';
  f.nonAllow = p.get('na') === '1';
  return f;
}

/** Writes the filter into `base` (other params such as `mock`, `scenario`, `d` are kept). */
export function filterToParams(f: DecisionFilter, base?: URLSearchParams): URLSearchParams {
  const p = new URLSearchParams(base ? base.toString() : '');
  if (f.actions.length) p.set('action', f.actions.join(','));
  else p.delete('action');
  for (const k of KEYS) {
    if (f[k]) p.set(k, f[k]);
    else p.delete(k);
  }
  if (f.nonAllow) p.set('na', '1');
  else p.delete('na');
  return p;
}

export function isFilterActive(f: DecisionFilter): boolean {
  return f.actions.length > 0 || f.nonAllow || KEYS.some((k) => Boolean(f[k]));
}

export function matchDecision(d: DecisionSummary, f: DecisionFilter): boolean {
  if (f.actions.length && !f.actions.includes(d.action)) return false;
  if (f.nonAllow && d.action === 'allow') return false;
  if (f.surface && d.surface !== f.surface) return false;
  if (f.kind && d.kind !== f.kind) return false;
  if (f.agent && d.identity?.agent_id !== f.agent) return false;
  if (f.member && d.identity?.member_id !== f.member) return false;
  if (f.team && d.identity?.team_id !== f.team) return false;
  if (f.source && d.source !== f.source) return false;
  if (f.dest && d.destination?.dest_class !== f.dest) return false;
  if (f.control && d.control_id !== f.control && !(d.controls ?? []).some((c) => c.control_id === f.control)) return false;
  if (f.q) {
    const hay = [
      d.id,
      d.request_id,
      d.preview,
      d.reason,
      d.tool_name,
      d.model,
      d.control_id,
      d.identity?.agent_id,
      d.identity?.member_id,
      d.identity?.display_name,
      d.surface,
      ...(d.entities ?? []),
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
    if (!hay.includes(f.q.toLowerCase())) return false;
  }
  return true;
}

/** Server-side query (`&action=…&surface=…`) for GET /api/decisions. Multi-action filters stay client-side. */
export function toApiQuery(f: DecisionFilter): string {
  const p = new URLSearchParams();
  if (f.actions.length === 1) p.set('action', f.actions[0] as string);
  if (f.surface) p.set('surface', f.surface);
  if (f.kind) p.set('kind', f.kind);
  if (f.agent) p.set('agent_id', f.agent);
  if (f.member) p.set('member_id', f.member);
  if (f.team) p.set('team_id', f.team);
  if (f.control) p.set('control_id', f.control);
  if (f.q) p.set('q', f.q);
  const s = p.toString();
  return s ? `&${s}` : '';
}
