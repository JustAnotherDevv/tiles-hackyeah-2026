// Budgets (UIG-03 + kill switch half of UIG-10 + UIG-15 chart), flows F5/F6: org → team → member/agent
// hierarchy with live usage bars (SSE budget.updated/threshold + 5 s polling), "Request increase" with
// the live approval route → POST /api/budgets/raise → ApplyResult, kill switch per scope + global.
// Owner: B19-dashboard-gov-policy.
import { AlertTriangle, Cpu, LineChart, Wallet } from '@/components/icons';
import { useMemo, useState } from 'react';
import { useApi } from '@/api/hooks';
import type { BudgetDimension, BudgetScopeView, BudgetStatus, BudgetWindow, BudgetsResponse } from '@/api/types';
import { Gauge } from '@/components/charts';
import { BudgetHistoryChart } from '@/components/governance/budgets/BudgetHistoryChart';
import { pickLimit, BudgetTree } from '@/components/governance/budgets/BudgetTree';
import { GlobalKillPanel } from '@/components/governance/budgets/KillSwitchControl';
import { RaiseDialog } from '@/components/governance/budgets/RaiseDialog';
import { BudgetStatePill } from '@/components/governance/budgets/UsageBar';
import { GovernanceToaster } from '@/components/governance/GovernanceToaster';
import { hasCapability, useDirectory, useNow, useViewer, useWhoAmI } from '@/components/governance/hooks';
import { dimensionLabel, fmtDimension, fmtSeconds, scopeLabel, windowLabel } from '@/components/governance/lib/format-gov';
import { PersonaSwitcher } from '@/components/governance/PersonaSwitcher';
import { policyMocks, policyPaths, useMockStoreRefresh, type MockViewer } from '@/components/governance/policy/policy-api';
import { EmptyState, KpiTile, MockBadge, PageHeader, Panel, Segmented } from '@/components/shell';
import { Skeleton } from '@/components/ui/skeleton';
import type { PageMeta } from '@/lib/page';
import { cn } from '@/lib/utils';

export const meta: PageMeta = {
  path: '/governance/budgets',
  title: 'Budgets',
  icon: 'Wallet',
  section: 'Governance',
  order: 20,
  minRole: 'member',
  shortcut: 'g b',
  description: 'Org → team → agent limits, live usage, increase requests, kill switch',
};

const DIMS: { value: BudgetDimension; label: string }[] = [
  { value: 'usd', label: 'USD' },
  { value: 'tokens', label: 'Tokens' },
  { value: 'compute_s', label: 'Compute' },
  { value: 'spend_usd', label: 'Agent spend' },
];
const WINDOWS: { value: BudgetWindow; label: string }[] = [
  { value: 'day', label: 'Day' },
  { value: 'month', label: 'Month' },
  { value: 'session', label: 'Session' },
];

export default function BudgetsPage() {
  const { viewerId, role } = useViewer();
  const who = useWhoAmI();
  const dir = useDirectory();
  const now = useNow(1000);
  const viewer: MockViewer = useMemo(() => ({ id: viewerId, role }), [viewerId, role]);
  const res = useApi<BudgetsResponse>(policyPaths.budgets(viewerId), {
    mock: policyMocks.budgets,
    refreshOn: ['budget.updated', 'budget.threshold', 'policy.applied', 'killswitch'],
    refreshMs: 5000,
  });
  useMockStoreRefresh(res.refresh, res.isMock);

  const [dimension, setDimension] = useState<BudgetDimension>('usd');
  const [win, setWin] = useState<BudgetWindow>('day');
  const [selected, setSelected] = useState<string | null>(null);
  const [raise, setRaise] = useState<{ scope: BudgetScopeView; limit: BudgetStatus | null } | null>(null);

  const data = res.data;
  const canKill = hasCapability(who.data, 'killswitch', role);
  const org = data?.scopes.find((s) => s.scope_type === 'org') ?? null;
  const orgDay = org?.limits.find((l) => l.window === 'day' && l.dimension === 'usd') ?? null;
  const orgMonth = org?.limits.find((l) => l.window === 'month' && l.dimension === 'usd') ?? null;
  const orgCompute = org?.limits.find((l) => l.window === 'day' && l.dimension === 'compute_s') ?? null;
  const soft = data?.scopes.filter((s) => s.state === 'soft').length ?? 0;
  const hard = data?.scopes.filter((s) => s.state === 'hard').length ?? 0;
  const ks = data?.kill_switch;
  const killedCount = ks ? ks.teams.length + ks.members.length + ks.agents.length + ks.sessions.length : 0;

  const sel = data?.scopes.find((s) => s.scope === selected) ?? org;
  const selLimit = sel ? pickLimit(sel, dimension, win).status ?? sel.limits[0] ?? null : null;
  // prefer a daily window for the 24 h burn-down
  const chartDim = (selLimit?.dimension ?? dimension) as BudgetDimension;

  const sponsorOf = (agentId: string) => dir.sponsorOf(agentId);
  const memberName = (id: string) => dir.nameOf(id);

  return (
    <div className="space-y-5">
      <GovernanceToaster />
      <PageHeader
        title="Budgets"
        icon={Wallet}
        subtitle="Hierarchical spend limits enforced inline. Soft limit downgrades the model, hard limit returns 402, kill switch returns 429."
        badge={res.isMock ? <MockBadge /> : null}
        actions={<PersonaSwitcher />}
      />

      <div className="flex flex-wrap items-center gap-2 sm:gap-3">
        <Segmented value={dimension} options={DIMS} onChange={setDimension} ariaLabel="Dimension" />
        <Segmented value={win} options={WINDOWS} onChange={setWin} ariaLabel="Window" />
        {!canKill ? <span className="basis-full text-xs text-text-3 sm:basis-auto">Kill switch locked for the {role} role</span> : null}
        {data ? <span className="ml-auto hidden font-mono text-2xs text-text-4 sm:inline">pricing {data.pricing_version}</span> : null}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="col-span-2 flex items-center gap-4 rounded-lg border border-border bg-card p-4 shadow-card lg:col-span-1">
          {orgDay ? (
            <Gauge
              value={Math.min(orgDay.pct, 100)}
              max={100}
              label="Org spend today"
              sublabel="of limit"
              tone={orgDay.pct >= 100 ? 'bad' : orgDay.pct >= 80 ? 'warn' : 'neutral'}
              format={() => `${Math.round(orgDay.pct)}%`}
              size={72}
            />
          ) : (
            <Skeleton className="size-[72px] rounded-full" />
          )}
          <div className="min-w-0">
            <div className="text-xs text-text-3">Org spend today</div>
            <div className="mt-0.5 font-mono text-lg font-semibold text-text-1 tabular">{orgDay ? fmtDimension('usd', orgDay.used) : '—'}</div>
            <div className="text-xs text-text-3 tabular">of {orgDay ? fmtDimension('usd', orgDay.limit) : '—'} daily limit</div>
          </div>
        </div>
        <KpiTile
          label="Org this month"
          icon={LineChart}
          value={orgMonth ? fmtDimension('usd', orgMonth.used) : '—'}
          hint={orgMonth ? `of ${fmtDimension('usd', orgMonth.limit)} · ${Math.round(orgMonth.pct)}%` : undefined}
          loading={!data}
        />
        <KpiTile
          label="Local compute today"
          icon={Cpu}
          value={orgCompute ? fmtSeconds(orgCompute.used) : '—'}
          hint={orgCompute ? `of ${fmtSeconds(orgCompute.limit)} GPU-seconds` : 'no compute limit'}
          loading={!data}
        />
        <KpiTile
          label="Scopes at soft / hard limit"
          icon={AlertTriangle}
          value={`${soft} / ${hard}`}
          tone={hard > 0 ? 'bad' : soft > 0 ? 'warn' : 'neutral'}
          hint={hard > 0 ? 'blocking with 402' : soft > 0 ? 'downgrading models' : 'all within limits'}
          loading={!data}
          className="col-span-2 sm:col-span-1"
        />
      </div>

      {ks ? (
        <GlobalKillPanel
          active={ks.global}
          perm={{ canEngage: canKill, canRelease: role === 'owner', reason: '' }}
          viewer={viewer}
          onDone={() => res.refresh()}
          stoppedCount={killedCount}
        />
      ) : null}

      <Panel
        title="Budget hierarchy"
        description="Org → team → member / agent. Ticks mark the soft (80%) and hard (100%) limit. Select a row for its burn-down."
        isMock={res.isMock}
        flush
        actions={
          <span className="inline-flex items-center gap-1.5 text-2xs text-text-3">
            <span className="size-1.5 rounded-full bg-allow" aria-hidden /> Live
          </span>
        }
      >
        {data ? (
          data.scopes.length ? (
            <BudgetTree
              data={data}
              dimension={dimension}
              window={win}
              now={now}
              viewer={viewer}
              canKillswitch={canKill}
              sponsorOf={sponsorOf}
              memberName={memberName}
              selected={sel?.scope ?? null}
              onSelect={setSelected}
              onRaise={(scope, limit) => setRaise({ scope, limit })}
              onMutated={() => res.refresh()}
            />
          ) : (
            <EmptyState icon="Wallet" title="No budgets configured" hint="Add budgets.limits to config/policy.yaml" />
          )
        ) : res.error ? (
          <EmptyState icon="AlertTriangle" title="Budgets unavailable" hint={res.error.message} />
        ) : (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        )}
      </Panel>

      {sel ? (
        <Panel
          title={
            <span className="flex items-center gap-2">
              Burn-down · {sel.name} <span className="hidden font-mono text-xs font-normal text-text-3 sm:inline">{sel.scope}</span>
            </span>
          }
          description={`${dimensionLabel(chartDim)} over the last 24 h with a linear forecast to the end of the day`}
          isMock={res.isMock}
          actions={<BudgetStatePill state={sel.state} />}
        >
          <div className={cn('grid gap-4', sel.limits.length > 0 && 'lg:grid-cols-[1fr_260px]')}>
            <BudgetHistoryChart scope={sel.scope} dimension={chartDim} />
            {sel.limits.length > 0 ? (
              <div className="space-y-2">
                <div className="text-xs font-medium text-text-2">Limits on {scopeLabel(sel.scope)}</div>
                {sel.limits.map((l) => (
                  <button
                    type="button"
                    key={`${l.window}|${l.dimension}`}
                    onClick={() => setRaise({ scope: sel, limit: l })}
                    className="flex min-h-9 w-full items-center justify-between gap-2 rounded-sm border border-border bg-surface-1 px-2.5 py-1.5 text-left text-xs transition-colors duration-100 hover:border-border-strong md:min-h-0"
                    title="Request a change to this limit"
                  >
                    <span className="text-text-2">
                      {windowLabel(l.window)} · {dimensionLabel(l.dimension)}
                    </span>
                    <span className="font-mono tabular text-text-1">
                      {fmtDimension(l.dimension, l.used)} <span className="text-text-3">/ {fmtDimension(l.dimension, l.limit)}</span>
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </Panel>
      ) : null}

      <RaiseDialog
        scope={raise?.scope ?? null}
        initial={raise?.limit ?? null}
        open={raise !== null}
        onOpenChange={(o) => !o && setRaise(null)}
        viewer={viewer}
        role={role}
        onDone={() => res.refresh()}
      />
    </div>
  );
}
