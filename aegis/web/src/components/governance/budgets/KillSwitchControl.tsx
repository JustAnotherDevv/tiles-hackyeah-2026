// Kill switch (kill-switch half of UIG-10, flow F6): per-row toggle for agents/teams/members/sessions
// and a separate global danger panel. Confirm dialog with a REQUIRED reason → POST /api/killswitch
// {scope, active, reason} → ApplyResult (applied / pending_approval like a budget raise / …).
// Locked with a reason tooltip when the viewer may not use it (never hidden). Sponsors may always
// pull the brake on their own agent (approvals rule `killswitch-own-agent`, SF-16).
// Owner: B19-dashboard-gov-policy.
import { Loader2, Power, PowerOff, ShieldAlert } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import type { ApplyResult } from '@/api/types';
import { errorTitle, parseApiError } from '@/components/governance/gov-api';
import { LockedAction } from '@/components/governance/LockedAction';
import { scopeLabel } from '@/components/governance/lib/format-gov';
import { policyApi, type MockViewer } from '@/components/governance/policy/policy-api';
import { toastApplyResult } from '@/components/governance/policy/policy-toast';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

const PRESETS = ['Runaway loop', 'Suspected prompt injection', 'Cost spike', 'Incident drill'];

export interface KillPermission {
  /** viewer may engage (turn ON) for this scope */
  canEngage: boolean;
  /** viewer may release (turn OFF) */
  canRelease: boolean;
  reason: string;
}

/** Client-side pre-check (the server's ApplyResult is the truth). */
export function killPermission(opts: { canKillswitch: boolean; scope: string; viewerId: string | null; sponsorId?: string | null }): KillPermission {
  if (opts.canKillswitch) return { canEngage: true, canRelease: true, reason: '' };
  const ownAgent = opts.scope.startsWith('agent:') && opts.sponsorId !== null && opts.sponsorId !== undefined && opts.sponsorId === opts.viewerId;
  return {
    canEngage: ownAgent,
    canRelease: false,
    reason: ownAgent ? 'Releasing the kill switch requires an admin' : 'Requires admin — members can only stop agents they sponsor',
  };
}

function KillConfirmDialog({
  scope,
  active,
  open,
  onOpenChange,
  viewer,
  onDone,
}: {
  scope: string;
  active: boolean;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  viewer: MockViewer;
  onDone?: (r: ApplyResult) => void;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const ok = reason.trim().length >= 3;
  const submit = async () => {
    if (!ok) return;
    setBusy(true);
    try {
      const r = await policyApi.killswitch({ scope, active, reason: reason.trim() }, viewer);
      const what = `Kill switch ${active ? 'ON' : 'off'} · ${scope}`;
      if (r.data.status === 'applied') {
        toast[active ? 'error' : 'success'](`${what}`, {
          id: `kill-${scope}`,
          description: active ? `New calls get 429 killed${r.data.version ? ` · policy v${r.data.version}` : ''}` : `Traffic resumes${r.data.version ? ` · policy v${r.data.version}` : ''}`,
          icon: active ? <PowerOff className="size-4 text-block" /> : <Power className="size-4 text-allow" />,
        });
      } else toastApplyResult(r.data, { what });
      onDone?.(r.data);
      setReason('');
      onOpenChange(false);
    } catch (e) {
      const p = parseApiError(e);
      toast.error(errorTitle(p), { description: p.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className={cn('flex items-center gap-2', active ? 'text-block' : 'text-text-1')}>
            {active ? <PowerOff className="size-4" /> : <Power className="size-4 text-allow" />}
            {active ? 'Engage kill switch' : 'Release kill switch'}
          </DialogTitle>
          <DialogDescription className="text-text-2">
            {scope === 'global' ? 'Every agent in the organization' : scopeLabel(scope)}
            {active ? ' — in-flight calls finish, every new call answers 429 killed.' : ' — traffic resumes immediately.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <div className="text-2xs font-medium uppercase tracking-wider text-text-3">Reason (required, goes to the audit log)</div>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} autoFocus placeholder="Why?" className="text-sm" />
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setReason(p)}
                className="rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-xs text-text-2 hover:border-border-strong hover:text-text-1"
              >
                {p}
              </button>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant={active ? 'danger' : 'success'} onClick={() => void submit()} disabled={!ok || busy}>
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : active ? <PowerOff className="size-3.5" /> : <Power className="size-3.5" />}
            {active ? 'Kill' : 'Release'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Compact per-row toggle. */
export function KillSwitchControl({
  scope,
  killed,
  perm,
  viewer,
  onDone,
  inheritedFrom,
}: {
  scope: string;
  killed: boolean;
  perm: KillPermission;
  viewer: MockViewer;
  onDone?: (r: ApplyResult) => void;
  /** killed by a parent scope (global / team) — can't be released here */
  inheritedFrom?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const next = !killed;
  if (killed && inheritedFrom) {
    return <span className="whitespace-nowrap text-2xs text-block/80">killed via {inheritedFrom === 'global' ? 'global switch' : inheritedFrom}</span>;
  }
  const locked = next ? !perm.canEngage : !perm.canRelease;
  return (
    <>
      <LockedAction
        locked={locked}
        reason={perm.reason}
        size="xs"
        variant={killed ? 'success' : 'danger-ghost'}
        onClick={() => setOpen(true)}
        hint={killed ? 'Release the kill switch' : 'Stop this scope now (429 killed)'}
      >
        {!locked ? killed ? <Power className="size-3" /> : <PowerOff className="size-3" /> : null}
        {killed ? 'Release' : 'Kill'}
      </LockedAction>
      <KillConfirmDialog scope={scope} active={next} open={open} onOpenChange={setOpen} viewer={viewer} onDone={onDone} />
    </>
  );
}

/** Global kill switch danger panel (admin+). */
export function GlobalKillPanel({ active, perm, viewer, onDone }: { active: boolean; perm: KillPermission; viewer: MockViewer; onDone?: (r: ApplyResult) => void }) {
  const [open, setOpen] = useState(false);
  const locked = active ? !perm.canRelease : !perm.canEngage;
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3',
        active ? 'border-block/50 bg-block/10' : 'border-block/20 bg-[linear-gradient(90deg,rgba(229,68,109,0.06),transparent_60%)]',
      )}
    >
      <div className={cn('grid size-9 place-items-center rounded-lg', active ? 'bg-block text-white' : 'bg-block/10 text-block')}>
        <ShieldAlert className="size-4.5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-text-1">
          Global kill switch{' '}
          <span className={cn('ml-1 rounded-full px-2 py-0.5 text-2xs font-medium', active ? 'bg-block text-white' : 'bg-surface-3 text-text-3')}>{active ? 'ENGAGED' : 'off'}</span>
        </div>
        <div className="text-xs text-text-3">
          {active ? 'Every agent call answers 429 killed until an owner releases it.' : 'Stops every agent in the org within one request. Requires admin; releasing requires owner.'}
        </div>
      </div>
      <LockedAction
        locked={locked}
        reason={active ? 'Releasing the global kill switch requires an owner' : 'Requires admin'}
        variant={active ? 'success' : 'danger'}
        size="sm"
        onClick={() => setOpen(true)}
      >
        {!locked ? active ? <Power className="size-3.5" /> : <PowerOff className="size-3.5" /> : null}
        {active ? 'Release' : 'Kill everything'}
      </LockedAction>
      <KillConfirmDialog scope="global" active={!active} open={open} onOpenChange={setOpen} viewer={viewer} onDone={onDone} />
    </div>
  );
}
