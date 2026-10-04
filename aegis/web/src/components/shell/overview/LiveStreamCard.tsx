// Row C (4 cols) — 8 newest decisions sliding in with an action-tinted flash; "View all" → /security/live.
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowUpRight } from '@/components/icons';
import { Link, useNavigate } from 'react-router-dom';
import { useLiveDecisions } from '@/api/hooks';
import type { DecisionSummary } from '@/api/types';
import { truncate } from '@/lib/format';
import { useMotionSafe } from '@/lib/motion';
import { cn } from '@/lib/utils';
import { ActionBadge } from '../ActionBadge';
import { DestBadge } from '../DestBadge';
import { EmptyState } from '../EmptyState';
import { IdentityChip } from '../IdentityChip';
import { LiveDot } from '../LiveDot';
import { Panel } from '../Panel';
import { TimeAgo } from '../TimeAgo';

function Row({ d }: { d: DecisionSummary }) {
  const navigate = useNavigate();
  const flash = d.action === 'block' ? 'row-flash-block' : d.action === 'redact' || d.action === 'require_approval' ? 'row-flash' : '';
  return (
    <button
      type="button"
      onClick={() => navigate(`/security/decisions/${encodeURIComponent(d.id)}`)}
      className={cn('flex w-full flex-col gap-1 border-b border-border-subtle px-4 py-2.5 text-left transition-colors last:border-b-0 hover:bg-surface-2/60', flash)}
    >
      <div className="flex min-w-0 items-center gap-2">
        <ActionBadge action={d.action} size="sm" />
        <IdentityChip identity={d.identity} />
        <span className="ml-auto shrink-0 text-[11px] text-text-4">
          <TimeAgo ts={d.ts} short />
        </span>
      </div>
      <div className="flex min-w-0 items-center gap-2 text-[12px]">
        {d.control_id ? <span className="shrink-0 font-mono text-[11px] text-text-2">{d.control_id}</span> : null}
        <span className="min-w-0 truncate text-text-3">{truncate(d.preview || d.reason, 70)}</span>
        <span className="ml-auto shrink-0">
          <DestBadge dest={d.destination} />
        </span>
      </div>
    </button>
  );
}

export function LiveStreamCard({ className }: { className?: string }) {
  const { items, connected } = useLiveDecisions(8);
  const motionOk = useMotionSafe();
  return (
    <Panel
      className={className}
      title="Live decisions"
      leading={<LiveDot paused={!connected} />}
      flush
      actions={
        <Link to="/security/live" className="flex items-center gap-1 text-[12px] text-text-3 hover:text-text-1">
          View all <ArrowUpRight className="size-3.5" />
        </Link>
      }
    >
      <div className="mt-2 h-[268px] overflow-hidden border-t border-border-subtle">
        {items.length === 0 ? (
          <EmptyState icon="Radio" title="No decisions yet" hint={connected ? 'Traffic through the gateway appears here instantly.' : 'Waiting for the live event stream…'} />
        ) : (
          <AnimatePresence initial={false}>
            {items.map((d) => (
              <motion.div
                key={d.id}
                layout={motionOk ? 'position' : false}
                initial={motionOk ? { opacity: 0, y: -4 } : false}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15, ease: [0.16, 1, 0.3, 1] }}
              >
                <Row d={d} />
              </motion.div>
            ))}
          </AnimatePresence>
        )}
      </div>
    </Panel>
  );
}
