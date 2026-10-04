// Members tab: avatar + name/email, role (RoleChangeMenu), teams, title, sponsored agents, pending
// governed changes (meta.pending_changes, CONTRACTS A-37) and the active toggle. Owner: B18.
import { Bot, Clock } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { Member } from '@/api/types';
import { Switch } from '@/components/ui/switch';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { teamColor } from '@/lib/colors';
import type { ViewRole } from '@/lib/page';
import { cn } from '@/lib/utils';
import { MemberAvatar } from '../MemberAvatar';
import { memberTeams, type Gate } from './org-actions';
import { RoleChangeMenu } from './RoleChangeMenu';

interface PendingChip {
  approval_id: string;
  op: string;
  to: string | null;
  required_role: string;
}

function pendingOf(m: Member): PendingChip[] {
  const p = m.meta?.pending_changes;
  return Array.isArray(p) ? (p as PendingChip[]) : [];
}

const TH = 'px-3 py-2 text-left text-2xs font-medium uppercase tracking-wider text-text-3';

export function MembersTable({
  members,
  viewerId,
  viewerRole,
  manageGate,
  busyId,
  onRole,
  onActive,
}: {
  members: Member[];
  viewerId: string | null;
  viewerRole: ViewRole;
  manageGate: Gate;
  busyId: string | null;
  onRole: (m: Member, role: Member['role']) => void;
  onActive: (m: Member, active: boolean) => void;
}) {
  const ownerCount = members.filter((m) => m.role === 'owner' && m.active).length;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] border-collapse text-[12.5px]">
        <thead className="border-b border-border-subtle">
          <tr>
            <th className={cn(TH, 'pl-4')}>Member</th>
            <th className={TH}>Role</th>
            <th className={TH}>Teams</th>
            <th className={TH}>Title</th>
            <th className={TH}>Sponsor of</th>
            <th className={cn(TH, 'pr-4 text-right')}>Active</th>
          </tr>
        </thead>
        <tbody>
          {members.map((m) => {
            const me = m.id === viewerId;
            const pending = pendingOf(m);
            const activeLocked = !manageGate.ok
              ? manageGate.reason
              : me
                ? 'You cannot deactivate yourself.'
                : m.role === 'owner' && viewerRole !== 'owner'
                  ? 'Only owners can deactivate an owner.'
                  : null;
            return (
              <tr
                key={m.id}
                className={cn('border-b border-border-subtle/60 transition-colors last:border-0 hover:bg-surface-2/40', me && 'bg-allow/[0.04]', !m.active && 'opacity-55')}
              >
                <td className="py-2 pl-4 pr-3">
                  <div className="flex items-center gap-2.5">
                    <MemberAvatar member={m} size="md" highlight={me} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 font-medium text-text-1">
                        {m.name}
                        {me ? <span className="rounded-full bg-allow/15 px-1.5 text-2xs font-medium text-allow">you</span> : null}
                      </div>
                      <div className="truncate font-mono text-[11px] text-text-3">{m.email ?? m.id}</div>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <RoleChangeMenu
                      target={m}
                      viewerRole={viewerRole}
                      viewerId={viewerId}
                      manageGate={manageGate}
                      ownerCount={ownerCount}
                      busy={busyId === m.id}
                      onChange={(r) => onRole(m, r)}
                    />
                    {pending.map((p) => (
                      <Link
                        key={p.approval_id}
                        to={`/governance/approvals?id=${encodeURIComponent(p.approval_id)}`}
                        className="inline-flex h-5 items-center gap-1 rounded-full border border-approval/35 bg-approval/10 px-1.5 text-2xs text-approval hover:bg-approval/20"
                        title={`Pending ${p.op}${p.to ? ` → ${p.to}` : ''} · needs ${p.required_role} · open approval`}
                      >
                        <Clock className="size-2.5" />
                        {p.to ? `→ ${p.to}` : p.op} · needs {p.required_role}
                      </Link>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {memberTeams(m).map((t) => (
                      <span key={t} className="inline-flex h-5 items-center gap-1 rounded-xs border border-border bg-surface-2 px-1.5 text-[11px] text-text-2">
                        <span className="size-1.5 rounded-full" style={{ background: teamColor(t) }} />
                        {t}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="max-w-[220px] truncate px-3 py-2 text-text-2" title={m.title ?? undefined}>
                  {m.title ?? '—'}
                </td>
                <td className="px-3 py-2">
                  {(m.agents ?? []).length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {(m.agents ?? []).map((a) => (
                        <span
                          key={a}
                          className="inline-flex h-5 items-center gap-1 rounded-xs border border-role-agent/25 bg-role-agent/5 px-1.5 font-mono text-[10.5px] text-text-2"
                        >
                          <Bot className="size-3 text-role-agent" />
                          {a}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className="text-text-4">—</span>
                  )}
                </td>
                <td className="py-2 pl-3 pr-4 text-right">
                  {activeLocked ? (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="inline-flex cursor-not-allowed" tabIndex={0}>
                          <Switch checked={m.active} disabled aria-label={`${m.name} active`} />
                        </span>
                      </TooltipTrigger>
                      <TooltipContent side="left">{activeLocked}</TooltipContent>
                    </Tooltip>
                  ) : (
                    <Switch checked={m.active} disabled={busyId === m.id} onCheckedChange={(v) => onActive(m, v)} aria-label={`${m.name} active`} />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
