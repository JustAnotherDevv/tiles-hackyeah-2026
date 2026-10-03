// "<agent> on behalf of <sponsor> · Team · 2 min ago" or "<member> (role) · Team · …".
// Owner: B18-dashboard-gov-approvals.
import type { ApprovalRequest } from '@/api/types';
import { RoleBadge, TimeAgo } from '@/components/shell';
import { cn } from '@/lib/utils';
import type { Directory } from './hooks';
import { MemberAvatar } from './MemberAvatar';

export function RequesterLine({ req, dir, className, showTime = true }: { req: ApprovalRequest; dir: Directory; className?: string; showTime?: boolean }) {
  const r = req.requester;
  const agentId = r.agent_id;
  const sponsorId = r.member_id ?? (agentId ? dir.agentById.get(agentId)?.owner_member_id : null) ?? null;
  const sponsor = sponsorId ? dir.memberById.get(sponsorId) : undefined;
  const teamId = r.team_id ?? req.team_id;
  const team = teamId ? (teamId.charAt(0).toUpperCase() + teamId.slice(1)) : null;
  return (
    <div className={cn('flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-text-3', className)}>
      {agentId ? (
        <>
          <MemberAvatar agent name={agentId} size="sm" showName className="font-medium text-text-1" />
          <span>on behalf of</span>
          <MemberAvatar member={sponsor} name={sponsor?.name ?? sponsorId} size="xs" showName className="text-text-2" />
        </>
      ) : (
        <>
          <MemberAvatar member={sponsor} name={r.display_name ?? sponsorId} size="sm" showName className="font-medium text-text-1" />
          {sponsor ? <RoleBadge role={sponsor.role} /> : r.role !== 'agent' ? <RoleBadge role={r.role} /> : null}
        </>
      )}
      {team ? (
        <>
          <span className="text-text-4">·</span>
          <span>{team}</span>
        </>
      ) : null}
      {showTime ? (
        <>
          <span className="text-text-4">·</span>
          <span>
            requested <TimeAgo ts={req.created_at} />
          </span>
        </>
      ) : null}
    </div>
  );
}
