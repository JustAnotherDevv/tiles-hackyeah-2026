// One inbox row: kind icon, title, approver badge, requester, amount, countdown, two-person, lock.
// Owner: B18-dashboard-gov-approvals.
import { displayTitle } from '@/components/governance/lib/format-gov';
import { motion } from 'framer-motion';
import { Lock } from 'lucide-react';
import { forwardRef } from 'react';
import type { ApprovalRequest } from '@/api/types';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';
import { ApproverBadge } from '../ApproverBadge';
import { ExpiryCountdown } from '../ExpiryCountdown';
import type { Directory } from '../hooks';
import { approvalIcon, firstName, fmtMoney, statusMeta } from '../lib/format-gov';
import { TwoPersonProgress } from '../TwoPersonProgress';
import type { VoteState } from './util';

const TONE: Record<string, string> = {
  approval: 'text-approval border-approval/30 bg-approval/10',
  allow: 'text-allow border-allow/30 bg-allow/10',
  block: 'text-block border-block/30 bg-block/10',
  log: 'text-log border-log/30 bg-log/10',
};

export interface ApprovalListItemProps {
  req: ApprovalRequest;
  vote: VoteState;
  selected: boolean;
  fresh: boolean;
  dir: Directory;
  onSelect: (id: string) => void;
}

export const ApprovalListItem = forwardRef<HTMLDivElement, ApprovalListItemProps>(function ApprovalListItem({ req, vote, selected, fresh, dir, onSelect }, ref) {
  const Icon = resolveIcon(approvalIcon(req.kind, req.action_type));
  const pending = req.status === 'pending';
  const who = req.requester.agent_id ?? firstName(dir.memberById.get(req.requester.member_id ?? '')?.name ?? req.requester.display_name ?? req.requester.member_id ?? '');
  const st = statusMeta(req.status);
  const locked = pending && !vote.ok;
  return (
    <motion.div
      ref={ref}
      layout="position"
      initial={{ opacity: 0, y: -10, height: 0 }}
      animate={{ opacity: 1, y: 0, height: 'auto' }}
      exit={{ opacity: 0, x: 24, height: 0, transition: { duration: 0.32, ease: [0.65, 0, 0.35, 1] } }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="overflow-hidden"
    >
      <div
        role="button"
        tabIndex={0}
        data-approval-id={req.id}
        onClick={() => onSelect(req.id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect(req.id);
          }
        }}
        className={cn(
          'relative flex cursor-pointer gap-3 border-b border-border-subtle px-4 py-3.5 outline-none transition-colors',
          'hover:bg-white/[0.018] focus-visible:bg-surface-2',
          selected && 'bg-surface-2 before:absolute before:inset-y-2.5 before:left-0 before:w-0.5 before:rounded-full before:bg-accent-fg',
          fresh && 'animate-row-in',
        )}
      >
        <div
          className={cn(
            'grid size-8 shrink-0 place-items-center rounded-[9px] border',
            pending && vote.ok ? 'border-approval/35 bg-approval/10 text-approval' : 'border-border bg-surface-2 text-text-2',
          )}
        >
          <Icon className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className={cn('text-[13px] font-medium leading-[18px]', locked ? 'text-text-2' : 'text-text-1')}>{displayTitle(req.title)}</div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-3">
            {pending ? (
              <ApproverBadge level={req.required_role} size="sm" />
            ) : (
              <span className={cn('inline-flex h-[18px] items-center rounded-full border px-1.5 text-2xs font-medium', TONE[st.tone])}>{st.label}</span>
            )}
            <span className={cn('max-w-[180px] truncate', req.requester.agent_id && 'font-mono text-[11.5px]')}>{who}</span>
            {req.amount_usd !== null ? <span className="tabular text-text-2">{fmtMoney(req.amount_usd)}</span> : null}
            {pending ? <ExpiryCountdown expiresAt={req.expires_at} /> : null}
            {req.two_person ? <TwoPersonProgress votes={req.votes} /> : null}
          </div>
        </div>
        {locked ? (
          <span className="mt-0.5 text-text-4" title={vote.reason ?? 'Locked for this role'}>
            <Lock className="size-3.5" />
          </span>
        ) : pending && vote.ok ? (
          <span className="mt-1 size-2 shrink-0 rounded-full bg-approval shadow-[0_0_0_3px_rgba(139,92,246,.18)]" title="You can act on this" />
        ) : null}
      </div>
    </motion.div>
  );
});
