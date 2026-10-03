// Agents tab: service identities with their sponsor (who fills `self` approval slots), allowed
// models, destination ceiling, status, spend today, last seen, and an admin-only Deactivate /
// Reactivate action (PATCH /api/agents/{id}). Owner: B18-dashboard-gov-approvals.
import { Bot, Code2, Plug, Power, PowerOff, Terminal, Workflow } from 'lucide-react';
import type { Agent, Member } from '@/api/types';
import { DestBadge, TimeAgo } from '@/components/shell';
import { teamColor } from '@/lib/colors';
import { cn } from '@/lib/utils';
import { fmtMoney } from '../lib/format-gov';
import { LockedAction } from '../LockedAction';
import { MemberAvatar } from '../MemberAvatar';
import type { Gate } from './org-actions';

const KIND_ICON = {
  'claude-code': Terminal,
  scripted: Workflow,
  sdk: Code2,
  'mcp-client': Plug,
  other: Bot,
} as const;

function statusOf(a: Agent): 'active' | 'killed' | 'idle' | 'disabled' {
  if (!a.active) return 'disabled';
  return a.status ?? 'active';
}

const STATUS_STYLE: Record<ReturnType<typeof statusOf>, { label: string; cls: string; dot: string }> = {
  active: {
    label: 'Active',
    cls: 'border-allow/30 bg-allow/10 text-allow',
    dot: 'bg-allow animate-pulse',
  },
  idle: {
    label: 'Idle',
    cls: 'border-border-strong bg-surface-2 text-text-2',
    dot: 'bg-text-3',
  },
  killed: {
    label: 'Killed',
    cls: 'border-block/40 bg-block/15 text-block',
    dot: 'bg-block',
  },
  disabled: {
    label: 'Deactivated',
    cls: 'border-block/30 bg-block/5 text-block',
    dot: 'bg-block/60',
  },
};

const TH = 'px-3 py-2 text-left text-2xs font-medium uppercase tracking-wider text-text-3';

export function AgentsTable({
  agents,
  memberById,
  viewerId,
  manageGate,
  busyId,
  onActive,
}: {
  agents: Agent[];
  memberById: Map<string, Member>;
  viewerId: string | null;
  manageGate: Gate;
  busyId: string | null;
  onActive: (a: Agent, active: boolean) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[980px] border-collapse text-[12.5px]">
        <thead className="border-b border-border-subtle">
          <tr>
            <th className={cn(TH, 'pl-4')}>Agent</th>
            <th className={TH}>Sponsor</th>
            <th className={TH}>Allowed models</th>
            <th className={TH}>Max destination</th>
            <th className={TH}>Status</th>
            <th className={cn(TH, 'text-right')}>Spend today</th>
            <th className={TH}>Last seen</th>
            <th className={cn(TH, 'pr-4 text-right')}>Action</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((a) => {
            const Icon = KIND_ICON[a.kind] ?? Bot;
            const sponsor = a.owner_member_id ? memberById.get(a.owner_member_id) : undefined;
            const st = statusOf(a);
            const s = STATUS_STYLE[st];
            const models = a.allowed_models ?? [];
            return (
              <tr key={a.id} className={cn('border-b border-border-subtle/60 transition-colors last:border-0 hover:bg-surface-2/40', st === 'disabled' && 'opacity-60')}>
                <td className="py-2 pl-4 pr-3">
                  <div className="flex items-center gap-2.5">
                    <span className="grid size-8 shrink-0 place-items-center rounded-md border border-role-agent/30 bg-role-agent/10 text-role-agent">
                      <Icon className="size-4" />
                    </span>
                    <div className="min-w-0">
                      <div className="font-mono text-[12px] font-medium text-text-1">{a.id}</div>
                      <div className="flex items-center gap-1.5 text-[11px] text-text-3">
                        <span className="size-1.5 rounded-full" style={{ background: teamColor(a.team_id) }} />
                        {a.team_id ?? '—'} · {a.kind}
                        {a.profile ? <span className="rounded-xs bg-surface-2 px-1 font-mono text-[10px]">{a.profile}</span> : null}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2">
                  {sponsor ? (
                    <div
                      className="flex items-center gap-2"
                      title={`${sponsor.name} fills this agent's "self" approval slots — and is excluded from its admin/owner approvals (separation of duties)`}
                    >
                      <MemberAvatar member={sponsor} size="sm" highlight={sponsor.id === viewerId} />
                      <div className="min-w-0">
                        <div className="truncate text-text-1">
                          {sponsor.name}
                          {sponsor.id === viewerId ? <span className="ml-1 text-2xs font-medium text-allow">you</span> : null}
                        </div>
                        <div className="text-2xs text-text-3">
                          fills <span className="font-mono text-allow">self</span> slots
                        </div>
                      </div>
                    </div>
                  ) : (
                    <span className="text-text-4">—</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="flex max-w-[260px] flex-wrap gap-1">
                    {models.slice(0, 3).map((m) => (
                      <span key={m} className="inline-flex h-5 items-center rounded-xs border border-border bg-surface-2 px-1.5 font-mono text-[10.5px] text-text-2">
                        {m}
                      </span>
                    ))}
                    {models.length > 3 ? (
                      <span className="inline-flex h-5 items-center rounded-xs px-1 text-[10.5px] text-text-3" title={models.slice(3).join(', ')}>
                        +{models.length - 3}
                      </span>
                    ) : null}
                  </div>
                </td>
                <td className="px-3 py-2">{a.max_destination ? <DestBadge dest={a.max_destination} /> : <span className="text-text-4">—</span>}</td>
                <td className="px-3 py-2">
                  <span className={cn('inline-flex h-5 items-center gap-1.5 rounded-full border px-2 text-xs font-medium', s.cls)}>
                    <span className={cn('size-1.5 rounded-full', s.dot)} />
                    {s.label}
                  </span>
                </td>
                <td className="px-3 py-2 text-right tabular text-text-1">{typeof a.spend_today_usd === 'number' ? fmtMoney(a.spend_today_usd) : '—'}</td>
                <td className="px-3 py-2 text-xs">{a.last_seen ? <TimeAgo ts={a.last_seen} /> : <span className="text-text-4">never</span>}</td>
                <td className="py-2 pl-3 pr-4 text-right">
                  <LockedAction
                    locked={!manageGate.ok}
                    reason={manageGate.reason}
                    size="xs"
                    variant={a.active ? 'danger-ghost' : 'secondary'}
                    disabled={busyId === a.id}
                    onClick={() => onActive(a, !a.active)}
                    wrapperClassName="justify-end"
                  >
                    {manageGate.ok ? a.active ? <PowerOff className="size-3" /> : <Power className="size-3" /> : null}
                    {a.active ? 'Deactivate' : 'Reactivate'}
                  </LockedAction>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
