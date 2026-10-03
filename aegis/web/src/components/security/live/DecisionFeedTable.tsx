// Live decision table (prototype view-live.js column set). Memoized rows; only rows that arrived after the
// first render animate (6 px slide + background flash, rose for block).
import { motion, useReducedMotion } from 'framer-motion';
import { memo, type ReactNode } from 'react';
import type { DecisionSummary } from '@/api/types';
import { ActionBadge, DestBadge, IdentityChip } from '@/components/shell';
import { fmtMs, fmtTime, fmtUsd } from '@/lib/format';
import { cn } from '@/lib/utils';
import { ControlChip, EntityChip, SurfaceTag } from '../common/atoms';
import { splitTokens } from '../lib/placeholders';

const GRID = 'grid grid-cols-[64px_108px_minmax(140px,1.1fr)_120px_minmax(200px,2.4fr)_96px_96px_74px_64px_56px] items-center gap-3';

export function PreviewText({ text, className }: { text: string; className?: string }) {
  const pieces = splitTokens(text.length > 220 ? `${text.slice(0, 220)}…` : text);
  return (
    <span className={cn('truncate font-mono text-[11.5px] text-text-2', className)} title={text}>
      {pieces.map((p, i) =>
        p.token ? (
          <span key={i} className="rounded-[3px] bg-redact/12 px-0.5 text-redact">
            {p.text}
          </span>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </span>
  );
}

function monitorHit(d: DecisionSummary): boolean {
  return (d.controls ?? []).some((c) => c.mode === 'monitor' && c.action !== 'allow');
}

export const FeedRow = memo(function FeedRow({
  d,
  isNew,
  selected,
  onOpen,
}: {
  d: DecisionSummary;
  isNew: boolean;
  selected: boolean;
  onOpen: (d: DecisionSummary) => void;
}) {
  const reduce = useReducedMotion();
  const extra = Math.max(0, (d.controls ?? []).filter((c) => c.control_id !== d.control_id).length);
  return (
    <motion.div
      role="row"
      tabIndex={0}
      data-id={d.id}
      initial={isNew && !reduce ? { opacity: 0, y: -6 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
      onClick={() => onOpen(d)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onOpen(d);
      }}
      className={cn(
        GRID,
        'min-h-[42px] cursor-pointer border-b border-border-subtle px-4 py-1.5 text-xs outline-none transition-colors hover:bg-surface-2/70 focus-visible:bg-surface-2',
        isNew && !reduce && (d.action === 'block' ? 'animate-row-in-block' : 'animate-row-in'),
        selected && 'bg-brand/10 shadow-[inset_2px_0_0_var(--accent-fg)]',
      )}
    >
      <span className="font-mono text-2xs tabular text-text-3">{fmtTime(d.ts, { seconds: true })}</span>
      <span className="flex min-w-0 flex-wrap items-center gap-1">
        <ActionBadge action={d.action} size="sm" />
        {monitorHit(d) ? <span className="rounded-sm border border-dashed border-border-strong px-1 text-[10px] text-text-3">monitor</span> : null}
        {d.degraded ? <span className="rounded-sm border border-redact/30 px-1 text-[10px] text-redact">degraded</span> : null}
      </span>
      <span className="min-w-0 truncate">
        <IdentityChip identity={d.identity} />
      </span>
      <span className="min-w-0">
        <SurfaceTag surface={d.surface} direction={d.direction} />
      </span>
      <span className="flex min-w-0 items-center gap-1.5">
        {d.tool_name || d.model ? <span className="shrink-0 font-mono text-[11.5px] font-medium text-text-1">{d.tool_name ?? d.model}</span> : null}
        <PreviewText text={d.preview || d.reason} className="min-w-0" />
        {d.redaction_count ? (
          <span className="flex shrink-0 items-center gap-1">
            <span className="rounded-full bg-redact/12 px-1.5 text-[10px] font-medium text-redact">{d.redaction_count}</span>
            {(d.entities ?? []).slice(0, 2).map((e) => (
              <EntityChip key={e} entity={e} className="hidden 2xl:inline-flex" />
            ))}
          </span>
        ) : null}
      </span>
      <span className="flex min-w-0 items-center gap-1">
        {d.control_id ? <ControlChip id={d.control_id} /> : <span className="text-text-4">—</span>}
        {extra > 0 ? <span className="text-[10px] text-text-3">+{extra}</span> : null}
      </span>
      <span className="min-w-0 truncate">
        <DestBadge dest={d.destination} />
      </span>
      <span className="font-mono text-[10.5px] text-text-3">
        v{d.policy_version} · #{d.feed_serial ?? '—'}
      </span>
      <span className="text-right font-mono tabular text-text-2" title={d.upstream_ms !== null ? `upstream ${fmtMs(d.upstream_ms)}` : undefined}>
        {fmtMs(d.latency_ms)}
      </span>
      <span className="text-right font-mono tabular text-text-3">{d.cost_usd ? fmtUsd(d.cost_usd, { dp: d.cost_usd < 0.01 ? 4 : 2 }) : '—'}</span>
    </motion.div>
  );
});

export function DecisionFeedTable({
  rows,
  isNew,
  selectedId,
  onOpen,
  empty,
}: {
  rows: DecisionSummary[];
  isNew: (id: string) => boolean;
  selectedId: string | null;
  onOpen: (d: DecisionSummary) => void;
  empty?: ReactNode;
}) {
  return (
    <div className="overflow-x-auto" role="table" aria-label="Live decisions">
      <div className="min-w-[1100px]">
        <div role="row" className={cn(GRID, 'sticky top-0 z-[1] border-b border-border bg-surface-1/95 px-4 py-2 text-2xs font-medium uppercase tracking-[0.08em] text-text-3 backdrop-blur')}>
          <span>Time</span>
          <span>Decision</span>
          <span>Identity</span>
          <span>Surface</span>
          <span>Request</span>
          <span>Control</span>
          <span>Dest</span>
          <span>Version</span>
          <span className="text-right">Aegis</span>
          <span className="text-right">Cost</span>
        </div>
        {rows.length === 0 ? (
          (empty ?? null)
        ) : (
          rows.map((d) => <FeedRow key={d.id} d={d} isNew={isNew(d.id)} selected={selectedId === d.id} onOpen={onOpen} />)
        )}
      </div>
    </div>
  );
}
