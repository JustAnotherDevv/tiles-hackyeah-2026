// auto | self | admin | owner | deny badge (owner fuchsia, admin sky, self emerald, auto slate, deny rose).
// Owner: B18-dashboard-gov-approvals.
import { Ban, Shield, ShieldCheck, User, Zap } from 'lucide-react';
import type { ApproverLevel } from '@/api/types';
import { ROLE_COLORS } from '@/lib/colors';
import { cn } from '@/lib/utils';
import { levelLabel } from './lib/format-gov';

const ICON = { auto: Zap, self: User, admin: Shield, owner: ShieldCheck, deny: Ban } as const;

export function ApproverBadge({ level, size = 'md', label, className }: { level: ApproverLevel; size?: 'sm' | 'md'; label?: string; className?: string }) {
  const c = ROLE_COLORS[level];
  const Icon = ICON[level] ?? Shield;
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border font-medium',
        size === 'sm' ? 'h-[18px] px-1.5 text-2xs' : 'h-5 px-2 text-xs',
        c.className,
        className,
      )}
    >
      <Icon className={size === 'sm' ? 'size-2.5' : 'size-3'} />
      {label ?? levelLabel(level)}
    </span>
  );
}
