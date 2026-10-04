// Role badge that doubles as a "change role" menu (UIG-10). Every option stays visible; options the
// viewer cannot pick are disabled with the reason inline. Admin-initiated role changes are sent as
// owner approvals (rule org-privileged). Owner: B18-dashboard-gov-approvals.
import { ChevronDown, Lock, Send } from '@/components/icons';
import type { Member } from '@/api/types';
import { RoleBadge } from '@/components/shell';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { ViewRole } from '@/lib/page';
import { cn } from '@/lib/utils';
import { roleChangeGate, type Gate } from './org-actions';

const ROLES: Member['role'][] = ['owner', 'admin', 'member'];

export function RoleChangeMenu({
  target,
  viewerRole,
  viewerId,
  manageGate,
  ownerCount,
  busy,
  onChange,
}: {
  target: Member;
  viewerRole: ViewRole;
  viewerId: string | null;
  manageGate: Gate;
  ownerCount: number;
  busy?: boolean;
  onChange: (role: Member['role']) => void;
}) {
  const self = target.id === viewerId;
  const gates = ROLES.filter((r) => r !== target.role).map((r) => roleChangeGate(viewerRole, viewerId, target, r, ownerCount));
  if (!manageGate.ok || self || gates.every((g) => !g.ok)) {
    const reason = !manageGate.ok ? manageGate.reason : self ? 'You cannot change your own role (separation of duties).' : (gates[0]?.reason ?? 'Not allowed');
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex cursor-not-allowed items-center gap-1" tabIndex={0}>
            <RoleBadge role={target.role} />
            <Lock className="size-3 text-text-4" />
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[260px]">
          {reason}
        </TooltipContent>
      </Tooltip>
    );
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={busy}>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          aria-label={`Change role of ${target.name}`}
        >
          <RoleBadge role={target.role} />
          <ChevronDown className="size-3 text-text-3" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[268px]">
        <DropdownMenuLabel className="text-2xs uppercase tracking-wider text-text-3">Change role · {target.name}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {ROLES.map((r) => {
          const g = roleChangeGate(viewerRole, viewerId, target, r, ownerCount);
          const current = r === target.role;
          return (
            <DropdownMenuItem key={r} disabled={!g.ok} onSelect={() => g.ok && onChange(r)} className={cn('flex-col items-start gap-0.5 py-1.5', current && 'bg-surface-2')}>
              <span className="flex w-full items-center gap-2">
                <RoleBadge role={r} />
                {current ? <span className="text-2xs text-text-3">current</span> : null}
                {g.ok && g.needsApproval ? (
                  <span className="ml-auto inline-flex items-center gap-1 text-2xs text-approval">
                    <Send className="size-3" /> needs {g.needsApproval}
                  </span>
                ) : null}
                {!g.ok && !current ? <Lock className="ml-auto size-3 text-text-4" /> : null}
              </span>
              {!g.ok && !current && g.reason ? <span className="pl-0.5 text-2xs leading-4 text-text-3">{g.reason}</span> : null}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
