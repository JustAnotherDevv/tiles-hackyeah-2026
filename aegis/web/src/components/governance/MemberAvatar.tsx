// Flat initials avatar (tinted by meta.avatar_color) + optional name; agents render as a bot tile.
// Owner: B18-dashboard-gov-approvals.
import { Bot } from '@/components/icons';
import type { Member } from '@/api/types';
import { ROLE_COLORS } from '@/lib/colors';
import { cn } from '@/lib/utils';
import { initials } from './lib/format-gov';

const SIZES = { xs: 'size-5 text-[9px]', sm: 'size-6 text-[10px]', md: 'size-8 text-xs', lg: 'size-10 text-sm' } as const;

export interface MemberAvatarProps {
  member?: Member | null;
  /** Fallback name when no member object is available (or an agent id). */
  name?: string | null;
  color?: string | null;
  agent?: boolean;
  size?: keyof typeof SIZES;
  showName?: boolean;
  /** Ring in the role colour (e.g. the current viewer). */
  highlight?: boolean;
  dim?: boolean;
  className?: string;
  title?: string;
}

function memberColor(member: Member | null | undefined): string {
  const c = member?.meta?.avatar_color;
  if (typeof c === 'string' && c) return c;
  return member ? ROLE_COLORS[member.role].fg : '#64748b';
}

export function MemberAvatar({ member, name, color, agent = false, size = 'sm', showName = false, highlight = false, dim = false, className, title }: MemberAvatarProps) {
  const label = member?.name ?? name ?? '—';
  const bg = color ?? memberColor(member);
  const ring = highlight ? ROLE_COLORS[member?.role ?? 'member'].fg : undefined;
  const tile = agent ? (
    <span
      className={cn('grid shrink-0 place-items-center rounded-md border border-role-agent/30 bg-role-agent/10 text-role-agent', SIZES[size])}
      title={title ?? label}
    >
      <Bot className="size-[62%]" />
    </span>
  ) : (
    <span
      className={cn('grid shrink-0 select-none place-items-center rounded-full border font-semibold tracking-[0.02em]', SIZES[size], dim && 'opacity-45 grayscale')}
      style={{
        background: `color-mix(in oklab, ${bg} 16%, var(--surface-2))`,
        borderColor: `color-mix(in oklab, ${bg} 38%, var(--border))`,
        color: `color-mix(in oklab, ${bg} 70%, var(--text-1))`,
        boxShadow: ring ? `0 0 0 2px var(--background), 0 0 0 3px ${ring}` : undefined,
      }}
      title={title ?? label}
    >
      {initials(label)}
    </span>
  );
  if (!showName) return <span className={cn('inline-flex', className)}>{tile}</span>;
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-1.5', className)}>
      {tile}
      <span className={cn('truncate', agent && 'font-mono text-[12px]')}>{label}</span>
    </span>
  );
}
