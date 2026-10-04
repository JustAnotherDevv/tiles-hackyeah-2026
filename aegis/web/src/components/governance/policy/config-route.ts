// Client-side ESTIMATE of the approval route for config changes, mirroring the approvals-engine
// `config_rules` (docs/plan/09 §config_rules, a superset of CONTRACTS §4.3). Used only when the
// server can't tell us (G2 gap, or simulate failing): RaiseDialog preview fallback. The server's
// PolicyDiffResponse.required_role / ApprovalRoute / ApplyResult always win and the UI labels this
// value "estimate". Owner: B19-dashboard-gov-policy.
import type { ApproverLevel, PolicyChange } from '@/api/types';

export interface RouteEstimate {
  level: ApproverLevel;
  rule_id: string | null;
  text: string;
}

const LEVEL_RANK: Record<ApproverLevel, number> = { auto: 0, self: 1, admin: 2, owner: 3, deny: 4 };
const CRITICAL = new Set(['DLP-02', 'EXE-01', 'SIG-01', 'SIG-02']);

function scopeType(scope: string | null | undefined): string {
  if (!scope) return '';
  const i = scope.indexOf(':');
  return i < 0 ? scope : scope.slice(0, i);
}

type ChangeLike = Pick<PolicyChange, 'kind' | 'scope' | 'increase_pct'> & Partial<Pick<PolicyChange, 'control_id' | 'loosening'>>;

/** Route one change (first match wins). */
export function routeChange(c: ChangeLike): RouteEstimate {
  const k = c.kind;
  const st = scopeType(c.scope);
  const pct = c.increase_pct ?? 0;
  const r = (level: ApproverLevel, rule_id: string, text: string): RouteEstimate => ({ level, rule_id, text });
  if (k === 'approval.rule') return r('owner', 'approval-rules', 'approval rules → owner');
  if (['control.enable', 'control.add', 'control.action.tighten', 'control.threshold.tighten', 'model.disallow'].includes(k)) {
    return r('auto', 'protect-more', 'tightening change → applies automatically');
  }
  if (['control.disable', 'control.remove', 'control.mode', 'control.action.loosen'].includes(k)) {
    if (c.control_id && CRITICAL.has(c.control_id)) return r('owner', 'disable-control-critical', `${k} on critical ${c.control_id} → owner`);
    return r('admin', 'disable-control', `${k} → admin`);
  }
  if (k === 'budget.raise') {
    const p = `+${Math.round(pct)}%`;
    if (st === 'org') return pct > 100 ? r('owner', 'raise-org-2x', `${p} org budget → owner (two-person)`) : r('owner', 'raise-org', `${p} org budget → owner`);
    if (st === 'team') return pct > 100 ? r('owner', 'raise-large', `${p} team budget (> 100%) → owner`) : r('admin', 'raise-team-small', `${p} team budget (≤ 100%) → admin`);
    if (['member', 'agent', 'session'].includes(st)) {
      return pct > 50 ? r('admin', 'raise-agent-large', `${p} ${st} budget (> 50%) → admin`) : r('self', 'raise-small', `${p} ${st} budget (≤ 50%) → self`);
    }
    return r('owner', 'raise-other', `${p} budget → owner`);
  }
  if (k === 'budget.remove') return r('owner', 'raise-other', 'budget removed → owner');
  if (['budget.lower', 'budget.add'].includes(k)) return r('admin', 'budget-tighten', 'tighter budget → admin');
  if (k === 'profile.change') return c.loosening ? r('owner', 'profile-down', 'weaker profile → owner') : r('auto', 'profile-up', 'stricter profile → auto');
  if (k === 'killswitch.off') return c.scope === 'global' ? r('owner', 'killswitch-release-global', 'release global kill → owner') : r('admin', 'loosen-threshold', 'release kill switch → admin');
  if (k === 'control.threshold.loosen') return r('admin', 'loosen-threshold', 'looser threshold → admin');
  if (k === 'killswitch.on') return r('admin', 'tighten', 'kill switch on → admin');
  if (k === 'model.allow') return r('admin', 'model-allow', 'allow model → admin');
  if (['provider.change', 'route.change'].includes(k)) return r('owner', 'provider-change', `${k} → owner`);
  if (c.loosening) return r('admin', 'policy-loosen', 'loosening change → admin');
  if (['control.params', 'other'].includes(k)) return r('self', 'policy-neutral', 'neutral change → self');
  return r('owner', 'default', `${k} → owner (default_config_approver)`);
}

/** Multi-change proposals take the highest level among their changes. */
export function routeChanges(changes: ChangeLike[]): RouteEstimate | null {
  if (changes.length === 0) return null;
  let best: RouteEstimate | null = null;
  for (const c of changes) {
    const r = routeChange(c);
    if (!best || LEVEL_RANK[r.level] > LEVEL_RANK[best.level]) best = r;
  }
  return best;
}
