// Approvals inbox (UIG-02): role-filtered list + detail, approve/deny with reason, two-person
// progress, live via SSE (approval.created/updated), ?id=apr_… deep link. Server can_vote/why_not
// drive the locked/unlocked buttons; switching "view as" keeps the selection so the lock → unlock
// transition is visible on stage. Owner: B18-dashboard-gov-approvals.
import { CheckCheck, Clock, Info, ListFilter, TriangleAlert } from '@/components/icons';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { ApprovalRequest } from '@/api/types';
import { ApprovalDetail } from '@/components/governance/approvals/ApprovalDetail';
import { ApprovalList } from '@/components/governance/approvals/ApprovalList';
import { DecideDialog } from '@/components/governance/approvals/DecideDialog';
import { isMine, resolveVote, sortInbox, sponsorIdOf, type InboxTab, type KindFilter, type VoteState } from '@/components/governance/approvals/util';
import { useApproval, useApprovalRules, useApprovals, useDirectory, useNow, useViewer } from '@/components/governance/hooks';
import { floodSignals, floodText, requesterKey } from '@/components/governance/lib/approval-review';
import { firstName, kindLabel } from '@/components/governance/lib/format-gov';
import { PersonaSwitcher } from '@/components/governance/PersonaSwitcher';
import { MockBadge, PageHeader } from '@/components/shell';
import { ROLE_COLORS } from '@/lib/colors';
import type { PageMeta } from '@/lib/page';
import { cn } from '@/lib/utils';

export const meta: PageMeta = {
  path: '/governance/approvals',
  title: 'Approvals',
  icon: 'Inbox',
  section: 'Governance',
  order: 10,
  minRole: 'member',
  badge: 'approvals',
  shortcut: 'g a',
  description: 'Agent actions and config changes waiting for the right role',
};

const TABS: { id: InboxTab; label: string }[] = [
  { id: 'needs', label: 'Needs you' },
  { id: 'pending', label: 'All pending' },
  { id: 'mine', label: 'Requested by me' },
  { id: 'history', label: 'History' },
];

const KINDS: { id: KindFilter; label: string }[] = [
  { id: 'all', label: 'All kinds' },
  { id: 'action', label: kindLabel('action') },
  { id: 'config_change', label: kindLabel('config_change') },
  { id: 'budget_raise', label: kindLabel('budget_raise') },
  { id: 'mcp_pin', label: kindLabel('mcp_pin') },
];

function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable || Boolean(t.closest('[role="dialog"]'));
}

export default function ApprovalsPage() {
  const { viewerId, role, viewer, member } = useViewer();
  const dir = useDirectory();
  const rules = useApprovalRules();
  const list = useApprovals('all');
  const now = useNow(5000);
  const [mountedAt] = useState(() => Date.now());
  const [params, setParams] = useSearchParams();
  const paramId = params.get('id');
  const [tabChoice, setTabChoice] = useState<InboxTab | null>(null);
  const [kind, setKind] = useState<KindFilter>('all');
  const [decide, setDecide] = useState<{ mode: 'approve' | 'deny'; open: boolean }>({ mode: 'approve', open: false });

  // Server can_vote/why_not are only trusted for the viewer they were fetched for.
  const [stamp, setStamp] = useState<{ data: unknown; viewer: string | null }>({ data: list.data, viewer: viewerId });
  if (stamp.data !== list.data) setStamp({ data: list.data, viewer: viewerId });
  const serverFresh = Boolean(list.data) && stamp.viewer === viewerId;

  const all = useMemo(() => list.data?.items ?? [], [list.data]);
  const inList = paramId ? all.find((a) => a.id === paramId) : undefined;
  const single = useApproval(paramId && list.data && !inList ? paramId : null);
  const items = useMemo(() => {
    const extra = single.data && !all.some((a) => a.id === single.data?.id) ? [single.data] : [];
    return sortInbox([...extra, ...all]);
  }, [all, single.data]);

  const votes = useMemo(() => {
    const m = new Map<string, VoteState>();
    for (const r of items) m.set(r.id, resolveVote(r, viewer, dir, serverFresh, now));
    return m;
  }, [items, viewer, dir, serverFresh, now]);

  // ASI09 anti-fatigue: requesters with a burst of approval requests (>= 5 in 5 min).
  const floods = useMemo(() => floodSignals(items, now), [items, now]);
  const floodOf = (r: ApprovalRequest | null) => (r ? (floods.get(requesterKey(r)) ?? null) : null);

  const byKind = (r: ApprovalRequest) => kind === 'all' || r.kind === kind;
  const pending = items.filter((r) => r.status === 'pending');
  const needs = pending.filter((r) => votes.get(r.id)?.ok);
  const mine = items.filter((r) => isMine(r, viewerId, dir));
  const history = items.filter((r) => r.status !== 'pending');
  const tab: InboxTab = tabChoice ?? (needs.length > 0 ? 'needs' : 'pending');
  const visible = (tab === 'needs' ? needs : tab === 'pending' ? pending : tab === 'mine' ? mine : history).filter(byKind);
  const counts: Record<InboxTab, number> = { needs: needs.length, pending: pending.length, mine: mine.filter((r) => r.status === 'pending').length, history: history.length };

  const selectedId = paramId ?? visible[0]?.id ?? null;
  const selected = selectedId ? (items.find((r) => r.id === selectedId) ?? null) : null;
  const selectedVote = selected ? (votes.get(selected.id) ?? null) : null;

  const select = (id: string) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        n.set('id', id);
        return n;
      },
      { replace: true },
    );

  const expiringSoon = pending.filter((r) => r.expires_at && Date.parse(r.expires_at) - now < 5 * 60_000).length;
  const today = new Date(now).toDateString();
  const decidedToday = history.filter((r) => r.decided_at && new Date(r.decided_at).toDateString() === today).length;
  const viewerName = member?.name ?? dir.nameOf(viewerId);
  const viewerFirst = firstName(dir.memberById.get(viewerId ?? '')?.name ?? viewerName);

  // keyboard: j/k move · a approve · d deny (UIG-13)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e)) return;
      const idx = visible.findIndex((r) => r.id === selectedId);
      if (e.key === 'j' || e.key === 'ArrowDown') {
        const next = visible[Math.min(visible.length - 1, idx + 1)];
        if (next) {
          e.preventDefault();
          select(next.id);
        }
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        const prev = visible[Math.max(0, idx - 1)];
        if (prev) {
          e.preventDefault();
          select(prev.id);
        }
      } else if ((e.key === 'a' || e.key === 'd') && selected && selected.status === 'pending' && selectedVote?.ok) {
        e.preventDefault();
        setDecide({ mode: e.key === 'a' ? 'approve' : 'deny', open: true });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const emptyText =
    tab === 'needs'
      ? `Nothing needs a decision from ${viewerFirst || 'you'} (${role})`
      : tab === 'mine'
        ? 'You have not requested anything'
        : tab === 'history'
          ? 'No decided requests yet'
          : 'Nothing pending';

  return (
    <div>
      <PageHeader
        title="Approvals"
        icon="Inbox"
        badge={list.isMock ? <MockBadge /> : undefined}
        subtitle="Agent actions and config changes, routed to the role allowed to approve them by action type, amount and scope. Every decision is audited."
        actions={<PersonaSwitcher />}
      />

      {role === 'member' ? (
        <div className="mb-4 flex items-start gap-2.5 rounded-md border border-border bg-surface-1 px-3 py-2.5 sm:px-4">
          <Info className="mt-0.5 size-4 shrink-0 text-text-3" />
          <div className="text-[12.5px] leading-5">
            <span className="font-medium text-text-1">Viewing as a member{member ? ` (${member.name})` : ''}.</span>{' '}
            <span className="text-text-2">
              Members self-approve their own agents' <span className="font-mono text-text-1">self</span>-level items (e.g. spend ≤ $20). Admin- and owner-level items stay locked with
              the reason shown: separation of duties means a sponsor never approves their own agent's request.
            </span>
          </div>
        </div>
      ) : null}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex max-w-full items-center gap-0.5 overflow-x-auto rounded-md border border-border bg-surface-1 p-0.5" role="tablist" aria-label="Inbox">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTabChoice(t.id)}
              className={cn(
                'flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[5px] px-2.5 text-[12.5px] transition-colors sm:h-7',
                tab === t.id ? 'bg-surface-3 text-text-1 shadow-[inset_0_0_0_1px_var(--border-strong)]' : 'text-text-3 hover:text-text-1',
              )}
            >
              {t.label}
              <span
                className={cn(
                  'min-w-[18px] rounded-sm px-1 text-center text-2xs tabular',
                  t.id === 'needs' && counts.needs > 0 ? 'bg-approval/20 text-approval' : 'bg-surface-4 text-text-3',
                )}
              >
                {counts[t.id]}
              </span>
            </button>
          ))}
        </div>
        <label className="relative flex items-center">
          <ListFilter className="pointer-events-none absolute left-2 size-3.5 text-text-3" />
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as KindFilter)}
            className="h-9 appearance-none rounded-md border border-border bg-surface-1 pl-7 pr-3 text-[12.5px] text-text-2 hover:border-border-strong sm:h-8"
            aria-label="Filter by kind"
          >
            {KINDS.map((k) => (
              <option key={k.id} value={k.id}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <span className="grow" />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-3">
          <span className={cn('inline-flex items-center gap-1.5', expiringSoon > 0 && 'text-block')}>
            <Clock className="size-3.5" />
            <span className={cn('tabular', expiringSoon > 0 ? 'text-block' : 'text-text-1')}>{expiringSoon}</span> expiring within 5 min
          </span>
          <span className="inline-flex items-center gap-1.5">
            <CheckCheck className="size-3.5" />
            <span className="tabular text-text-1">{decidedToday}</span> decided today
          </span>
        </div>
      </div>

      {floods.size > 0 ? (
        <div data-testid="flood-banner" role="alert" className="mb-3 space-y-1 rounded-md border border-block/40 bg-block/10 px-3 py-2.5 sm:px-4">
          {[...floods.values()].map((f) => (
            <div key={f.key} className="flex items-start gap-2 text-[12.5px]">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-block" />
              <span>
                <span className="font-mono font-medium text-block">{f.label}</span> <span className="font-medium text-block">{floodText(f)}.</span>{' '}
                <span className="text-text-2">Approval fatigue is an attack: review each request individually{f.pending ? ` (${f.pending} still pending)` : ''}; approvals from this requester need a typed confirmation.</span>
              </span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="grid min-w-0 items-start gap-3 lg:grid-cols-[minmax(320px,420px)_minmax(0,1fr)]">
        <section className="min-w-0 overflow-hidden rounded-lg border border-border bg-card shadow-card">
          <div className="flex items-center justify-between border-b border-border-subtle px-4 py-2 text-2xs uppercase tracking-wider text-text-3">
            <span>
              {TABS.find((t) => t.id === tab)?.label} · {visible.length}
            </span>
            <span className="inline-flex items-center gap-1 normal-case tracking-normal">
              viewing as
              <span className="font-medium" style={{ color: ROLE_COLORS[role].fg }}>
                {viewerFirst || role}
              </span>
            </span>
          </div>
          <div className="max-h-[50vh] overflow-y-auto lg:max-h-[calc(100vh-260px)]">
            <ApprovalList
              items={visible}
              votes={votes}
              selectedId={selectedId}
              freshIds={new Set(items.filter((r) => Date.parse(r.created_at) > mountedAt).map((r) => r.id))}
              dir={dir}
              flooded={new Set(floods.keys())}
              loading={list.loading}
              empty={list.error && !list.data ? 'Approvals could not be loaded' : emptyText}
              onSelect={select}
            />
          </div>
          {list.error && !list.data ? (
            <div className="flex items-center gap-2 border-t border-border-subtle px-4 py-2 text-xs text-text-2">
              <span className="min-w-0 flex-1 truncate" title={list.error.message}>
                <span className="text-block">Could not load approvals.</span> {list.error.message}
              </span>
              <button type="button" onClick={() => list.refresh()} className="h-7 shrink-0 rounded-md border border-border bg-surface-2 px-2 text-text-1 hover:border-border-strong">
                Retry
              </button>
            </div>
          ) : null}
        </section>

        <section className="flex min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-card shadow-card lg:sticky lg:top-[calc(var(--topbar-h)+12px)] lg:max-h-[max(480px,calc(100vh-340px))]">
          <ApprovalDetail
            req={selected}
            vote={selectedVote}
            rule={selected?.rule_id ? rules.ruleById.get(selected.rule_id) : undefined}
            dir={dir}
            viewer={viewer}
            viewerName={viewerName}
            onDecide={(mode) => setDecide({ mode, open: true })}
            onChanged={() => list.refresh()}
            flood={floodOf(selected)}
            emptyHint={tab === 'needs' ? `Nothing is waiting for ${viewerFirst || 'you'}. Switch persona or open "All pending".` : undefined}
          />
        </section>
      </div>

      <DecideDialog
        req={selected}
        mode={decide.mode}
        open={decide.open && Boolean(selected)}
        onOpenChange={(open) => setDecide((d) => ({ ...d, open }))}
        viewer={viewer}
        viewerName={viewerName}
        sponsorId={selected ? sponsorIdOf(selected, dir) : null}
        flood={floodOf(selected)}
        onDone={() => list.refresh()}
      />
    </div>
  );
}
