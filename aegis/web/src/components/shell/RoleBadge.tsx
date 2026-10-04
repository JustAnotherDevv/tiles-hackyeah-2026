import type { ApproverLevel, Role } from '@/api/types';
import { ROLE_COLORS } from '@/lib/colors';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';

/** Role / approver-level pill (owner fuchsia · admin sky · member slate · agent teal · self emerald). */
export function RoleBadge({ role, prefix, className, icon = true }: { role: Role | ApproverLevel; prefix?: string; className?: string; icon?: boolean }) {
  const c = ROLE_COLORS[role] ?? ROLE_COLORS.member;
  const Icon = resolveIcon(c.icon);
  return (
    <span className={cn('inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2 text-xs font-medium', c.className, className)}>
      {icon ? <Icon className="size-3" strokeWidth={2.2} /> : null}
      {prefix ? `${prefix} ${c.label}` : c.label}
    </span>
  );
}
