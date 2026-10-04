// Budget hierarchy (UIG-03): org → team → member/agent rows from `scopes[].parent` (sessions grouped
// last), each with a live usage bar (used + reserved, 80 % / 100 % marks), value text by dimension,
// reset countdown, state pill and actions (Request increase · Kill). Ported from the prototype's
// view-budgets.js row grid. Owner: B19-dashboard-gov-policy.
import { AnimatePresence, motion } from 'framer-motion';
import { Bot, Building2, ChevronRight, Clock, TerminalSquare, TrendingUp, User, Users } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import type { ApplyResult, BudgetDimension, BudgetScopeView, BudgetStatus, BudgetWindow, BudgetsResponse, Member } from '@/api/types';
import { dimensionLabel, fmtDimension, scopeParts, windowLabel } from '@/components/governance/lib/format-gov';
import type { MockViewer } from '@/components/governance/policy/policy-api';
import { Button } from '@/components/ui/button';
import { teamColor } from '@/lib/colors';
import { cn } from '@/lib/utils';
import { KillSwitchControl, killPermission } from './KillSwitchControl';
import { BudgetStatePill, BudgetUsageBar } from './UsageBar';

const ICONS: Record<string, typeof Bot> = { org: Building2, team: Users, member: User, agent: Bot, session: TerminalSquare };

export function pickLimit(s: BudgetScopeView, dim: BudgetDimension, win: BudgetWindow): { status: BudgetStatus | null; exact: boolean } {
  const exact = s.limits.find((l) => l.dimension === dim && l.window === win);
  if (exact) return { status: exact, exact: true };
  const sameDim = s.limits.find((l) => l.dimension === dim);
  if (sameDim) return { status: sameDim, exact: false };
  if (s.scope_type === 'session') return { status: s.limits.find((l) => l.window === 'session') ?? null, exact: false };
  return { status: null, exact: false };
}

function fmtReset(iso: string | null, now: number): string | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - now;
  if (!Number.isFinite(ms) || ms <= 0) return null;
  const h = Math.floor(ms / 3600_000);
  const m = Math.floor((ms % 3600_000) / 60_000);
  if (h >= 48) return `resets in ${Math.round(h / 24)}d`;
  return h > 0 ? `resets in ${h}h ${String(m).padStart(2, '0')}m` : `resets in ${m}m`;
}

function isDirectKill(ks: BudgetsResponse['kill_switch'], scope: string): boolean {
  const { type, id } = scopeParts(scope);
  if (type === 'team') return ks.teams.includes(id);
  if (type === 'member') return ks.members.includes(id);
  if (type === 'agent') return ks.agents.includes(id);
  if (type === 'session') return ks.sessions.includes(id);
  return false;
}

export interface BudgetTreeProps {
  data: BudgetsResponse;
  dimension: BudgetDimension;
  window: BudgetWindow;
  now: number;
  viewer: MockViewer;
  canKillswitch: boolean;
  sponsorOf: (agentId: string) => Member | undefined;
  memberName: (id: string) => string;
  selected: string | null;
  onSelect: (scope: string) => void;
  onRaise: (s: BudgetScopeView, l: BudgetStatus | null) => void;
  onMutated?: (r: ApplyResult) => void;
}

export function BudgetTree(props: BudgetTreeProps) {
  const { data } = props;
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const { roots, children, sessions } = useMemo(() => {
    const ch = new Map<string, BudgetScopeView[]>();
    const roots: BudgetScopeView[] = [];
    const sessions: BudgetScopeView[] = [];
    const known = new Set(data.scopes.map((s) => s.scope));
    for (const s of data.scopes) {
      if (s.scope_type === 'session') {
        sessions.push(s);
        continue;
      }
      if (s.parent && known.has(s.parent)) ch.set(s.parent, [...(ch.get(s.parent) ?? []), s]);
      else roots.push(s);
    }
    const order: Record<string, number> = { org: 0, team: 1, agent: 2, member: 3, model: 4, tool: 5 };
    for (const [k, v] of ch) ch.set(k, [...v].sort((a, b) => (order[a.scope_type] ?? 9) - (order[b.scope_type] ?? 9) || a.name.localeCompare(b.name)));
    return { roots, children: ch, sessions };
  }, [data.scopes]);

  const toggle = (scope: string) =>
    setCollapsed((c) => {
      const n = new Set(c);
      if (n.has(scope)) n.delete(scope);
      else n.add(scope);
      return n;
    });

  const render = (s: BudgetScopeView, depth: number, inheritedKill: string | null): ReactNode[] => {
    const kids = children.get(s.scope) ?? [];
    const open = !collapsed.has(s.scope);
    const direct = isDirectKill(data.kill_switch, s.scope);
    const inherited = s.state === 'killed' && !direct ? (inheritedKill ?? (data.kill_switch.global ? 'global' : null)) : null;
    const nextInherited = direct ? s.scope : inheritedKill;
    const out: ReactNode[] = [
      <BudgetRow key={s.scope} {...props} s={s} depth={depth} hasKids={kids.length > 0} open={open} onToggle={() => toggle(s.scope)} directKill={direct} inheritedKill={inherited} />,
    ];
    if (open) for (const k of kids) out.push(...render(k, depth + 1, nextInherited));
    return out;
  };

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[860px]">
        <div className="grid grid-cols-[minmax(240px,1.4fr)_minmax(220px,2fr)_150px_130px_170px] items-center gap-4 border-b border-border px-4 py-2 text-2xs font-medium uppercase tracking-wider text-text-3">
          <div>Scope</div>
          <div>
            Usage · {dimensionLabel(props.dimension)} / {windowLabel(props.window)}
          </div>
          <div className="text-right">Used / limit</div>
          <div>State</div>
          <div className="text-right">Actions</div>
        </div>
        <AnimatePresence initial={false}>{roots.flatMap((r) => render(r, 0, null))}</AnimatePresence>
        {sessions.length > 0 ? (
          <>
            <div className="border-b border-border-subtle bg-surface-1/60 px-4 py-1.5 text-2xs font-medium uppercase tracking-wider text-text-3">Sessions</div>
            {sessions.map((s) => (
              <BudgetRow key={s.scope} {...props} s={s} depth={0} hasKids={false} open={false} onToggle={() => undefined} directKill={isDirectKill(data.kill_switch, s.scope)} inheritedKill={null} />
            ))}
          </>
        ) : null}
      </div>
    </div>
  );
}

function BudgetRow({
  s,
  depth,
  hasKids,
  open,
  onToggle,
  directKill,
  inheritedKill,
  dimension,
  window: win,
  now,
  viewer,
  canKillswitch,
  sponsorOf,
  memberName,
  selected,
  onSelect,
  onRaise,
  onMutated,
}: BudgetTreeProps & { s: BudgetScopeView; depth: number; hasKids: boolean; open: boolean; onToggle: () => void; directKill: boolean; inheritedKill: string | null }) {
  const Icon = ICONS[s.scope_type] ?? Users;
  const { status: l, exact } = pickLimit(s, dimension, win);
  const { type, id } = scopeParts(s.scope);
  const sponsor = type === 'agent' ? sponsorOf(id) : undefined;
  const sub =
    type === 'agent'
      ? sponsor
        ? `sponsor ${sponsor.name}`
        : 'service identity'
      : type === 'member'
        ? 'member'
        : type === 'team'
          ? `team · ${s.limits.length} limit${s.limits.length === 1 ? '' : 's'}`
          : type === 'session'
            ? s.parent ?? 'session'
            : 'organization';
  const killed = s.state === 'killed';
  const perm = killPermission({ canKillswitch, scope: s.scope, viewerId: viewer.id, sponsorId: sponsor?.id ?? null });
  const reset = l ? fmtReset(l.resets_at, now) : null;
  const tcolor = type === 'team' ? teamColor(id) : type === 'member' || type === 'agent' ? teamColor(s.parent ? scopeParts(s.parent).id : null) : undefined;
  return (
    <motion.div
      layout="position"
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.18 }}
      onClick={() => onSelect(s.scope)}
      className={cn(
        'grid cursor-pointer grid-cols-[minmax(240px,1.4fr)_minmax(220px,2fr)_150px_130px_170px] items-center gap-4 border-b border-border-subtle px-4 py-2.5 transition-colors hover:bg-surface-2/50',
        selected === s.scope && 'bg-[var(--accent-subtle)] hover:bg-[var(--accent-subtle)]',
        killed && 'bg-block/[0.04]',
      )}
    >
      <div className="flex min-w-0 items-center gap-2" style={{ paddingLeft: depth * 20 }}>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
          className={cn('grid size-5 shrink-0 place-items-center rounded text-text-3 hover:bg-surface-3', !hasKids && 'invisible')}
          aria-label={open ? 'Collapse' : 'Expand'}
        >
          <ChevronRight className={cn('size-3.5 transition-transform', open && 'rotate-90')} />
        </button>
        <span className="grid size-7 shrink-0 place-items-center rounded-md border border-border bg-surface-2" style={tcolor ? { color: tcolor, borderColor: `${tcolor}40` } : undefined}>
          <Icon className="size-3.5" />
        </span>
        <div className="min-w-0">
          <div className={cn('truncate text-sm', depth === 0 ? 'font-semibold text-text-1' : 'font-medium text-text-1')}>{s.name || memberName(id)}</div>
          <div className="truncate font-mono text-2xs text-text-3">
            {s.scope} <span className="font-sans">· {sub}</span>
          </div>
        </div>
      </div>

      <div className="min-w-0">
        {l ? (
          <>
            <BudgetUsageBar used={l.used} reserved={l.reserved} limit={l.limit} state={killed ? 'killed' : l.state} />
            <div className="mt-1 flex items-center gap-2 text-2xs text-text-3">
              <span className="tabular">{Math.round(l.pct)}%</span>
              {!exact ? (
                <span className="text-text-4">
                  ({dimensionLabel(l.dimension)} / {windowLabel(l.window)})
                </span>
              ) : null}
              {l.label ? <span className="truncate text-text-4">{l.label}</span> : null}
              {reset ? (
                <span className="ml-auto inline-flex items-center gap-1 text-text-4">
                  <Clock className="size-3" />
                  {reset}
                </span>
              ) : null}
            </div>
          </>
        ) : (
          <div className="text-2xs text-text-4">no {dimensionLabel(dimension)} limit — inherits from parent</div>
        )}
      </div>

      <div className="text-right font-mono text-xs tabular">
        {l ? (
          <>
            <span className={cn(l.state === 'hard' ? 'text-block' : l.state === 'soft' ? 'text-redact' : 'text-text-1')}>{fmtDimension(l.dimension, l.used)}</span>
            <span className="text-text-3"> / {fmtDimension(l.dimension, l.limit)}</span>
          </>
        ) : (
          <span className="text-text-4">—</span>
        )}
      </div>

      <div>
        <BudgetStatePill state={s.state} />
      </div>

      <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
        {s.limits.length > 0 && !killed ? (
          <Button size="xs" variant="secondary" onClick={() => onRaise(s, l)} title="Request a budget change (routed by approval rules)">
            <TrendingUp className="size-3" /> Increase
          </Button>
        ) : null}
        {type !== 'org' ? (
          <KillSwitchControl scope={s.scope} killed={killed} perm={perm} viewer={viewer} onDone={onMutated} inheritedFrom={directKill ? null : inheritedKill} />
        ) : null}
      </div>
    </motion.div>
  );
}
