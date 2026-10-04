// n/2 segmented bar + voter avatars (two-person rule). Owner: B18-dashboard-gov-approvals.
import { motion } from 'framer-motion';
import type { ApprovalVote, Member } from '@/api/types';
import { cn } from '@/lib/utils';
import { MemberAvatar } from './MemberAvatar';

export function TwoPersonProgress({
  votes,
  needed = 2,
  memberById,
  showAvatars = false,
  size = 'sm',
  className,
}: {
  votes: ApprovalVote[];
  needed?: number;
  memberById?: Map<string, Member>;
  showAvatars?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}) {
  const approvals = votes.filter((v) => v.decision === 'approve');
  const denied = votes.some((v) => v.decision === 'deny');
  const n = Math.min(approvals.length, needed);
  return (
    <span className={cn('inline-flex items-center gap-1.5', className)} title={`${n} of ${needed} approvals`}>
      <span className="flex gap-1">
        {Array.from({ length: needed }).map((_, i) => (
          <span key={i} className={cn('relative overflow-hidden rounded-full bg-surface-4', size === 'md' ? 'h-1.5 w-9' : 'h-1 w-[22px]')}>
            <motion.span
              className={cn('absolute inset-0 rounded-full', denied ? 'bg-block' : 'bg-allow')}
              initial={false}
              animate={{ scaleX: i < n ? 1 : 0 }}
              style={{ originX: 0 }}
              transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
            />
          </span>
        ))}
      </span>
      <span className={cn('tabular text-text-3', size === 'md' ? 'text-xs' : 'text-2xs')}>
        {n}/{needed}
      </span>
      {showAvatars && approvals.length > 0 ? (
        <span className="flex -space-x-1.5">
          {approvals.map((v) => (
            <MemberAvatar key={v.member_id} member={memberById?.get(v.member_id)} name={v.member_id} size="xs" />
          ))}
        </span>
      ) : null}
    </span>
  );
}
