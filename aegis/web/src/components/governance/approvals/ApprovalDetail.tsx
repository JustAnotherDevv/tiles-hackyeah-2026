// Approval detail pane: header, requester, bound payload, why-this-role, routing, votes and the
// role-aware footer (Approve/Deny unlock or lock with the reason as the "view as" persona changes).
// Owner: B18-dashboard-gov-approvals.
import { displayTitle } from '@/components/governance/lib/format-gov';
import { motion } from 'framer-motion';
import { Check, Copy, ExternalLink, Hash, Inbox, Lock, LockOpen, Undo2, Users, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import type { ApprovalRequest, ApprovalRuleView } from '@/api/types';
import { EmptyState, RoleBadge, TimeAgo } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { ApproverBadge } from '../ApproverBadge';
import { ExpiryCountdown } from '../ExpiryCountdown';
import { errorTitle, govApi, parseApiError } from '../gov-api';
import type { Directory } from '../hooks';
import { approveLabel, roleSatisfies, type Viewer } from '../lib/eligibility';
import { kindLabel, statusMeta } from '../lib/format-gov';
import { LockedAction } from '../LockedAction';
import { MemberAvatar } from '../MemberAvatar';
import { RequesterLine } from '../RequesterLine';
import { TwoPersonProgress } from '../TwoPersonProgress';
import { PayloadView } from './PayloadView';
import { RoutingSteps } from './RoutingSteps';
import { sponsorIdOf, toastDecision, type VoteState } from './util';
import { WhyRole } from './WhyRole';

function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn('border-t border-border-subtle px-5 py-4', className)}>
      <div className="mb-2.5 text-2xs font-medium uppercase tracking-wider text-text-3">{title}</div>
      {children}
    </section>
  );
}

const LABEL_TONE: Record<string, string> = {
  RESTRICTED: 'text-block border-block/30 bg-block/10',
  SECRET: 'text-block border-block/30 bg-block/10',
  CONFIDENTIAL: 'text-redact border-redact/30 bg-redact/10',
  prod: 'text-block border-block/30 bg-block/10',
  critical: 'text-block border-block/30 bg-block/10',
};

export interface ApprovalDetailProps {
  req: ApprovalRequest | null;
  vote: VoteState | null;
  rule: ApprovalRuleView | undefined;
  dir: Directory;
  viewer: Viewer;
  viewerName: string;
  onDecide: (mode: 'approve' | 'deny') => void;
  onChanged: (res: ApprovalRequest) => void;
  emptyHint?: ReactNode;
}

export function ApprovalDetail({ req, vote, rule, dir, viewer, viewerName, onDecide, onChanged, emptyHint }: ApprovalDetailProps) {
  const [cancelling, setCancelling] = useState(false);
  if (!req || !vote) {
    return (
      <div className="grid min-h-[420px] place-items-center">
        <EmptyState icon={Inbox} title="Inbox zero" hint={emptyHint ?? 'Nothing selected. New requests appear here in real time.'} />
      </div>
    );
  }
  const pending = req.status === 'pending';
  const st = statusMeta(req.status);
  const sponsorId = sponsorIdOf(req, dir);
  const isRequester = viewer.member_id !== null && sponsorId === viewer.member_id;
  const canCancel = pending && (isRequester || roleSatisfies(viewer.role, 'admin'));
  const labels = Object.entries(req.labels ?? {}).filter(([k]) => ['sensitivity', 'env', 'data_class', 'control_severity', 'recurring', 'scope', 'dest', 'loosening'].includes(k));
  const decidedNoButtons = req.required_role === 'deny' || req.required_role === 'auto';

  async function cancel() {
    if (!req) return;
    setCancelling(true);
    try {
      const res = await govApi.cancel(req.id, viewer.member_id);
      toastDecision(res.data, 'cancel', viewerName);
      onChanged(res.data);
    } catch (e) {
      const p = parseApiError(e);
      toast.error(errorTitle(p), { id: `apr-${req.id}`, description: p.message });
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
    <motion.div key={req.id} className="min-h-0 flex-1 overflow-y-auto" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}>
      {/* header */}
      <div className="px-5 pb-4 pt-[18px]">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="inline-flex h-5 items-center rounded-sm border border-border bg-surface-2 px-1.5 text-2xs font-medium uppercase tracking-wide text-text-2">{kindLabel(req.kind)}</span>
          <span className="inline-flex h-5 items-center rounded-sm border border-border bg-surface-2 px-1.5 font-mono text-2xs text-text-2">{req.action_type}</span>
          <ApproverBadge level={req.required_role} />
          {req.two_person ? (
            <span className="inline-flex h-5 items-center gap-1 rounded-full border border-accent-fg/30 bg-brand/10 px-2 text-xs text-accent-fg">
              <Users className="size-3" /> Two-person rule
            </span>
          ) : null}
          {!pending ? <span className={cn('inline-flex h-5 items-center rounded-full border px-2 text-xs font-medium', st.tone === 'allow' ? 'border-allow/30 bg-allow/10 text-allow' : st.tone === 'block' ? 'border-block/30 bg-block/10 text-block' : 'border-log/30 bg-log/10 text-log')}>{st.label}</span> : null}
          {labels.map(([k, v]) => (
            <span key={k} className={cn('inline-flex h-5 items-center rounded-sm border px-1.5 font-mono text-2xs', LABEL_TONE[v] ?? 'border-border bg-surface-2 text-text-3')}>
              {k}: {v}
            </span>
          ))}
          <span className="grow" />
          <button
            type="button"
            className="inline-flex items-center gap-1 font-mono text-2xs text-text-3 hover:text-text-1"
            title="Copy id"
            onClick={() => {
              void navigator.clipboard?.writeText(req.id).then(() => toast.success('Copied', { description: req.id, duration: 1500 }));
            }}
          >
            <Hash className="size-3" />
            {req.id}
            <Copy className="size-3" />
          </button>
        </div>
        <h2 className="mb-1 mt-2.5 text-[17px] font-semibold leading-6 tracking-[-0.015em] text-text-1">{displayTitle(req.title)}</h2>
        {req.summary ? <p className="mb-2 text-[12.5px] text-text-3">{req.summary}</p> : null}
        <RequesterLine req={req} dir={dir} />
      </div>

      <Section title="Requested action · bound parameters (what will actually run)">
        <PayloadView req={req} hideActionLabel />
      </Section>

      <Section title="Why this role?">
        <WhyRole req={req} rule={rule} dir={dir} viewerId={viewer.member_id} vote={vote} />
      </Section>

      <Section title="Routing">
        <RoutingSteps req={req} dir={dir} />
        {req.two_person ? (
          <div className="mt-3 flex items-center gap-2 text-xs text-text-3">
            <TwoPersonProgress votes={req.votes} memberById={dir.memberById} showAvatars size="md" />
            <span>two distinct approvers; at least one {req.required_role}</span>
          </div>
        ) : null}
      </Section>

      {req.votes.length > 0 || req.decided_at ? (
        <Section title="Votes & audit trail">
          <ol className="space-y-2">
            {req.votes.map((v) => {
              const m = dir.memberById.get(v.member_id);
              return (
                <li key={`${v.member_id}-${v.ts}`} className="flex items-start gap-2.5 text-[12.5px]">
                  <MemberAvatar member={m} name={v.member_id} size="sm" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-medium text-text-1">{m?.name ?? v.member_id}</span>
                      <RoleBadge role={v.role} />
                      <span className={cn('inline-flex items-center gap-0.5 text-xs font-medium', v.decision === 'approve' ? 'text-allow' : 'text-block')}>
                        {v.decision === 'approve' ? <Check className="size-3" /> : <X className="size-3" />}
                        {v.decision === 'approve' ? 'approved' : 'denied'}
                      </span>
                      <span className="text-xs">
                        <TimeAgo ts={v.ts} />
                      </span>
                    </div>
                    {v.comment ? <div className="mt-0.5 text-text-2">“{v.comment}”</div> : null}
                  </div>
                </li>
              );
            })}
            {req.decided_at && req.votes.length === 0 ? (
              <li className="text-xs text-text-3">
                {st.label} <TimeAgo ts={req.decided_at} /> {req.required_role === 'deny' ? `by rule ${req.rule_id}` : req.status === 'expired' ? '(TTL elapsed ⇒ denied)' : ''}
              </li>
            ) : null}
            {req.decision_id ? (
              <li className="pt-1 text-xs text-text-3">
                Originating decision{' '}
                <Link to={`/security/decisions/${req.decision_id}`} className="inline-flex items-center gap-0.5 font-mono text-accent-fg hover:underline">
                  {req.decision_id} <ExternalLink className="size-3" />
                </Link>
              </li>
            ) : null}
          </ol>
        </Section>
      ) : null}
    </motion.div>

      {/* footer (pinned) */}
      <div className="flex shrink-0 flex-wrap items-center gap-2.5 border-t border-border bg-surface-1 px-5 py-3">
        {pending ? (
          <>
            <ExpiryCountdown expiresAt={req.expires_at} prefix="Expires in" className="text-xs" />
            {canCancel ? (
              <Button variant="ghost" size="sm" onClick={() => void cancel()} disabled={cancelling} className="text-text-3">
                <Undo2 className="size-3.5" /> Cancel request
              </Button>
            ) : null}
            <span className="grow" />
            {decidedNoButtons ? null : (
                <div key={vote.ok ? 'open' : 'locked'} className="flex items-center gap-2 duration-300 animate-in fade-in-0 zoom-in-95">
                  {vote.ok ? (
                    <span className="hidden items-center gap-1 text-xs text-allow md:inline-flex">
                      <LockOpen className="size-3.5" /> You can decide as {viewerName}
                    </span>
                  ) : (
                    <span className="hidden max-w-[300px] items-center gap-1 truncate text-xs text-text-3 md:inline-flex" title={vote.reason ?? undefined}>
                      <Lock className="size-3.5 shrink-0" /> {vote.reason}
                    </span>
                  )}
                  <LockedAction locked={!vote.ok} reason={vote.reason} variant="ghost" size="sm" className="text-block hover:bg-block/10 hover:text-block" onClick={() => onDecide('deny')}>
                    {vote.ok ? <X className="size-3.5" /> : null}
                    Deny
                  </LockedAction>
                  <LockedAction
                    locked={!vote.ok}
                    reason={vote.reason}
                    size="sm"
                    className={cn(vote.ok ? 'bg-emerald-600 text-white shadow-[0_0_0_3px_rgba(16,185,129,.15)] hover:bg-emerald-500' : 'bg-surface-3 text-text-3')}
                    onClick={() => onDecide('approve')}
                    hint="⌘/Ctrl+Enter in the dialog submits"
                  >
                    {vote.ok ? <Check className="size-3.5" /> : null}
                    {approveLabel(req, viewer, { sponsorId })}
                  </LockedAction>
                </div>
            )}
          </>
        ) : (
          <div className="flex w-full items-center gap-2 text-xs text-text-3">
            <span className={cn('size-1.5 rounded-full', st.tone === 'allow' ? 'bg-allow' : st.tone === 'block' ? 'bg-block' : 'bg-log')} />
            {st.label}
            {req.decided_at ? (
              <>
                <TimeAgo ts={req.decided_at} />
                {req.decided_by.length ? <span>by {req.decided_by.map((id) => dir.memberById.get(id)?.name ?? id).join(' + ')}</span> : null}
              </>
            ) : null}
            <span className="grow" />
            <span>audited as approval.{req.status === 'approved' ? 'granted' : req.status}</span>
          </div>
        )}
      </div>
    </div>
  );
}
