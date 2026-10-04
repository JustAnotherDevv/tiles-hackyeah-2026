// Budgets (UIG-03 + kill switch half of UIG-10 + UIG-15 chart), flows F5/F6: org → team → member/agent
// hierarchy with live usage bars (SSE budget.updated/threshold + 5 s polling), "Request increase" with
// the live approval route → POST /api/budgets/raise → ApplyResult, kill switch per scope + global.
// Owner: B19-dashboard-gov-policy.
import { Activity, AlertTriangle, Cpu, LineChart, Power, Wallet } from 'lucide-react';
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
  { value: 'compute_s', label: 'Compute s' },
  { value: 'spend_usd', label: 'Spend $' },
];
const WINDOWS: { value: BudgetWindow; label: string }[] = [
  { value: 'day', label: 'Day' },
  { value: 'month', label: 'Month' },
  { value: 'session', label: 'Session' },
];

export default function BudgetsPage() {
  const { viewerId, role, member } = useViewer();
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
        subtitle="Hierarchical limits enforced inline by BUD-01 — soft limit downgrades the model, hard limit answers 402, the kill switch answers 429."
        badge={res.isMock ? <MockBadge /> : null}
        actions={<PersonaSwitcher />}
      />

      <div className="flex flex-wrap items-center gap-3">
        <Segmented value={dimension} options={DIMS} onChange={setDimension} ariaLabel="Dimension" />
        <Segmented value={win} options={WINDOWS} onChange={setWin} ariaLabel="Window" />
        <span className="text-xs text-text-3">
          Viewing as <span className="text-text-1">{member?.name ?? '—'}</span> ({role}) · {canKill ? 'kill switch available' : 'kill switch locked for your role'}
        </span>
        {data ? <span className="ml-auto text-2xs text-text-4">pricing {data.pricing_version}</span> : null}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <div className="col-span-2 flex items-center gap-4 rounded-xl border border-border bg-surface-1 p-4 lg:col-span-1">
          {orgDay ? (
            <Gauge
              value={Math.min(orgDay.pct, 100)}
              max={100}
              label="Org spend today"
              sublabel="of limit"
              tone={orgDay.pct >= 100 ? 'bad' : orgDay.pct >= 80 ? 'warn' : 'neutral'}
              format={() => `${Math.round(orgDay.pct)}%`}
              size={76}
            />
          ) : (
            <Skeleton className="size-[76px] rounded-full" />
          )}
          <div className="min-w-0">
            <div className="text-2xs font-medium uppercase tracking-wider text-text-3">Org spend today</div>
            <div className="mt-0.5 font-mono text-lg font-semibold text-text-1 tabular">{orgDay ? fmtDimension('usd', orgDay.used) : '—'}</div>
            <div className="text-xs text-text-3 tabular">of {orgDay ? fmtDimension('usd', orgDay.limit) : '—'}</div>
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
          label="Scopes at soft / hard"
          icon={AlertTriangle}
          value={`${soft} / ${hard}`}
          tone={hard > 0 ? 'bad' : soft > 0 ? 'warn' : 'good'}
          hint={hard > 0 ? 'blocking with 402' : soft > 0 ? 'downgrading models' : 'all healthy'}
          loading={!data}
        />
        <KpiTile
          label="Kill switch"
          icon={Power}
          value={ks?.global ? 'GLOBAL' : killedCount ? `${killedCount} killed` : 'off'}
          tone={ks?.global || killedCount ? 'bad' : 'good'}
          hint={ks ? [...ks.agents.map((a) => `agent:${a}`), ...ks.teams.map((t) => `team:${t}`)].slice(0, 2).join(', ') || 'nothing stopped' : undefined}
          loading={!data}
        />
      </div>

      {ks ? (
        <GlobalKillPanel
          active={ks.global}
          perm={{ canEngage: canKill, canRelease: role === 'owner', reason: '' }}
          viewer={viewer}
          onDone={() => res.refresh()}
        />
      ) : null}

      <Panel
        title="Budget hierarchy"
        description="Org → team → member / agent. Bars move live; 80 % marks the soft limit, the bright mark the hard limit. Click a row for its burn-down."
        isMock={res.isMock}
        flush
        actions={
          <span className="inline-flex items-center gap-1.5 text-2xs text-text-3">
            <Activity className="size-3 text-allow" /> live
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
              Burn-down · {sel.name} <span className="font-mono text-xs font-normal text-text-3">{sel.scope}</span>
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
                <div className="text-2xs font-medium uppercase tracking-wider text-text-3">Limits on {scopeLabel(sel.scope)}</div>
                {sel.limits.map((l) => (
                  <button
                    type="button"
                    key={`${l.window}|${l.dimension}`}
                    onClick={() => setRaise({ scope: sel, limit: l })}
                    className="flex w-full items-center justify-between rounded-md border border-border bg-surface-1 px-2.5 py-1.5 text-left text-xs hover:border-border-strong"
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
