// Animated inbox list (new ids slide in, decided ones slide out). Owner: B18-dashboard-gov-approvals.
import { AnimatePresence } from 'framer-motion';
import { CheckCheck } from '@/components/icons';
import type { ReactNode } from 'react';
import type { ApprovalRequest } from '@/api/types';
import { EmptyState } from '@/components/shell';
import { Skeleton } from '@/components/ui/skeleton';
import type { Directory } from '../hooks';
import { requesterKey } from '../lib/approval-review';
import { ApprovalListItem } from './ApprovalListItem';
import type { VoteState } from './util';

export function ApprovalList({
  items,
  votes,
  selectedId,
  freshIds,
  dir,
  loading,
  empty,
  onSelect,
  flooded,
}: {
  items: ApprovalRequest[];
  votes: Map<string, VoteState>;
  selectedId: string | null;
  freshIds: Set<string>;
  dir: Directory;
  loading: boolean;
  empty: ReactNode;
  onSelect: (id: string) => void;
  /** requesterKey()s currently flooding the inbox (ASI09). */
  flooded?: Set<string>;
}) {
  if (loading && items.length === 0) {
    return (
      <div className="space-y-px">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex gap-3 border-b border-border-subtle px-4 py-3.5">
            <Skeleton className="size-8 rounded-[9px]" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-3.5 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="flex flex-col">
      <AnimatePresence initial={false} mode="popLayout">
        {items.map((req) => (
          <ApprovalListItem
            key={req.id}
            req={req}
            vote={votes.get(req.id) ?? { ok: false, reason: null, source: 'client', code: 'not_pending' }}
            selected={req.id === selectedId}
            fresh={freshIds.has(req.id)}
            dir={dir}
            onSelect={onSelect}
            flooded={flooded?.has(requesterKey(req)) ?? false}
          />
        ))}
      </AnimatePresence>
      {items.length === 0 ? <EmptyState icon={CheckCheck} title={empty} hint="New requests slide in here in real time." /> : null}
    </div>
  );
}
