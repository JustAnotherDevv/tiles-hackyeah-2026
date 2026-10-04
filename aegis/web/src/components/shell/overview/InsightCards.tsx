// Row E — top controls fired · data protected · local vs remote vs third-party · top agents.
import { Bot } from '@/components/icons';
import { BarList } from '@/components/charts/BarList';
import type { DestClass } from '@/api/types';
import { ACTION_COLORS, DEST_COLORS } from '@/lib/colors';
import { fmtNum, fmtPct, fmtUsd } from '@/lib/format';
import { resolveIcon } from '@/lib/icons';
import { EmptyState } from '../EmptyState';
import { Panel } from '../Panel';
import type { OverviewData } from './useOverviewData';

export function TopControlsCard({ d, className }: { d: OverviewData; className?: string }) {
  const items = (d.view?.by_control ?? [])
    .slice()
    .sort((a, b) => b.hits - a.hits)
    .map((c) => ({
      key: c.control_id,
      label: <span className="font-mono text-[12px]">{c.control_id}</span>,
      hint: `${c.family} · ${fmtNum(c.blocks)} blocks · ${fmtNum(c.redacts)} redacts`,
      value: c.hits,
      color: c.blocks >= c.redacts && c.blocks > 0 ? ACTION_COLORS.block.chart : c.redacts > 0 ? ACTION_COLORS.redact.chart : ACTION_COLORS.log.chart,
      href: '/security/coverage',
    }));
  return (
    <Panel className={className} title="Top controls fired" description="Bar colour = dominant outcome" isMock={d.stats.isMock}>
      <BarList items={items} limit={6} valueFormat={(n) => fmtNum(n, { compact: true })} labelWidth={150} emptyText="No controls fired yet" />
    </Panel>
  );
}

export function DataProtectedCard({ d, className }: { d: OverviewData; className?: string }) {
  const ents = (d.view?.by_entity ?? []).slice().sort((a, b) => b.count - a.count);
  return (
    <Panel
      className={className}
      title="Data protected"
      description={
        <>
          <span className="tabular text-redact">{fmtNum(d.view?.entitiesTotal ?? 0)}</span> values kept on this machine
        </>
      }
      isMock={d.stats.isMock}
    >
      <BarList
        items={ents.map((e) => ({ key: e.entity, label: <span className="font-mono text-[12px]">{e.entity}</span>, value: e.count, color: ACTION_COLORS.redact.chart }))}
        limit={6}
        valueFormat={(n) => fmtNum(n, { compact: true })}
        labelWidth={130}
        emptyText="Nothing redacted yet"
      />
    </Panel>
  );
}

export function DestinationsCard({ d, className }: { d: OverviewData; className?: string }) {
  const order: DestClass[] = ['local', 'remote', 'third_party'];
  const rows = order.map((c) => d.view?.by_destination.find((x) => x.dest_class === c) ?? { dest_class: c, count: 0, redactions: 0 });
  const total = rows.reduce((a, r) => a + r.count, 0);
  const tint: Record<DestClass, string> = { local: '#1E9F68', remote: '#3B78E6', third_party: '#0891B2' };
  return (
    <Panel className={className} title="Where traffic went" description="Local · remote · third-party, with redactions" isMock={d.stats.isMock}>
      <div className="mb-4 mt-1 flex h-2.5 overflow-hidden rounded-full bg-surface-2">
        {rows.map((r) => (
          <div key={r.dest_class} className="h-full transition-[width] duration-700 ease-out first:rounded-l-full last:rounded-r-full" style={{ width: total ? `${(r.count / total) * 100}%` : '0%', background: tint[r.dest_class], marginRight: 2 }} />
        ))}
      </div>
      <div className="grid grid-cols-3 gap-3">
        {rows.map((r) => {
          const Icon = resolveIcon(DEST_COLORS[r.dest_class].icon);
          return (
            <div key={r.dest_class} className="flex min-w-0 flex-col gap-1">
              <div className="flex items-center gap-1.5 whitespace-nowrap text-[11.5px] text-text-3">
                <span className="size-2 shrink-0 rounded-[3px]" style={{ background: tint[r.dest_class] }} />
                <Icon className="size-3.5 shrink-0 max-[1600px]:hidden" />
                <span className="truncate">{r.dest_class === 'third_party' ? '3rd party' : DEST_COLORS[r.dest_class].label}</span>
              </div>
              <div className="text-lg font-semibold tabular tracking-[-0.02em] text-text-1">{fmtNum(r.count, { compact: true })}</div>
              <div className="text-[11.5px] text-text-3">
                {fmtPct(total ? (r.count / total) * 100 : 0)} · <span className="text-redact">{fmtNum(r.redactions, { compact: true })}</span> redacted
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

export function TopAgentsCard({ d, className }: { d: OverviewData; className?: string }) {
  const agents = (d.view?.top_agents ?? []).slice().sort((a, b) => b.requests - a.requests).slice(0, 5);
  return (
    <Panel className={className} title="Top agents" description="Requests · blocks · spend" isMock={d.stats.isMock} flush>
      {agents.length === 0 ? (
        <EmptyState icon="Bot" title="No agent traffic yet" />
      ) : (
        <div className="mt-2 border-t border-border-subtle">
          {agents.map((a) => (
            <div key={a.agent_id} className="flex items-center gap-1.5 border-b border-border-subtle px-4 py-2 text-[12.5px] last:border-b-0">
              <Bot className="size-3.5 shrink-0 text-[#2DD4BF]" />
              <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-text-1" title={a.agent_id}>
                {a.agent_id.split('@')[0]}
              </span>
              <span className="w-9 text-right tabular text-text-2" title="requests">{fmtNum(a.requests, { compact: true })}</span>
              <span className="w-8 text-right tabular text-block" title="blocks">{fmtNum(a.blocks, { compact: true })}</span>
              <span className="w-[52px] text-right tabular text-text-2" title="spend today">{fmtUsd(a.spend_usd, { dp: 2 })}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
