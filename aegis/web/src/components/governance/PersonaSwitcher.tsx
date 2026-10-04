// Compact "Viewing as ▾" switcher (useViewAs().setViewAs) + quick persona chips for the demo
// (Piotr member · Emily admin · Katarzyna owner). Owner: B18-dashboard-gov-approvals.
import { Eye } from '@/components/icons';
import type { Member } from '@/api/types';
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ROLE_COLORS } from '@/lib/colors';
import { cn } from '@/lib/utils';
import { useDirectory, useViewer } from './hooks';
import { firstName } from './lib/format-gov';
import { MemberAvatar } from './MemberAvatar';

const QUICK_PERSONAS = ['u_piotr', 'u_emily', 'u_katarzyna'] as const;
const ROLE_ORDER: Member['role'][] = ['owner', 'admin', 'member'];

export function PersonaSwitcher({ chips = true, select = true, className, personas = QUICK_PERSONAS }: { chips?: boolean; select?: boolean; className?: string; personas?: readonly string[] }) {
  const { viewerId, members: shellMembers, setViewAs } = useViewer();
  const dir = useDirectory();
  // Prefer the governance directory (names/colours); fall back to the shell's member list.
  const members = dir.members.length > 0 ? dir.members : shellMembers;
  const byId = new Map(members.map((m) => [m.id, m]));
  const current = viewerId ? byId.get(viewerId) : undefined;

  return (
    <div className={cn('flex min-w-0 max-w-full flex-wrap items-center gap-2', className)}>
      <span className="inline-flex shrink-0 items-center gap-1 text-xs text-text-3">
        <Eye className="size-3.5" /> Viewing as
      </span>
      {chips ? (
        <div className="relative flex max-w-full items-center gap-0.5 overflow-x-auto rounded-md border border-border bg-surface-1 p-0.5">
          {personas.map((id) => {
            const m = byId.get(id);
            if (!m) return null;
            const active = id === viewerId;
            return (
              <button
                key={id}
                type="button"
                onClick={() => setViewAs(id)}
                className={cn(
                  'relative flex h-9 shrink-0 items-center sm:h-8 gap-1.5 rounded-[5px] px-2 text-xs transition-colors',
                  active ? 'text-text-1' : 'text-text-3 hover:text-text-1',
                )}
                aria-pressed={active}
                title={`View as ${m.name} (${m.role})`}
              >
                {active ? <span className="absolute inset-0 rounded-[5px] border border-border-strong bg-surface-3" /> : null}
                <span className="relative flex items-center gap-1.5">
                  <MemberAvatar member={m} size="xs" />
                  <span className="font-medium">{firstName(m.name)}</span>
                  <span className="text-2xs" style={{ color: ROLE_COLORS[m.role].fg }}>
                    {m.role}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
      {select ? (
        <Select value={viewerId ?? ''} onValueChange={(v) => setViewAs(v)}>
          <SelectTrigger size="sm" className="hidden min-w-[150px] bg-surface-1 sm:flex" aria-label="View as">
            <SelectValue placeholder="Pick a person">
              {current ? (
                <span className="flex items-center gap-1.5">
                  <MemberAvatar member={current} size="xs" />
                  <span className="truncate">{current.name}</span>
                </span>
              ) : null}
            </SelectValue>
          </SelectTrigger>
          <SelectContent position="popper" align="end">
            {ROLE_ORDER.map((role) => {
              const group = members.filter((m) => m.role === role);
              if (group.length === 0) return null;
              return (
                <SelectGroup key={role}>
                  <SelectLabel className="text-2xs uppercase tracking-wider" style={{ color: ROLE_COLORS[role].fg }}>
                    {ROLE_COLORS[role].label}s
                  </SelectLabel>
                  {group.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      <span className="flex items-center gap-2">
                        <MemberAvatar member={m} size="xs" />
                        <span>{m.name}</span>
                        <span className="text-2xs text-text-3">{m.title ?? ''}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectGroup>
              );
            })}
          </SelectContent>
        </Select>
      ) : null}
    </div>
  );
}
