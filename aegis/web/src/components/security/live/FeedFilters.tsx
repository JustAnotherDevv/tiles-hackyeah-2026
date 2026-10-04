// Live-feed filter bar: search, action chips with counts, selects (surface/kind/agent/source/dest), non-allow toggle.
import { ChevronDown, Search, X } from '@/components/icons';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import type { Action, DecisionSummary } from '@/api/types';
import { ACTION_COLORS } from '@/lib/colors';
import { cn } from '@/lib/utils';
import { EMPTY_FILTER, isFilterActive } from '../lib/filters';
import { ALL_SURFACES } from '../lib/catalog';
import type { DecisionFilter } from '../types';

const ACTIONS: Action[] = ['block', 'require_approval', 'redact', 'log', 'allow'];
const KINDS = ['model_call', 'tool_call', 'mcp', 'egress', 'a2a', 'config_change'];
const SOURCES = ['proxy', 'hook', 'mcp', 'egress', 'guard', 'playground', 'dashboard', 'selftest'];
const DESTS = ['local', 'remote', 'third_party'];

export function MiniSelect({
  value,
  onChange,
  label,
  options,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  options: { value: string; label: ReactNode }[];
  className?: string;
}) {
  return (
    <label
      className={cn(
        'relative inline-flex h-9 shrink-0 items-center gap-1.5 rounded-sm border bg-surface-1 pl-2.5 pr-1 text-xs transition-colors sm:h-8',
        value ? 'border-accent-fg/40 text-text-1' : 'border-border text-text-3 hover:border-border-strong',
        className,
      )}
    >
      <span className="text-text-3">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-full max-w-[160px] cursor-pointer appearance-none bg-transparent pr-4 font-mono text-text-1 outline-none"
        aria-label={label}
      >
        <option value="">all</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {typeof o.label === 'string' ? o.label : o.value}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-1.5 size-3 text-text-4" aria-hidden />
    </label>
  );
}

export function ActionChips({ value, counts, onChange }: { value: Action[]; counts: Record<Action, number>; onChange: (a: Action[]) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      {ACTIONS.map((a) => {
        const on = value.includes(a);
        const c = ACTION_COLORS[a];
        return (
          <button
            key={a}
            type="button"
            onClick={() => onChange(on ? value.filter((x) => x !== a) : [...value, a])}
            className={cn(
              'inline-flex h-9 items-center gap-1.5 rounded-sm border px-2.5 text-xs transition-colors sm:h-8',
              on ? 'text-text-1' : 'border-border bg-surface-1 text-text-2 hover:border-border-strong',
            )}
            style={on ? { borderColor: c.border, background: c.bg, color: c.fg } : undefined}
            aria-pressed={on}
          >
            <span className="size-1.5 rounded-full" style={{ background: c.chart }} />
            {c.label}
            <span className="font-mono text-2xs tabular text-text-3">{counts[a] ?? 0}</span>
          </button>
        );
      })}
    </div>
  );
}

export function FeedFilters({
  filter,
  onChange,
  items,
  agents,
  right,
}: {
  filter: DecisionFilter;
  onChange: (f: DecisionFilter) => void;
  items: DecisionSummary[];
  agents: { id: string; name: string }[];
  right?: ReactNode;
}) {
  const [q, setQ] = useState(filter.q);
  useEffect(() => setQ(filter.q), [filter.q]);
  useEffect(() => {
    if (q === filter.q) return;
    const t = setTimeout(() => onChange({ ...filter, q }), 250);
    return () => clearTimeout(t);
  }, [q, filter, onChange]);

  const counts = useMemo(() => {
    const c: Record<Action, number> = { allow: 0, log: 0, redact: 0, require_approval: 0, block: 0 };
    for (const d of items) c[d.action] = (c[d.action] ?? 0) + 1;
    return c;
  }, [items]);
  const agentOptions = useMemo(() => {
    const ids = new Map<string, string>(agents.map((a) => [a.id, a.name]));
    for (const d of items) if (d.identity?.agent_id && !ids.has(d.identity.agent_id)) ids.set(d.identity.agent_id, d.identity.agent_id);
    return [...ids.keys()].sort().map((id) => ({ value: id, label: id }));
  }, [agents, items]);
  const set = (patch: Partial<DecisionFilter>) => onChange({ ...filter, ...patch });

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative flex h-9 w-full min-w-0 items-center rounded-sm border border-border bg-surface-1 px-2.5 focus-within:border-accent-fg/50 sm:h-8 sm:w-auto sm:min-w-[220px] sm:max-w-[360px] sm:flex-1">
          <Search className="size-3.5 text-text-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search id, tool, control, entity, agent"
            className="ml-2 h-full w-full bg-transparent text-xs text-text-1 outline-none placeholder:text-text-4"
            aria-label="Search decisions"
          />
          {q ? (
            <button type="button" onClick={() => setQ('')} className="-mr-1 grid size-7 shrink-0 place-items-center text-text-3 hover:text-text-1" aria-label="Clear search">
              <X className="size-3.5" />
            </button>
          ) : null}
        </label>
        <ActionChips value={filter.actions} counts={counts} onChange={(actions) => set({ actions })} />
        {right ? <div className="ml-auto flex items-center gap-2">{right}</div> : null}
      </div>
      <div className="-mx-4 flex items-center gap-1.5 overflow-x-auto px-4 pb-0.5 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0">
        <MiniSelect label="Surface" value={filter.surface} onChange={(surface) => set({ surface })} options={ALL_SURFACES.map((s) => ({ value: s, label: s }))} />
        <MiniSelect label="Kind" value={filter.kind} onChange={(kind) => set({ kind })} options={KINDS.map((s) => ({ value: s, label: s }))} />
        <MiniSelect label="Agent" value={filter.agent} onChange={(agent) => set({ agent })} options={agentOptions} />
        <MiniSelect label="Source" value={filter.source} onChange={(source) => set({ source })} options={SOURCES.map((s) => ({ value: s, label: s }))} />
        <MiniSelect label="Dest" value={filter.dest} onChange={(dest) => set({ dest })} options={DESTS.map((s) => ({ value: s, label: s }))} />
        {filter.control ? (
          <button type="button" onClick={() => set({ control: '' })} className="inline-flex h-9 shrink-0 items-center gap-1 rounded-sm border border-accent-fg/40 bg-brand/10 px-2.5 font-mono text-xs text-text-1 sm:h-8">
            control {filter.control} <X className="size-3" />
          </button>
        ) : null}
        <button
          type="button"
          onClick={() => set({ nonAllow: !filter.nonAllow })}
          aria-pressed={filter.nonAllow}
          className={cn(
            'inline-flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border px-2.5 text-xs transition-colors sm:h-8',
            filter.nonAllow ? 'border-accent-fg/40 bg-brand/10 text-text-1' : 'border-border bg-surface-1 text-text-3 hover:border-border-strong',
          )}
        >
          <span className={cn('size-2 rounded-[3px] border', filter.nonAllow ? 'border-accent-fg bg-accent-fg' : 'border-border-strong')} />
          Hide allowed
        </button>
        {isFilterActive(filter) ? (
          <button type="button" onClick={() => onChange({ ...EMPTY_FILTER, actions: [] })} className="h-9 shrink-0 whitespace-nowrap px-2 text-xs text-text-3 hover:text-text-1 sm:h-8">
            Clear filters
          </button>
        ) : null}
      </div>
    </div>
  );
}
