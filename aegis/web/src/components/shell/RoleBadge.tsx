import type { ApproverLevel, Role } from '@/api/types';
import { ROLE_COLORS } from '@/lib/colors';
import { cn } from '@/lib/utils';

export function RoleBadge({ role }: { role: Role | ApproverLevel }) {
  const c = ROLE_COLORS[role];
  return <span className={cn('inline-flex h-5 items-center rounded-full border px-2 text-xs font-medium', c.className)}>{c.label}</span>;
}
