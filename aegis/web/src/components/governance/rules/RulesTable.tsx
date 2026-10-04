// One approval rule table (first-match order #, id, description, condition, approver, two-person,
// TTL). The row matched by the route simulator is highlighted and scrolled into view. Owner: B18.
import { motion } from 'framer-motion';
import { Users } from 'lucide-react';
import { useEffect, useRef } from 'react';
import type { ApprovalRuleView } from '@/api/types';
import { cn } from '@/lib/utils';
import { ApproverBadge } from '../ApproverBadge';
import { fmtTtl } from '../lib/format-gov';

const TH = 'px-3 py-2 text-left text-2xs font-medium uppercase tracking-wider text-text-3';

export function RulesTable({ rules, highlightId, defaultTtl }: { rules: ApprovalRuleView[]; highlightId: string | null; defaultTtl: number }) {
  const hiRef = useRef<HTMLTableRowElement | null>(null);
  useEffect(() => {
    if (highlightId && hiRef.current) hiRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [highlightId]);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] border-collapse text-[12.5px]">
        <thead className="border-b border-border-subtle">
          <tr>
            <th className={cn(TH, 'w-10 pl-4 text-right')}>#</th>
            <th className={TH}>Rule</th>
            <th className={TH}>When</th>
            <th className={TH}>Approver</th>
            <th className={TH}>Two-person</th>
            <th className={cn(TH, 'pr-4 text-right')}>TTL</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((r, i) => {
            const hi = r.id === highlightId;
            return (
              <tr
                key={r.id}
                ref={hi ? hiRef : undefined}
                className={cn(
                  'relative border-b border-border-subtle/60 align-top transition-colors last:border-0 hover:bg-surface-2/40',
                  hi && 'bg-approval/[0.08] hover:bg-approval/10',
                )}
              >
                <td className="relative py-2 pl-4 pr-3 text-right tabular text-text-4">
                  {hi ? <motion.span layoutId="rule-hi" className="absolute inset-y-0 left-0 w-[3px] bg-approval" /> : null}
                  {i + 1}
                </td>
                <td className="px-3 py-2">
                  <div className={cn('font-mono text-[12px] font-medium', hi ? 'text-approval' : 'text-text-1')}>{r.id}</div>
                  {r.description ? <div className="mt-0.5 max-w-[340px] text-[11.5px] leading-4 text-text-3">{r.description}</div> : null}
                </td>
                <td className="px-3 py-2 font-mono text-[11.5px] leading-[17px] text-text-2">{r.when}</td>
                <td className="px-3 py-2">
                  <ApproverBadge level={r.approver} size="sm" />
                </td>
                <td className="px-3 py-2">
                  {r.two_person ? (
                    <span className="inline-flex h-[18px] items-center gap-1 rounded-full border border-accent-fg/30 bg-brand/10 px-1.5 text-2xs text-accent-fg">
                      <Users className="size-2.5" /> 2 approvers
                    </span>
                  ) : (
                    <span className="text-text-4">—</span>
                  )}
                </td>
                <td className="py-2 pl-3 pr-4 text-right tabular text-text-2">
                  {r.ttl_s ? (
                    fmtTtl(r.ttl_s)
                  ) : (
                    <span className="text-text-4" title="defaults.ttl_s">
                      {fmtTtl(defaultTtl)}
                    </span>
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
