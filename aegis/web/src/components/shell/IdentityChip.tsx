import { Bot } from '@/components/icons';
import { getMember } from '@/api/hooks';
import type { Identity } from '@/api/types';
import { avatarColor } from '@/lib/colors';
import { initials } from '@/lib/format';
import { cn } from '@/lib/utils';

/** Small avatar (initials, deterministic tint) used by IdentityChip, the view-as switcher and lists. */
export function Avatar({ name, size = 22, className }: { name: string; size?: number; className?: string }) {
  const c = avatarColor(name);
  return (
    <span
      className={cn('inline-grid shrink-0 place-items-center rounded-full font-semibold tracking-[0.02em]', className)}
      style={{ width: size, height: size, fontSize: Math.max(9, Math.round(size * 0.42)), background: c.bg, color: c.fg, boxShadow: 'inset 0 0 0 1px rgba(255,255,255,.06)' }}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}

/** Agent avatar: bot glyph on a teal tile (7 px radius, DESIGN_TOKENS §9). */
export function AgentAvatar({ size = 22, className }: { size?: number; className?: string }) {
  return (
    <span
      className={cn('inline-grid shrink-0 place-items-center rounded-[7px] border border-role-agent/25 bg-role-agent/10 text-role-agent', className)}
      style={{ width: size, height: size }}
      aria-hidden
    >
      <Bot style={{ width: size * 0.6, height: size * 0.6 }} strokeWidth={2} />
    </span>
  );
}

/** Who did it: agent (bot tile + mono id) or member (avatar + name). */
export function IdentityChip({ identity, size = 'sm', showTeam = false, avatar = true, className }: { identity: Identity | null; size?: 'sm' | 'md'; showTeam?: boolean; avatar?: boolean; className?: string }) {
  if (!identity) return <span className="text-text-4">—</span>;
  const isAgent = Boolean(identity.agent_id);
  const member = getMember(identity.member_id);
  const name = isAgent ? (identity.agent_id ?? 'agent') : (member?.name ?? identity.display_name ?? identity.member_id ?? 'anonymous');
  const px = size === 'md' ? 22 : 18;
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-1.5', size === 'md' ? 'text-sm' : 'text-xs', className)} title={isAgent && member ? `${name} · sponsor ${member.name}` : name}>
      {avatar ? isAgent ? <AgentAvatar size={px} /> : <Avatar name={name} size={px} /> : null}
      <span className={cn('truncate font-medium text-text-1', isAgent && 'mono')}>{isAgent ? name.split('@')[0] : name}</span>
      {isAgent && name.includes('@') ? <span className="mono -ml-1 truncate text-text-3">@{name.split('@')[1]}</span> : null}
      {showTeam && identity.team_id && !isAgent ? <span className="truncate text-text-3">· {identity.team_id}</span> : null}
    </span>
  );
}
