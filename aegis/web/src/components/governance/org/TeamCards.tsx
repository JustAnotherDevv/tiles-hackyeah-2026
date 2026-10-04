// Teams tab: one card per team — colour rail, description, data ceiling / default destination,
// members (role-coloured avatars) and the agents they sponsor. Owner: B18-dashboard-gov-approvals.
import { Bot, Crown, Users } from '@/components/icons';
import type { Agent, DestClass, Member, OrgResponse } from '@/api/types';
import { DestBadge, RoleBadge } from '@/components/shell';
import { teamColor } from '@/lib/colors';
import { cn } from '@/lib/utils';
import { firstName } from '../lib/format-gov';
import { MemberAvatar } from '../MemberAvatar';
import { memberTeams } from './org-actions';

type TeamRow = OrgResponse['teams'][number];

const ROLE_SORT: Record<Member['role'], number> = {
  owner: 0,
  admin: 1,
  member: 2,
};

export function TeamCards({ teams, members, agents, viewerId }: { teams: TeamRow[]; members: Member[]; agents: Agent[]; viewerId: string | null }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {teams.map((t) => {
        const color = teamColor(t.id);
        const ms = members.filter((m) => memberTeams(m).includes(t.id)).sort((a, b) => ROLE_SORT[a.role] - ROLE_SORT[b.role] || a.name.localeCompare(b.name));
        const ags = agents.filter((a) => a.team_id === t.id);
        const meta = (t.meta ?? {}) as {
          lead?: string;
          data_ceiling?: string;
          default_destination?: DestClass;
        };
        const lead = meta.lead ? members.find((m) => m.id === meta.lead) : undefined;
        return (
          <section key={t.id} className="min-w-0 overflow-hidden rounded-lg border border-border bg-card shadow-card">
            <div className="space-y-3 px-4 pb-4 pt-3.5">
              <div className="flex items-start gap-2.5">
                <span className="mt-[5px] size-2 shrink-0 rounded-[2px]" style={{ background: color }} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2">
                    <h3 className="text-sm font-semibold text-text-1">{t.name}</h3>
                    <span className="font-mono text-2xs text-text-4">team:{t.id}</span>
                  </div>
                  {t.description ? <p className="mt-0.5 text-xs leading-[17px] text-text-3">{t.description}</p> : null}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-1.5 text-2xs text-text-3">
                <span className="inline-flex h-5 items-center gap-1 rounded-xs border border-border bg-surface-2 px-1.5">
                  <Users className="size-3" /> <span className="tabular text-text-2">{t.member_count}</span> {t.member_count === 1 ? 'member' : 'members'}
                </span>
                <span className="inline-flex h-5 items-center gap-1 rounded-xs border border-border bg-surface-2 px-1.5">
                  <Bot className="size-3" /> <span className="tabular text-text-2">{t.agent_count}</span> {t.agent_count === 1 ? 'agent' : 'agents'}
                </span>
                {meta.data_ceiling ? (
                  <span
                    className="inline-flex h-5 items-center rounded-xs border border-border bg-surface-2 px-1.5 font-mono text-[10.5px] text-text-2"
                    title="Highest data class this team may handle"
                  >
                    ≤ {meta.data_ceiling}
                  </span>
                ) : null}
                {meta.default_destination ? <DestBadge dest={meta.default_destination} /> : null}
                {lead ? (
                  <span className="ml-auto inline-flex items-center gap-1">
                    <Crown className="size-3" /> lead {firstName(lead.name)}
                  </span>
                ) : null}
              </div>

              <div>
                <div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-text-4">Members</div>
                <div className="flex flex-col gap-1">
                  {ms.map((m) => (
                    <div key={m.id} className={cn('flex items-center gap-2 rounded-sm px-1.5 py-1', m.id === viewerId && 'bg-surface-2')}>
                      <MemberAvatar member={m} size="xs" />
                      <span className="min-w-0 flex-1 truncate text-[12.5px] text-text-2">
                        {m.name}
                        {m.id === viewerId ? <span className="ml-1.5 text-2xs font-medium text-text-3">(you)</span> : null}
                      </span>
                      <RoleBadge role={m.role} className="h-[18px] px-1.5 text-2xs" />
                    </div>
                  ))}
                </div>
              </div>

              {ags.length > 0 ? (
                <div>
                  <div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-text-4">Agents</div>
                  <div className="flex flex-wrap gap-1.5">
                    {ags.map((a) => {
                      const sponsor = members.find((m) => m.id === a.owner_member_id);
                      return (
                        <span
                          key={a.id}
                          className={cn(
                            'inline-flex h-6 max-w-full items-center gap-1.5 truncate rounded-sm border border-border bg-surface-2 px-1.5 font-mono text-[11px] text-text-2',
                            (a.status === 'killed' || !a.active) && 'border-block/30 bg-block/5 text-block line-through',
                          )}
                          title={`${a.name}${sponsor ? ` · sponsored by ${sponsor.name}` : ''}`}
                        >
                          <Bot className="size-3 text-role-agent" />
                          {a.id}
                        </span>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </div>
          </section>
        );
      })}
    </div>
  );
}
