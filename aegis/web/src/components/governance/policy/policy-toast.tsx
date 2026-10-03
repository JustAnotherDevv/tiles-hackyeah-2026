// "Policy v13 hot-reloaded in 184 ms" toast with the change summary and WHICH VERDICTS FLIPPED
// (from the dry-run probes). sonner id `policy-v<version>` so a shell toast with the same id is
// updated in place instead of duplicated. Owner: B19-dashboard-gov-policy.
import { ArrowRight, FlaskConical, ShieldOff, Zap } from 'lucide-react';
import { toast } from 'sonner';
import type { ApplyResult, Identity, PolicyChange } from '@/api/types';
import { eventHub } from '@/api/sse';
import { ActionBadge } from '@/components/shell/ActionBadge';
import type { ProbeFlip } from '@/components/governance/lib/probe-defs';
import { fmtMs } from '@/lib/format';
import { runProbes } from './probe-runner';

export interface PolicyAppliedInfo {
  version: number;
  previous_version: number | null;
  source: string;
  actor: Identity | null;
  changes: PolicyChange[];
  latency_ms: number | null;
}

/** Navigate inside the SPA without a hook (works from toasts mounted anywhere). */
export function govNavigate(path: string): void {
  void import('@/router')
    .then((m) => m.router.navigate(path))
    .catch(() => window.location.assign(`${import.meta.env.BASE_URL.replace(/\/$/, '')}${path}`));
}

function FlipRows({ flips }: { flips: ProbeFlip[] }) {
  return (
    <div className="mt-2 rounded-md border border-border bg-surface-1/80 p-2">
      <div className="mb-1 flex items-center gap-1 text-2xs font-medium uppercase tracking-wider text-text-3">
        <FlaskConical className="size-3" /> Verdicts flipped
      </div>
      <ul className="space-y-1">
        {flips.slice(0, 4).map((f) => (
          <li key={f.id} className="flex flex-wrap items-center gap-1.5 text-xs text-text-1">
            <span className="font-medium">{f.label}</span>
            <ActionBadge action={f.before} size="sm" />
            <ArrowRight className="size-3 text-text-3" />
            <ActionBadge action={f.after} size="sm" />
            {f.control ? <span className="font-mono text-2xs text-text-3">{f.control}</span> : null}
          </li>
        ))}
      </ul>
      {flips.length > 4 ? <div className="mt-1 text-2xs text-text-3">+{flips.length - 4} more</div> : null}
    </div>
  );
}

function ChangeRows({ changes }: { changes: PolicyChange[] }) {
  if (changes.length === 0) return null;
  return (
    <ul className="mt-1 space-y-0.5">
      {changes.slice(0, 3).map((c, i) => (
        <li key={`${c.path}-${i}`} className={`flex items-center gap-1 font-mono text-2xs ${c.loosening ? 'text-block' : 'text-text-2'}`}>
          {c.loosening ? <ShieldOff className="size-3 shrink-0" /> : null}
          <span className="truncate">{c.summary || `${c.kind} ${c.path}`}</span>
        </li>
      ))}
      {changes.length > 3 ? <li className="text-2xs text-text-3">+{changes.length - 3} more</li> : null}
    </ul>
  );
}

export function toastPolicyApplied(info: PolicyAppliedInfo, flips: ProbeFlip[] | null): void {
  const who = info.actor?.display_name ?? info.actor?.member_id ?? null;
  const title = `Policy v${info.version} hot-reloaded${info.latency_ms !== null && info.latency_ms !== undefined ? ` in ${fmtMs(info.latency_ms)}` : ''}`;
  toast.success(title, {
    id: `policy-v${info.version}`,
    icon: <Zap className="size-4 text-allow" />,
    duration: flips && flips.length ? 12000 : 7000,
    description: (
      <div className="min-w-[260px]">
        <ChangeRows changes={info.changes} />
        {flips && flips.length ? <FlipRows flips={flips} /> : null}
        <div className="mt-1.5 text-2xs text-text-3">
          {info.previous_version !== null ? `v${info.previous_version} → v${info.version} · ` : ''}
          source {info.source}
          {who ? ` · by ${who}` : ''}
        </div>
      </div>
    ),
    action: { label: 'View', onClick: () => govNavigate('/governance/policy') },
  });
}

const announced = new Set<number>();

/**
 * Announce an applied policy version once: re-run the probes, then toast when verdicts flipped — or
 * always when the shell's SSE toasts can't cover it (offline / mock / `force`).
 */
export async function announcePolicyApplied(info: PolicyAppliedInfo, opts: { mock: boolean; force?: boolean }): Promise<ProbeFlip[]> {
  if (announced.has(info.version)) return [];
  announced.add(info.version);
  const run = await runProbes(info.version, { mock: opts.mock });
  const sseLive = eventHub.status === 'live';
  if (run.flips.length > 0 || !sseLive || opts.force) toastPolicyApplied(info, run.available ? run.flips : null);
  return run.flips;
}

/** Result toasts for the page's own HTTP actions (apply / rollback / raise / kill). */
export function toastApplyResult(
  r: ApplyResult,
  ctx: { what: string; onOpenApproval?: (id: string) => void },
): void {
  const open = (id: string) => (ctx.onOpenApproval ? ctx.onOpenApproval(id) : govNavigate(`/governance/approvals?id=${encodeURIComponent(id)}`));
  switch (r.status) {
    case 'pending_approval': {
      const a = r.approval;
      toast(`Approval requested · routed to ${a?.required_role ?? 'approver'}${a?.rule_id ? ` (${a.rule_id})` : ''}`, {
        id: a ? `apr-${a.id}` : undefined,
        description: (
          <span className="text-xs text-text-2">
            {ctx.what}
            {a ? (
              <>
                {' · '}
                <span className="font-mono text-approval">{a.id}</span>
              </>
            ) : null}
          </span>
        ),
        className: 'border-approval/40',
        duration: 9000,
        action: a ? { label: 'Open', onClick: () => open(a.id) } : undefined,
      });
      break;
    }
    case 'applied':
      toast.success(`${ctx.what} — applied as v${r.version ?? '?'}${r.latency_ms ? ` in ${fmtMs(r.latency_ms)}` : ''}`, { id: r.version ? `policy-v${r.version}` : undefined });
      break;
    case 'rejected': {
      const e = r.errors[0];
      toast.error(r.message || `Rejected — still on v${r.previous_version ?? r.version ?? '?'}`, {
        // same sonner id as the shell's policy.rejected SSE toast → one toast on screen, not two
        id: 'policy-rejected',
        description: e ? `${e.line ? `line ${e.line}${e.col ? `:${e.col}` : ''} — ` : ''}${e.message}` : undefined,
        duration: 9000,
      });
      break;
    }
    case 'conflict':
      toast.warning(r.message || 'Policy changed meanwhile — rebase your draft');
      break;
    case 'noop':
      toast.info(r.message || 'Nothing to change');
      break;
  }
}
