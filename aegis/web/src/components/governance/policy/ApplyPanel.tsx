// Role-aware Apply (UIG-04): required role (server PolicyDiffResponse.required_role, else the
// config-rules estimate) + why + reason + the button: "Apply now" when the viewer's role is enough,
// "Request approval · needs owner" (violet) otherwise, locked when whoami says `no`. Invalid YAML can
// still be applied (with a warning) so the rejection path is demoable. Real-data step strip.
// Owner: B19-dashboard-gov-policy.
import { Check, ChevronRight, Loader2, Minus, Send, X, Zap } from 'lucide-react';
import { useState } from 'react';
import { ApproverBadge } from '@/components/governance/ApproverBadge';
import { LockedAction } from '@/components/governance/LockedAction';
import { Input } from '@/components/ui/input';
import { fmtMs } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { PolicyDraft, StepState } from './use-policy-draft';

function Step({ label, state, detail }: { label: string; state: StepState; detail?: string | null }) {
  const icon =
    state === 'ok' ? <Check className="size-3" /> : state === 'fail' ? <X className="size-3" /> : state === 'run' ? <Loader2 className="size-3 animate-spin" /> : state === 'skip' ? <Minus className="size-3" /> : null;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-2xs',
        state === 'ok' && 'border-allow/30 bg-allow/10 text-allow',
        state === 'fail' && 'border-block/30 bg-block/10 text-block',
        state === 'run' && 'border-[var(--accent-border)] bg-[var(--accent-subtle)] text-accent-fg',
        (state === 'idle' || state === 'skip') && 'border-border bg-surface-2 text-text-3',
      )}
    >
      {icon}
      {label}
      {detail ? <span className="font-mono">{detail}</span> : null}
    </span>
  );
}

export function ApplyPanel({ d }: { d: PolicyDraft }) {
  const [reason, setReason] = useState('');
  const level = d.requiredRole;
  const noChanges = !d.dirty;
  const locked = d.canApply === 'no';
  const direct = d.roleOk || level === 'auto';
  const label = noChanges ? 'No changes' : direct ? 'Apply now' : `Request approval · needs ${level}`;
  const s = d.steps;
  const showSteps = s.parse !== 'idle';

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-text-2">
        <span className="text-text-3">Required</span>
        {level ? <ApproverBadge level={level} size="sm" /> : <span className="text-text-3">—</span>}
        {d.ruleId ? <span className="font-mono text-2xs text-text-3">{d.ruleId}</span> : null}
        {d.requiredRoleIsEstimate && level ? <span className="rounded border border-border px-1 text-[10px] text-text-3">estimate</span> : null}
      </div>
      <div className="text-xs leading-relaxed text-text-3">
        {noChanges
          ? 'Edit the draft to see who has to approve it.'
          : level === 'auto'
            ? 'Tightening only — applies automatically for any role.'
            : direct
              ? `You are ${d.role === 'owner' ? 'an owner' : d.role === 'admin' ? 'an admin' : 'a member'} — this hot-reloads immediately (validate → self-test → atomic swap).`
              : `You are ${d.role === 'admin' ? 'an admin' : 'a member'}; this change needs ${level === 'owner' ? 'an owner' : `an ${level}`}. Applying parks the draft as an approval request (GOV-05).`}
      </div>
      <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (goes to the audit log)" className="h-8 text-xs" />
      {!noChanges && !d.valid && !d.checking ? <div className="text-2xs text-block">Draft has errors — the server will reject it (that's the safety net).</div> : null}
      <LockedAction
        locked={locked}
        reason="Your role cannot change the policy"
        disabled={noChanges || d.applying}
        onClick={() => void d.apply(reason.trim())}
        className={cn('w-full', !noChanges && !direct && 'bg-approval text-white hover:bg-approval/90')}
        wrapperClassName="w-full"
        hint={!noChanges ? '⌘S' : undefined}
      >
        {d.applying ? <Loader2 className="size-3.5 animate-spin" /> : direct ? <Zap className="size-3.5" /> : <Send className="size-3.5" />}
        {label}
      </LockedAction>
      {showSteps ? (
        <div className="flex flex-wrap items-center gap-1">
          <Step label="Parsed" state={s.parse} />
          <ChevronRight className="size-3 text-text-4" />
          <Step label="Validated" state={s.validate} />
          <ChevronRight className="size-3 text-text-4" />
          <Step label="Self-tests" state={s.selftest} detail={s.selftestText} />
          <ChevronRight className="size-3 text-text-4" />
          <Step label="Swapped" state={s.swap} detail={s.swapMs !== null ? fmtMs(s.swapMs) : null} />
        </div>
      ) : null}
    </div>
  );
}
