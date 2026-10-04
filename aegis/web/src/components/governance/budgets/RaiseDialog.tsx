// "Request increase" dialog (UIG-03, flow F5): pick a limit (dimension × window), set the new value
// (chips +25 % · +50 % · 2× · 2.5×, live +N %), see the LIVE approval route (POST /api/approvals/simulate
// with the G2 extension fields; falls back to a client estimate labelled "estimate"), give a reason,
// submit → POST /api/budgets/raise → ApplyResult (applied / pending_approval with Open / rejected /
// conflict / noop). The server's ApplyResult is authoritative. Owner: B19-dashboard-gov-policy.
import { ArrowRight, Loader2, Route, TrendingDown, TrendingUp, Wallet } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import type { ApplyResult, ApproverLevel, BudgetScopeView, BudgetStatus, PolicyChange } from '@/api/types';
import { ApproverBadge } from '@/components/governance/ApproverBadge';
import { errorTitle, govApi, parseApiError } from '@/components/governance/gov-api';
import { roleSatisfies } from '@/components/governance/lib/eligibility';
import { dimensionLabel, fmtDimension, windowLabel } from '@/components/governance/lib/format-gov';
import { routeChange } from '@/components/governance/policy/config-route';
import { policyApi, type MockViewer } from '@/components/governance/policy/policy-api';
import { toastApplyResult } from '@/components/governance/policy/policy-toast';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { ViewRole } from '@/lib/page';
import { cn } from '@/lib/utils';

const CHIPS: { label: string; f: number }[] = [
  { label: '+25%', f: 1.25 },
  { label: '+50%', f: 1.5 },
  { label: '2×', f: 2 },
  { label: '2.5×', f: 2.5 },
];

function key(l: BudgetStatus): string {
  return `${l.window}|${l.dimension}`;
}

function roundLimit(v: number, dim: string): number {
  if (dim === 'usd' || dim === 'spend_usd') return Math.round(v * 100) / 100;
  return Math.round(v);
}

interface RoutePreview {
  level: ApproverLevel;
  rule_id: string | null;
  two_person: boolean;
  estimate: boolean;
}

export function RaiseDialog({
  scope,
  initial,
  open,
  onOpenChange,
  viewer,
  role,
  onDone,
}: {
  scope: BudgetScopeView | null;
  initial: BudgetStatus | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  viewer: MockViewer;
  role: ViewRole;
  onDone?: (r: ApplyResult) => void;
}) {
  const limits = useMemo(() => scope?.limits ?? [], [scope]);
  const [sel, setSel] = useState<string>('');
  const [value, setValue] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [route, setRoute] = useState<RoutePreview | null>(null);
  const [routing, setRouting] = useState(false);

  // (re)initialise on open
  useEffect(() => {
    if (!open || !scope) return;
    const first = initial ?? limits[0] ?? null;
    if (!first) return;
    setSel(key(first));
    setValue(String(roundLimit(first.limit * 1.25, first.dimension)));
    setReason('');
    setRoute(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, scope?.scope]);

  const cur = limits.find((l) => key(l) === sel) ?? null;
  const newLimit = Number(value);
  const validNum = Number.isFinite(newLimit) && newLimit >= 0 && value.trim() !== '';
  const pct = cur && cur.limit > 0 && validNum ? ((newLimit - cur.limit) / cur.limit) * 100 : null;
  const same = cur !== null && validNum && newLimit === cur.limit;
  const raise = pct !== null && pct > 0;

  // live route preview (debounced; latest wins)
  useEffect(() => {
    if (!open || !cur || !scope || !validNum || same) {
      setRoute(null);
      return;
    }
    let live = true;
    setRouting(true);
    const change: PolicyChange = {
      kind: raise ? 'budget.raise' : 'budget.lower',
      path: `budgets.limits[scope=${scope.scope},window=${cur.window}].${cur.dimension}`,
      before: cur.limit,
      after: newLimit,
      control_id: null,
      scope: scope.scope,
      dimension: cur.dimension,
      increase_pct: pct === null ? null : Math.round(pct * 10) / 10,
      loosening: raise,
      summary: '',
    };
    const est = routeChange(change);
    const t = window.setTimeout(async () => {
      try {
        const r = await govApi.simulate(
          {
            kind: 'config_change',
            action_type: change.kind,
            resource: `budget:${scope.scope}`,
            requester_member_id: viewer.id,
            scope_type: scope.scope_type,
            increase_pct: change.increase_pct,
            changes: [change],
          },
          viewer.id,
        );
        if (!live) return;
        // trust the server only if it clearly understood the budget change (G2 extension)
        const understood = Boolean(r.data.rule_id && /raise|budget|tighten|lower/i.test(r.data.rule_id));
        setRoute(understood ? { level: r.data.required_role, rule_id: r.data.rule_id, two_person: r.data.two_person, estimate: r.isMock } : { level: est.level, rule_id: est.rule_id, two_person: false, estimate: true });
      } catch {
        if (live) setRoute({ level: est.level, rule_id: est.rule_id, two_person: false, estimate: true });
      } finally {
        if (live) setRouting(false);
      }
    }, 250);
    return () => {
      live = false;
      window.clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sel, cur?.limit, scope?.scope, value, viewer.id]);

  const direct = route ? route.level === 'auto' || roleSatisfies(role, route.level) : false;

  const submit = async () => {
    if (!scope || !cur || !validNum || same) return;
    setBusy(true);
    try {
      const r = await policyApi.raise({ scope: scope.scope, window: cur.window, dimension: cur.dimension, new_limit: newLimit, reason: reason.trim() }, viewer);
      const what = `${scope.scope} ${windowLabel(cur.window)} ${dimensionLabel(cur.dimension)} ${fmtDimension(cur.dimension, cur.limit)} → ${fmtDimension(cur.dimension, newLimit)}`;
      toastApplyResult(r.data, { what });
      onDone?.(r.data);
      if (r.data.status === 'applied' || r.data.status === 'pending_approval' || r.data.status === 'noop') onOpenChange(false);
    } catch (e) {
      const p = parseApiError(e);
      toast.error(errorTitle(p), { description: p.message });
    } finally {
      setBusy(false);
    }
  };

  if (!scope) return null;
  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wallet className="size-4 text-accent-fg" /> Request budget change
          </DialogTitle>
          <DialogDescription className="text-text-2">
            {scope.name} <span className="font-mono text-text-3">· {scope.scope}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-text-3">Limit</div>
            <div className="flex flex-wrap gap-1.5">
              {limits.map((l) => (
                <button
                  key={key(l)}
                  type="button"
                  onClick={() => {
                    setSel(key(l));
                    setValue(String(roundLimit(l.limit * 1.25, l.dimension)));
                  }}
                  className={cn(
                    'rounded-md border px-2.5 py-1 text-xs transition-colors',
                    key(l) === sel ? 'border-[var(--accent-border)] bg-[var(--accent-subtle)] text-accent-fg' : 'border-border bg-surface-2 text-text-2 hover:border-border-strong',
                  )}
                >
                  {windowLabel(l.window)} · {dimensionLabel(l.dimension)}
                </button>
              ))}
            </div>
            {cur ? (
              <div className="mt-2 text-xs text-text-3 tabular">
                used {fmtDimension(cur.dimension, cur.used)} of {fmtDimension(cur.dimension, cur.limit)} ({Math.round(cur.pct)}%)
                {cur.label ? <span className="ml-1 text-text-4">· {cur.label}</span> : null}
              </div>
            ) : null}
          </div>

          <div>
            <div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-text-3">New limit</div>
            <div className="flex items-center gap-2">
              <div className="font-mono text-sm text-text-3 tabular">{cur ? fmtDimension(cur.dimension, cur.limit) : '—'}</div>
              <ArrowRight className="size-3.5 text-text-3" />
              <Input
                value={value}
                onChange={(e) => setValue(e.target.value)}
                inputMode="decimal"
                className="h-8 w-32 font-mono tabular"
                aria-label="New limit"
                autoFocus
              />
              {pct !== null && !same ? (
                <span className={cn('inline-flex items-center gap-1 text-sm font-medium tabular', raise ? 'text-redact' : 'text-allow')}>
                  {raise ? <TrendingUp className="size-3.5" /> : <TrendingDown className="size-3.5" />}
                  {pct > 0 ? '+' : ''}
                  {Math.round(pct)}%
                </span>
              ) : null}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {CHIPS.map((c) => (
                <button
                  key={c.label}
                  type="button"
                  disabled={!cur}
                  onClick={() => cur && setValue(String(roundLimit(cur.limit * c.f, cur.dimension)))}
                  className="rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-xs text-text-2 transition-colors hover:border-border-strong hover:text-text-1"
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-border bg-surface-1 p-3">
            <div className="mb-1.5 flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wider text-text-3">
              <Route className="size-3" /> Approval route
              {route?.estimate ? <span className="rounded border border-border px-1 text-[10px] normal-case tracking-normal text-text-3">estimate</span> : null}
              {routing ? <Loader2 className="size-3 animate-spin" /> : null}
            </div>
            {same || !validNum ? (
              <div className="text-xs text-text-3">Enter a different limit to see who has to approve it.</div>
            ) : route ? (
              <div className="space-y-1.5">
                <div className="flex flex-wrap items-center gap-2 text-sm text-text-1">
                  <span className="tabular">
                    {pct !== null ? `${pct > 0 ? '+' : ''}${Math.round(pct)}%` : ''} {scope.scope_type} budget
                  </span>
                  <ArrowRight className="size-3.5 text-text-3" />
                  <ApproverBadge level={route.level} size="sm" />
                  {route.rule_id ? <span className="font-mono text-xs text-text-3">({route.rule_id})</span> : null}
                  {route.two_person ? <span className="text-2xs text-approval">two-person</span> : null}
                </div>
                <div className={cn('text-xs', direct ? 'text-allow' : 'text-approval')}>
                  {route.level === 'deny'
                    ? 'No one can approve this change.'
                    : direct
                      ? route.level === 'auto'
                        ? 'Applies automatically — no approval needed.'
                        : `You are ${role === 'admin' ? 'an' : 'the'} ${role} → you can apply this directly.`
                      : `You are a${role === 'admin' ? 'n' : ''} ${role} → this creates an approval request for ${route.level === 'self' ? 'the sponsor' : `an ${route.level}`}.`}
                </div>
              </div>
            ) : (
              <div className="text-xs text-text-3">Routing…</div>
            )}
          </div>

          <div>
            <div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-text-3">Reason</div>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              placeholder="e.g. Earnings week — copilot traffic is 2× normal"
              className="text-sm"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={busy || !cur || !validNum || same}
            className={cn(!direct && route && 'bg-approval text-white hover:bg-approval/90')}
          >
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : null}
            {direct ? 'Apply now' : route ? `Request approval · needs ${route.level}` : 'Submit'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
