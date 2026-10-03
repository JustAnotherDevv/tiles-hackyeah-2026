import { Bot, User } from 'lucide-react';
import type { Identity } from '@/api/types';

export function IdentityChip({ identity, size = 'sm', showTeam = false }: { identity: Identity | null; size?: 'sm' | 'md'; showTeam?: boolean }) {
  if (!identity) return <span className="text-text-4">—</span>;
  const isAgent = Boolean(identity.agent_id);
  const Icon = isAgent ? Bot : User;
  const name = identity.display_name ?? identity.agent_id ?? identity.member_id ?? 'anonymous';
  return (
    <span className={`inline-flex items-center gap-1.5 ${size === 'md' ? 'text-sm' : 'text-xs'}`}>
      <Icon className={`size-3.5 ${isAgent ? 'text-role-agent' : 'text-text-3'}`} />
      <span className="font-mono">{name}</span>
      {showTeam && identity.team_id ? <span className="text-text-3">· {identity.team_id}</span> : null}
    </span>
  );
}
