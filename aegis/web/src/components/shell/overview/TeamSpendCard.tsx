// Row D (4) — per-team daily USD as bullet bars with state badges (ok / downgrading / blocking / killed).
import { Link } from 'react-router-dom';
import { BUDGET_STATE_COLORS, teamColor } from '@/lib/colors';
import { fmtPct, fmtUsd } from '@/lib/format';
import { cn } from '@/lib/utils';
import { EmptyState } from '../EmptyState';
import { Panel } from '../Panel';
import { UsageBar } from '../UsageBar';
import { useShellState } from '../shellStore';
import type { OverviewData } from './useOverviewData';

export function TeamSpendCard({ d, className }: { d: OverviewData; className?: string }) {
  const kill = useShellState((s) => s.kill);
  const teams = (d.budgets.data?.scopes ?? []).filter((s) => s.scope_type === 'team');
  return (
    <Panel
      className={className}
      title="Spend by team"
      description="Daily USD budgets · soft 80 % downgrades to local models, hard 100 % blocks"
      isMock={d.budgets.isMock}
      actions={
        <Link to="/governance/budgets" className="text-[12px] text-text-3 hover:text-text-1">
          Budgets →
        </Link>
      }
    >
      {teams.length === 0 ? (
        <EmptyState icon="Wallet" title="No team budgets configured" />
      ) : (
        <div className="flex flex-col gap-3.5 pt-1">
          {teams.map((t) => {
            const lim = t.limits.find((l) => l.dimension === 'usd' && l.window === 'day') ?? t.limits[0];
            const id = t.scope.replace(/^team:/, '');
            const killed = Boolean(kill?.global || kill?.teams.includes(id));
            const state = killed ? 'killed' : (lim?.state ?? t.state);
            const sc = BUDGET_STATE_COLORS[state];
            return (
              <div key={t.scope} className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2 text-[12.5px]">
                  <span className="size-2 rounded-[3px]" style={{ background: teamColor(id) }} />
                  <span className="font-medium text-text-1">{t.name}</span>
                  <span className={cn('rounded-full border px-1.5 text-[10.5px] font-medium leading-4', sc.className)}>{sc.label}</span>
                  <span className="ml-auto tabular text-text-2">
                    {fmtUsd(lim?.used ?? 0, { dp: 2 })}
                    <span className="text-text-4"> / {fmtUsd(lim?.limit ?? 0, { dp: 0 })}</span>
                  </span>
                  <span className="w-10 text-right tabular text-[11.5px] text-text-3">{fmtPct(lim?.pct ?? 0)}</span>
                </div>
                <UsageBar pct={lim?.pct ?? 0} state={state} size="sm" />
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
