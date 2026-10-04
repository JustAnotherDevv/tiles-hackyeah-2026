// "Why this role?" — matched rule + its condition, the explanation paragraph, eligible approvers
// (viewer highlighted) and the server's why_not verbatim when locked. Owner: B18.
import { Ban, FileCode, Lock, Users } from '@/components/icons';
import type { ApprovalRequest, ApprovalRuleView } from '@/api/types';
import { cn } from '@/lib/utils';
import { ApproverBadge } from '../ApproverBadge';
import type { Directory } from '../hooks';
import { eligibleApprovers, explainLevel } from '../lib/eligibility';
import { firstName } from '../lib/format-gov';
import { MemberAvatar } from '../MemberAvatar';
import { sponsorIdOf, type VoteState } from './util';

export function WhyRole({ req, rule, dir, viewerId, vote }: { req: ApprovalRequest; rule: ApprovalRuleView | undefined; dir: Directory; viewerId: string | null; vote: VoteState }) {
  const sponsorId = sponsorIdOf(req, dir);
  const sponsor = sponsorId ? dir.memberById.get(sponsorId) : undefined;
  const eligible = req.required_role === 'deny' || req.required_role === 'auto' ? [] : eligibleApprovers(req, dir.members, { sponsorId });
  const text = explainLevel(req, {
    sponsorName: sponsor?.name ?? sponsorId,
    requesterName: req.requester.display_name ?? sponsor?.name ?? null,
    ruleText: rule?.when ?? null,
  });
  const voted = new Set(req.votes.map((v) => v.member_id));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex h-6 items-center gap-1.5 rounded-md border border-border bg-surface-2 px-2 font-mono text-xs text-text-1">
          <FileCode className="size-3 text-accent-fg" />
          {req.rule_id ?? 'default route'}
        </span>
        {rule?.when ? <span className="font-mono text-xs text-text-3">{rule.when}</span> : null}
        <span className="text-text-4">→</span>
        <ApproverBadge level={req.required_role} size="sm" />
        {req.two_person ? (
          <span className="inline-flex h-[18px] items-center gap-1 rounded-sm border border-border bg-surface-2 px-1.5 text-2xs text-text-1">
            <Users className="size-2.5" /> two-person
          </span>
        ) : null}
      </div>
      {rule?.description ? <div className="text-xs text-text-3">{rule.description}</div> : null}
      <p className="text-[13px] leading-5 text-text-2">{text}</p>

      {req.required_role === 'deny' ? (
        <div className="flex items-center gap-2 rounded-md border border-block/30 bg-block/5 px-3 py-2 text-[12.5px] text-block">
          <Ban className="size-4 shrink-0" />
          No one can approve this: rule {req.rule_id ?? '(default)'} denies it, so there are no decision buttons.
        </div>
      ) : eligible.length > 0 ? (
        <div>
          <div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-text-3">Eligible approvers</div>
          <div className="flex flex-wrap gap-1.5">
            {eligible.map((m) => {
              const me = m.id === viewerId;
              return (
                <span
                  key={m.id}
                  className={cn(
                    'inline-flex h-7 items-center gap-1.5 rounded-md border px-1 pr-2.5 text-xs',
                    me ? 'border-border-strong bg-surface-3 text-text-1' : 'border-border bg-surface-2 text-text-2',
                  )}
                  title={`${m.name} · ${m.role}${me ? ' · you' : ''}`}
                >
                  <MemberAvatar member={m} size="xs" />
                  {firstName(m.name)}
                  <span className="text-2xs text-text-3">{m.role}</span>
                  {me ? <span className="text-2xs font-medium text-text-2">(you)</span> : null}
                </span>
              );
            })}
            {req.votes
              .filter((v) => !eligible.some((m) => m.id === v.member_id) && voted.has(v.member_id))
              .map((v) => (
                <span key={`v-${v.member_id}`} className="inline-flex h-7 items-center gap-1.5 rounded-md border border-allow/30 bg-allow/5 px-1 pr-2.5 text-xs text-text-3 line-through decoration-text-4">
                  <MemberAvatar member={dir.memberById.get(v.member_id)} name={v.member_id} size="xs" />
                  {firstName(dir.memberById.get(v.member_id)?.name ?? v.member_id)} voted
                </span>
              ))}
          </div>
        </div>
      ) : null}

      {!vote.ok && req.status === 'pending' && req.required_role !== 'deny' && vote.reason ? (
        <div className="flex items-start gap-2 rounded-lg border border-dashed border-border-strong bg-surface-2 px-3 py-2.5 text-[12.5px] text-text-2">
          <Lock className="mt-0.5 size-3.5 shrink-0 text-text-3" />
          <span>
            {vote.reason}
          </span>
        </div>
      ) : null}
    </div>
  );
}
