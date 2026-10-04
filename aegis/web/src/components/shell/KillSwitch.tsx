// Topbar kill switch (UIS-18): admin+ only. Dialog with scope picker (global / team / agent), reason, then
// POST /api/killswitch → ApplyResult (applied | pending_approval → approval link | 403 → reason).
// The killbar itself is rendered by SystemBanners from /api/budgets + `killswitch` SSE events.
import { Bot, Globe, Power, Users } from '@/components/icons';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { api, isApiRequestError } from '@/api/client';
import { useApi, useViewAs } from '@/api/hooks';
import type { Agent, ApplyResult } from '@/api/types';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { VIEW_ROLE_RANK } from '@/lib/page';
import { cn } from '@/lib/utils';
import { mockAgents } from '@/mocks/shell/org';
import { LiveDot } from './LiveDot';
import { killActive, killScopes, useShellState } from './shellStore';

export function KillSwitchButton() {
  const { role } = useViewAs();
  const kill = useShellState((s) => s.kill);
  const [open, setOpen] = useState(false);
  const active = killActive(kill);
  if (VIEW_ROLE_RANK[role] < VIEW_ROLE_RANK.admin && !active) return null;
  return (
    <>
      <Button variant="danger-ghost" size="sm" onClick={() => setOpen(true)} className="h-[26px] shrink-0 gap-1.5 px-2.5 text-xs max-[1360px]:px-2 max-md:w-9 max-md:px-0">
        {active ? <LiveDot tone="bad" /> : <Power className="size-3.5" />}
        <span className="max-[1360px]:hidden">{active ? 'Kill switch on' : 'Kill switch'}</span>
      </Button>
      {open ? <KillDialog open={open} onOpenChange={setOpen} activeScopes={killScopes(kill)} canAct={VIEW_ROLE_RANK[role] >= VIEW_ROLE_RANK.admin} /> : null}
    </>
  );
}

function KillDialog({ open, onOpenChange, activeScopes, canAct }: { open: boolean; onOpenChange: (o: boolean) => void; activeScopes: string[]; canAct: boolean }) {
  const agents = useApi<{ items: Agent[] }>('/api/agents', { mock: mockAgents });
  const [scope, setScope] = useState('agent:chaos-agent@platform');
  const [reason, setReason] = useState('Runaway behaviour observed on the Command Center');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const options = [
    { value: 'global', label: 'Everything', hint: 'all agents, all teams — in-flight streams cancelled', icon: Globe },
    ...['trading', 'research', 'platform'].map((t) => ({ value: `team:${t}`, label: `Team ${t}`, hint: 'every agent in the team', icon: Users })),
    ...(agents.data?.items ?? []).map((a) => ({ value: `agent:${a.id}`, label: a.id, hint: a.name, icon: Bot })),
  ];
  const isActive = activeScopes.includes(scope);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post<ApplyResult>('/api/killswitch', { scope, active: !isActive, reason });
      if (r.data.status === 'pending_approval') {
        toast(`Kill switch change needs ${r.data.approval?.required_role ?? 'approval'}`, {
          className: 'aegis-toast aegis-toast-approval',
          description: r.data.message,
          action: r.data.approval ? { label: 'Review', onClick: () => navigate(`/governance/approvals?id=${r.data.approval?.id}`) } : undefined,
        });
      } else if (r.data.status === 'applied' || r.data.status === 'noop') {
        toast.success(isActive ? `Kill switch released · ${scope}` : `Kill switch engaged · ${scope}`, { className: 'aegis-toast', description: r.data.message || undefined });
      } else {
        toast.error(`Kill switch ${r.data.status}`, { className: 'aegis-toast', description: r.data.message });
      }
      onOpenChange(false);
    } catch (e) {
      const msg = isApiRequestError(e) ? e.message : 'Gateway unreachable';
      toast.error('Kill switch not applied', { className: 'aegis-toast', description: msg });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[520px] sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-md">
            <span className="grid size-7 place-items-center rounded-md border border-block/30 bg-block/10 text-block">
              <Power className="size-4" />
            </span>
            Kill switch
          </DialogTitle>
          <DialogDescription>Stops matching traffic at the gateway instantly (429 killed). Goes through policy governance — tightening needs admin.</DialogDescription>
        </DialogHeader>
        <div className="flex max-h-[300px] flex-col gap-1 overflow-y-auto">
          {options.map((o) => {
            const Icon = o.icon;
            const on = scope === o.value;
            const engaged = activeScopes.includes(o.value);
            return (
              <button
                type="button"
                key={o.value}
                onClick={() => setScope(o.value)}
                className={cn('flex items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors', on ? 'border-block/40 bg-block/[0.07]' : 'border-border bg-surface-2 hover:border-border-strong')}
              >
                <span className={cn('grid size-4 place-items-center rounded-full border', on ? 'border-block' : 'border-border-strong')}>{on ? <span className="size-2 rounded-full bg-block" /> : null}</span>
                <Icon className="size-4 text-text-3" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-[12.5px] text-text-1">{o.label}</span>
                  <span className="block truncate text-[11.5px] text-text-3">{o.hint}</span>
                </span>
                {engaged ? <span className="rounded-full border border-block/30 bg-block/10 px-1.5 text-[10.5px] font-medium text-block">engaged</span> : null}
              </button>
            );
          })}
        </div>
        <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="Reason (audited)" />
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant={isActive ? 'secondary' : 'danger'} disabled={busy || !canAct || !reason.trim()} onClick={() => void submit()}>
            <Power className="size-3.5" />
            {busy ? 'Applying…' : isActive ? 'Release' : 'Engage kill switch'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
