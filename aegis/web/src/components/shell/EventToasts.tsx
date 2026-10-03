// Global SSE → toast bridge (docs/plan/15 §2.8 + Addendum A-55). The shell toasts feed.*, budget.threshold,
// mcp.tool and system. It ALSO keeps the plain policy.* / approval.* / killswitch toasts because the
// governance <GovernanceToaster/> (mounted once in AppShell) only adds the "verdicts flipped" variant and
// relies on these: the policy toast uses sonner id `policy-v<version>`, so governance updates it in place
// (never two toasts for one version). Pages must not duplicate any of these.
// Dedupe: same kind + subject within 2 s (sonner id); at most 4 visible (Toaster visibleToasts).
// Replayed messages (first ~1.5 s after (re)connect) never toast.
import { useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { getMember, invalidateApi, useEvents } from '@/api/hooks';
import type { SseEventMap, SseEventName } from '@/api/types';
import { ROLE_COLORS } from '@/lib/colors';
import { fmtMs } from '@/lib/format';
import { applyKillEvent, getShellState, setShellState } from './shellStore';

const NAMES: SseEventName[] = [
  'policy.applied',
  'policy.rejected',
  'feed.updated',
  'feed.rejected',
  'approval.created',
  'approval.updated',
  'budget.threshold',
  'killswitch',
  'mcp.tool',
  'system',
];

function Meta({ children }: { children: React.ReactNode }) {
  return <div className="mt-1.5 font-mono text-[11px] text-text-3">{children}</div>;
}

function actorName(a: { display_name?: string | null; member_id: string | null; agent_id: string | null } | null): string {
  if (!a) return 'file watcher';
  return getMember(a.member_id)?.name ?? a.display_name ?? a.member_id ?? a.agent_id ?? 'unknown';
}

export function EventToasts() {
  const navigate = useNavigate();
  const recent = useRef(new Map<string, number>());

  const dedupe = (key: string): boolean => {
    const now = Date.now();
    const last = recent.current.get(key);
    recent.current.set(key, now);
    if (recent.current.size > 200) recent.current.clear();
    return last !== undefined && now - last < 2000;
  };

  useEvents(NAMES, (name, data, meta) => {
    // state updates happen even for replayed events; toasts only for fresh ones
    if (name === 'feed.updated') {
      const d = data as SseEventMap['feed.updated'];
      setShellState({ feedRejected: null, feedBadge: { kind: 'new', count: Math.max(1, d.added + d.modified), until: Date.now() + 10_000 } });
      setTimeout(() => {
        const b = getShellState().feedBadge;
        if (b?.kind === 'new' && b.until <= Date.now()) setShellState({ feedBadge: null });
      }, 10_200);
    }
    if (name === 'feed.rejected') {
      const d = data as SseEventMap['feed.rejected'];
      setShellState({ feedBadge: { kind: 'error' }, feedRejected: { reason: d.reason, keptSerial: d.kept_serial, attempted: d.serial_attempted, at: Date.now() } });
    }
    if (name === 'killswitch') {
      const d = data as SseEventMap['killswitch'];
      setShellState((s) => ({ kill: applyKillEvent(s.kill, d.scope, d.active), killActor: actorName(d.actor) }));
    }
    if (name === 'policy.applied') invalidateApi('/api/controls');
    if (meta.replay) return;

    switch (name) {
      case 'policy.applied': {
        const d = data as SseEventMap['policy.applied'];
        if (dedupe(`policy.applied:${d.version}`)) return;
        const changes = d.changes ?? [];
        const summary = changes
          .slice(0, 2)
          .map((c) => c.summary)
          .join(' · ');
        const more = changes.length > 2 ? ` (+${changes.length - 2} more)` : '';
        toast.success(`Policy v${d.version} applied in ${fmtMs(d.latency_ms)}`, {
          id: `policy-v${d.version}`,
          className: 'aegis-toast',
          duration: 7000,
          description: (
            <>
              <div>{summary ? `${summary}${more}` : 'Hot-reloaded — no semantic changes'}</div>
              <Meta>
                policy.applied · {d.source} · {actorName(d.actor)}
              </Meta>
            </>
          ),
          action: { label: 'View', onClick: () => navigate('/governance/policy') },
        });
        return;
      }
      case 'policy.rejected': {
        const d = data as SseEventMap['policy.rejected'];
        const e = d.errors?.[0];
        if (dedupe(`policy.rejected:${e?.message ?? ''}`)) return;
        toast.error(`Policy change rejected — still on v${d.kept_version}`, {
          id: 'policy-rejected',
          className: 'aegis-toast',
          duration: 9000,
          description: (
            <>
              <div>{e ? `${e.line !== null ? `line ${e.line}${e.col !== null ? `:${e.col}` : ''} · ` : ''}${e.message}` : 'Validation failed'}</div>
              <Meta>policy.rejected · {d.source}</Meta>
            </>
          ),
          action: { label: 'Open editor', onClick: () => navigate('/governance/policy') },
        });
        return;
      }
      case 'feed.updated': {
        const d = data as SseEventMap['feed.updated'];
        if (dedupe(`feed.updated:${d.serial}`)) return;
        toast.success(`Threat feed #${d.serial ?? '?'} verified ✓`, {
          id: `feed-${d.serial}`,
          className: 'aegis-toast',
          description: (
            <>
              <div>
                +{d.added} added · −{d.removed} removed · ~{d.modified} modified
              </div>
              <Meta>feed.updated · Ed25519 {d.key_id ?? ''}</Meta>
            </>
          ),
          action: { label: 'Threats', onClick: () => navigate('/security/threats') },
        });
        return;
      }
      case 'feed.rejected': {
        const d = data as SseEventMap['feed.rejected'];
        if (dedupe(`feed.rejected:${d.serial_attempted}`)) return;
        toast.error('Threat feed update rejected', {
          id: 'feed-rejected',
          className: 'aegis-toast',
          duration: 9000,
          description: (
            <>
              <div>
                {d.reason} — enforcement stays on #{d.kept_serial ?? '?'}
              </div>
              <Meta>feed.rejected · serial {d.serial_attempted ?? '?'}</Meta>
            </>
          ),
        });
        return;
      }
      case 'approval.created': {
        const d = data as SseEventMap['approval.created'];
        if (dedupe(`approval:${d.id}`)) return;
        toast(d.title, {
          id: `apr-${d.id}`,
          className: 'aegis-toast aegis-toast-approval',
          icon: <span className="text-[13px]">✋</span>,
          duration: 8000,
          description: (
            <>
              <div>
                needs {ROLE_COLORS[d.required_role]?.label.toLowerCase() ?? d.required_role}
                {d.two_person ? ' · two-person' : ''}
                {d.amount_usd !== null ? ` · $${d.amount_usd.toFixed(2)}` : ''}
              </div>
              <Meta>approval.created · {d.requester.agent_id ?? actorName(d.requester)}</Meta>
            </>
          ),
          action: { label: 'Review', onClick: () => navigate(`/governance/approvals?id=${encodeURIComponent(d.id)}`) },
        });
        return;
      }
      case 'approval.updated': {
        const d = data as SseEventMap['approval.updated'];
        if (!['approved', 'denied', 'expired'].includes(d.status)) return;
        if (dedupe(`approval.updated:${d.id}:${d.status}`)) return;
        const by = d.votes?.length ? (getMember(d.votes[d.votes.length - 1].member_id)?.name ?? d.votes[d.votes.length - 1].member_id) : null;
        const title = d.status === 'approved' ? `Approved${by ? ` by ${by}` : ''}` : d.status === 'denied' ? `Denied${by ? ` by ${by}` : ''}` : 'Approval expired';
        const fn = d.status === 'approved' ? toast.success : d.status === 'denied' ? toast.error : toast.warning;
        fn(title, { id: `apr-${d.id}`, className: 'aegis-toast', duration: 4500, description: d.title });
        return;
      }
      case 'budget.threshold': {
        const d = data as SseEventMap['budget.threshold'];
        if (d.pct < 50) return;
        if (dedupe(`budget:${d.scope}:${d.dimension}:${d.state}:${Math.floor(d.pct / 10)}`)) return;
        const what = d.state === 'hard' || d.pct >= 100 ? 'blocking' : d.state === 'soft' || d.pct >= 80 ? 'downgrading' : 'watch';
        const title = `${d.scope} at ${Math.round(d.pct)}% of ${d.window === 'day' ? 'daily' : d.window} ${d.dimension.toUpperCase()}`;
        const opts = {
          id: `budget-${d.scope}-${d.dimension}`,
          className: 'aegis-toast',
          description: <div>{what === 'blocking' ? 'Hard limit reached — further calls blocked (402)' : what === 'downgrading' ? 'Soft limit — remote models downgraded to local' : 'Halfway through the budget'}</div>,
          action: { label: 'Budgets', onClick: () => navigate('/governance/budgets') },
        };
        if (what === 'blocking') toast.error(title, opts);
        else toast.warning(title, opts);
        return;
      }
      case 'killswitch': {
        const d = data as SseEventMap['killswitch'];
        if (dedupe(`kill:${d.scope}:${d.active}`)) return;
        const fn = d.active ? toast.error : toast.success;
        fn(d.active ? `Kill switch engaged · ${d.scope}` : `Kill switch released · ${d.scope}`, {
          id: `kill-${d.scope}`,
          className: 'aegis-toast',
          description: <Meta>killswitch · by {actorName(d.actor)}</Meta>,
        });
        return;
      }
      case 'mcp.tool': {
        const d = data as SseEventMap['mcp.tool'];
        if (d.status === 'approved') return;
        if (dedupe(`mcp:${d.server}:${d.tool}:${d.status}`)) return;
        const title =
          d.status === 'changed'
            ? `MCP tool changed · ${d.server}/${d.tool}`
            : d.status === 'quarantined'
              ? `MCP tool quarantined · ${d.server}/${d.tool}`
              : `New MCP tool awaiting pin · ${d.server}/${d.tool}`;
        const fn = d.status === 'pending' ? toast.info : toast.warning;
        fn(title, {
          id: `mcp-${d.server}-${d.tool}`,
          className: 'aegis-toast',
          duration: 7000,
          description: (
            <>
              <div>{d.reason || (d.status === 'changed' ? 'Description/schema hash differs from the pinned version — calls blocked until re-approved' : 'Blocked until an admin approves it')}</div>
              <Meta>mcp.tool · {d.status}</Meta>
            </>
          ),
          action: { label: 'MCP', onClick: () => navigate('/security/mcp') },
        });
        return;
      }
      case 'system': {
        const d = data as SseEventMap['system'];
        if (dedupe(`system:${d.message}`)) return;
        const fn = d.level === 'error' ? toast.error : d.level === 'warning' ? toast.warning : toast.info;
        fn(d.message, { className: 'aegis-toast', description: d.component ? <Meta>system · {d.component}</Meta> : undefined });
        return;
      }
      default:
        return;
    }
  });
  return null;
}
