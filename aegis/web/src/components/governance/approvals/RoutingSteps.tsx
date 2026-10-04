// Requested ✓ → Rule ✓ → approver slot(s) → Executed. Real data only (votes, execution, uses).
// Owner: B18-dashboard-gov-approvals.
import { Check, ChevronRight, FileCode, Play, Send, ShieldCheck, User, X } from '@/components/icons';
import type { ReactNode } from 'react';
import type { ApprovalRequest } from '@/api/types';
import { cn } from '@/lib/utils';
import type { Directory } from '../hooks';
import { roleSatisfies } from '../lib/eligibility';
import { firstName } from '../lib/format-gov';

type StepState = 'done' | 'active' | 'idle' | 'fail';

function Step({ state, icon, children, i }: { state: StepState; icon: ReactNode; children: ReactNode; i: number }) {
  return (
    <div
      data-step={i}
      className={cn(
        'flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs transition-colors duration-150',
        state === 'done' && 'border-allow/30 bg-allow/10 text-text-1',
        state === 'active' && 'border-approval/40 bg-approval/10 text-text-1',
        state === 'idle' && 'border-border bg-surface-2 text-text-3',
        state === 'fail' && 'border-block/35 bg-block/10 text-block',
      )}
    >
      <span className={cn('grid size-4 place-items-center', state === 'done' ? 'text-allow' : state === 'active' ? 'text-approval' : '')}>{icon}</span>
      {children}
    </div>
  );
}

const Conn = () => <ChevronRight className="size-3.5 shrink-0 text-text-4" />;

export function RoutingSteps({ req, dir }: { req: ApprovalRequest; dir: Directory }) {
  const approvals = req.votes.filter((v) => v.decision === 'approve');
  const deny = req.votes.find((v) => v.decision === 'deny');
  const needed = req.two_person ? 2 : 1;
  const name = (id: string) => firstName(dir.memberById.get(id)?.name ?? id);
  const ex = (req.execution ?? {}) as Record<string, unknown>;
  const closed = req.status === 'denied' || req.status === 'expired' || req.status === 'cancelled';
  let i = 0;

  const slots: ReactNode[] = [];
  if (req.required_role === 'auto') {
    slots.push(
      <Step key="auto" i={++i} state="done" icon={<Check className="size-3.5" />}>
        Auto-approved by rule
      </Step>,
    );
  } else if (req.required_role === 'deny') {
    slots.push(
      <Step key="deny" i={++i} state="fail" icon={<X className="size-3.5" />}>
        Denied by rule
      </Step>,
    );
  } else {
    // order slots so the level-satisfying approval shows in slot 1
    const ordered = [...approvals].sort((a, b) => Number(roleSatisfies(b.role, req.required_role)) - Number(roleSatisfies(a.role, req.required_role)));
    for (let k = 0; k < needed; k++) {
      const v = ordered[k];
      const label = req.two_person ? (k === 0 ? `${req.required_role === 'owner' ? 'Owner' : 'Admin'} slot` : 'Second admin+') : req.required_role === 'self' ? 'Sponsor / admin' : `${req.required_role.charAt(0).toUpperCase()}${req.required_role.slice(1)}`;
      if (k > 0 || needed > 1) slots.push(<Conn key={`c-${k}`} />);
      if (v) {
        slots.push(
          <Step key={`s-${k}`} i={++i} state="done" icon={<Check className="size-3.5" />}>
            {name(v.member_id)}<span className="text-2xs text-text-3">{v.role}</span>
          </Step>,
        );
      } else if (deny && k === approvals.length) {
        slots.push(
          <Step key={`s-${k}`} i={++i} state="fail" icon={<X className="size-3.5" />}>
            Denied by {name(deny.member_id)}
          </Step>,
        );
      } else {
        const active = req.status === 'pending' && k === approvals.length;
        slots.push(
          <Step key={`s-${k}`} i={++i} state={closed ? 'fail' : active ? 'active' : 'idle'} icon={req.two_person ? <User className="size-3.5" /> : <ShieldCheck className="size-3.5" />}>
            {closed && k === approvals.length ? `${req.status}` : label}
          </Step>,
        );
      }
    }
  }

  let exec: ReactNode;
  if (req.status === 'approved') {
    const pv = typeof ex.policy_version === 'number' ? ex.policy_version : null;
    const text = pv !== null ? `Applied as policy v${pv}` : req.kind === 'action' ? `Grant used ${req.uses}/${req.max_uses}` : 'Executed';
    exec = (
      <Step i={++i} state="done" icon={<Play className="size-3.5" />}>
        {text}
      </Step>
    );
  } else {
    exec = (
      <Step i={++i} state={closed || req.required_role === 'deny' ? 'fail' : 'idle'} icon={<Play className="size-3.5" />}>
        {closed || req.required_role === 'deny' ? 'Not executed' : req.kind === 'action' ? 'Held call proceeds' : 'Apply change'}
      </Step>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Step i={0} state="done" icon={<Send className="size-3.5" />}>
        Requested
      </Step>
      <Conn />
      <Step i={1} state="done" icon={<FileCode className="size-3.5" />}>
        <span className="font-mono text-[11.5px]">{req.rule_id ?? 'default'}</span>
      </Step>
      {req.two_person || req.required_role === 'auto' || req.required_role === 'deny' ? null : <Conn />}
      {req.required_role === 'auto' || req.required_role === 'deny' ? <Conn /> : null}
      {slots}
      <Conn />
      {exec}
    </div>
  );
}
