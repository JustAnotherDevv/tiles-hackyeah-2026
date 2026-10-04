// Roles & permissions matrix (capability × owner/admin/member/agent) from CONTRACTS §3.5/§5.4 and
// Addendum A-20/A-37, plus a live row of rule ids grouped by approver level from
// /api/approvals/rules. The current "view as" column is highlighted. Owner: B18.
import { Check, Minus, X } from '@/components/icons';
import type { ApprovalRuleView, Role } from '@/api/types';
import { RoleBadge } from '@/components/shell';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ROLE_COLORS } from '@/lib/colors';
import type { ViewRole } from '@/lib/page';
import { cn } from '@/lib/utils';

type Cell = 'yes' | 'no' | { partial: string };
interface Row {
  cap: string;
  hint?: string;
  cells: Record<Role, Cell>;
}

const COLS: Role[] = ['owner', 'admin', 'member', 'agent'];

const ROWS: Row[] = [
  {
    cap: 'View dashboards, live feed, audit trail',
    cells: { owner: 'yes', admin: 'yes', member: 'yes', agent: 'no' },
  },
  {
    cap: 'Approve self-level items',
    hint: 'e.g. spend ≤ $20, staging DB writes',
    cells: {
      owner: 'yes',
      admin: 'yes',
      member: {
        partial: 'Only for agents they sponsor (or their own requests)',
      },
      agent: 'no',
    },
  },
  {
    cap: 'Approve admin-level items',
    hint: 'e.g. $50 MarketPulse, PII table reads',
    cells: {
      owner: 'yes',
      admin: {
        partial: 'Never for an agent they sponsor (separation of duties)',
      },
      member: 'no',
      agent: 'no',
    },
  },
  {
    cap: 'Approve owner-level items',
    hint: 'e.g. $480 GPU, disable a critical control',
    cells: {
      owner: { partial: 'Never their own request (separation of duties)' },
      admin: 'no',
      member: 'no',
      agent: 'no',
    },
  },
  {
    cap: 'Second signature (two-person rule)',
    hint: 'owner + a distinct admin',
    cells: { owner: 'yes', admin: 'yes', member: 'no', agent: 'no' },
  },
  {
    cap: 'Apply policy edits',
    cells: {
      owner: 'yes',
      admin: {
        partial: 'Directly up to admin-level changes; owner-level edits become an approval request',
      },
      member: { partial: 'Request only (self-level edits apply)' },
      agent: 'no',
    },
  },
  {
    cap: 'Raise budgets',
    cells: {
      owner: 'yes',
      admin: {
        partial: 'Team ≤ 2×, agents/members; larger raises need an owner',
      },
      member: { partial: 'Own agents ≤ +50%; anything else is a request' },
      agent: 'no',
    },
  },
  {
    cap: 'Kill switch',
    cells: {
      owner: 'yes',
      admin: 'yes',
      member: { partial: 'Agents they sponsor (auto-approved)' },
      agent: 'no',
    },
  },
  {
    cap: 'Manage members & agents',
    cells: {
      owner: 'yes',
      admin: {
        partial: 'Routine changes; role promotions/demotions need owner approval',
      },
      member: 'no',
      agent: 'no',
    },
  },
  {
    cap: 'Export audit',
    cells: { owner: 'yes', admin: 'yes', member: 'no', agent: 'no' },
  },
  {
    cap: 'Call models & tools through Aegis',
    hint: 'every call is evaluated by policy',
    cells: { owner: 'yes', admin: 'yes', member: 'yes', agent: 'yes' },
  },
];

function CellIcon({ cell }: { cell: Cell }) {
  if (cell === 'yes') return <Check className="mx-auto size-4 text-allow" strokeWidth={2.4} />;
  if (cell === 'no') return <X className="mx-auto size-3.5 text-text-4" />;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className="mx-auto inline-flex h-5 cursor-help items-center gap-1 rounded-sm border border-redact/30 bg-redact/10 px-1.5 text-2xs font-medium text-redact"
          tabIndex={0}
        >
          <Minus className="size-3" /> partial
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-[260px]">
        {cell.partial}
      </TooltipContent>
    </Tooltip>
  );
}

export function RolesMatrix({ viewerRole, rules }: { viewerRole: ViewRole; rules: ApprovalRuleView[] }) {
  const byLevel = (lvl: ApprovalRuleView['approver']) => rules.filter((r) => r.approver === lvl).map((r) => r.id);
  const live: Record<Role, string[]> = {
    owner: byLevel('owner'),
    admin: byLevel('admin'),
    member: byLevel('self'),
    agent: [],
  };
  const colCls = (c: Role) => (c === viewerRole ? 'bg-surface-2/70' : '');
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-[12.5px]">
        <thead>
          <tr className="border-b border-border-subtle">
            <th className="px-4 py-2.5 text-left text-2xs font-medium uppercase tracking-wider text-text-3">Capability</th>
            {COLS.map((c) => (
              <th key={c} className={cn('w-[150px] px-3 py-2.5 text-center', colCls(c))} style={c === viewerRole ? { boxShadow: `inset 0 2px 0 ${ROLE_COLORS[c].fg}` } : undefined}>
                <div className="flex flex-col items-center gap-1">
                  <RoleBadge role={c} />
                  {c === viewerRole ? <span className="text-2xs font-medium text-text-2">viewing as</span> : <span className="text-2xs text-transparent">·</span>}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.cap} className="border-b border-border-subtle/60 hover:bg-surface-2/30">
              <td className="px-4 py-2">
                <div className="text-text-1">{r.cap}</div>
                {r.hint ? <div className="text-2xs text-text-3">{r.hint}</div> : null}
              </td>
              {COLS.map((c) => (
                <td key={c} className={cn('px-3 py-2 text-center', colCls(c))}>
                  <CellIcon cell={r.cells[c]} />
                </td>
              ))}
            </tr>
          ))}
          <tr>
            <td className="px-4 py-2.5 align-top">
              <div className="text-text-1">Approves (from live rules)</div>
              <div className="text-2xs text-text-3">rule ids routed to this level · /api/approvals/rules</div>
            </td>
            {COLS.map((c) => (
              <td key={c} className={cn('px-2 py-2.5 align-top', colCls(c))}>
                {live[c].length > 0 ? (
                  <div className="flex flex-wrap justify-center gap-1">
                    {live[c].map((id) => (
                      <span key={id} className="rounded-xs border border-border bg-surface-2 px-1 font-mono text-[10px] text-text-2">
                        {id}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="text-center text-2xs text-text-4">never votes</div>
                )}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
