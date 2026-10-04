// Live decision table. Columns adapt to the *container* width (container queries, so the same table works in
// the full page, a drawer or a phone): stacked rows < 672 px, then 6 → 8 → 10 columns. Memoized rows; only rows
// that arrived after the first render animate (short fade + background flash, rose for block).
import { motion, useReducedMotion } from 'framer-motion';
import { CircleDashed, Eye } from '@/components/icons';
import { memo, type ReactNode } from 'react';
import type { DecisionSummary } from '@/api/types';
import { ActionBadge, DestBadge, IdentityChip } from '@/components/shell';
import { fmtMs, fmtTime, fmtUsd } from '@/lib/format';
import { cn } from '@/lib/utils';
import { ControlChip, EntityChip, SurfaceTag } from '../common/atoms';
import { splitTokens } from '../lib/placeholders';

// 6 columns ≥ @2xl (672), +surface/destination ≥ @4xl (896), +policy/cost ≥ @5xl (1024). Min widths of each tier
// (+ gaps + 32 px row padding) fit inside the tier's breakpoint, so the table never scrolls sideways.
const GRID =
  '@2xl:grid @2xl:grid-cols-[60px_92px_minmax(132px,1fr)_minmax(140px,2.4fr)_92px_56px] @4xl:grid-cols-[56px_88px_minmax(132px,1fr)_108px_minmax(140px,2.4fr)_88px_minmax(88px,0.6fr)_56px] @5xl:grid-cols-[56px_88px_minmax(140px,1.2fr)_108px_minmax(152px,2.4fr)_88px_minmax(92px,0.6fr)_64px_52px_52px] @5xl:gap-x-2.5 items-center gap-x-3';

export function PreviewText({ text, className }: { text: string; className?: string }) {
  const pieces = splitTokens(text.length > 220 ? `${text.slice(0, 220)}…` : text);
  return (
    <span className={cn('block truncate font-mono text-[11.5px] text-text-2', className)} title={text}>
      {pieces.map((p, i) =>
        p.token ? (
          <span key={i} className="rounded-xs bg-redact/12 px-0.5 text-redact">
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

function costText(d: DecisionSummary): string {
  return d.cost_usd ? fmtUsd(d.cost_usd, { dp: d.cost_usd < 0.01 ? 4 : 2 }) : '—';
}

function Flags({ d }: { d: DecisionSummary }) {
  return (
    <>
      {monitorHit(d) ? (
        <span className="inline-flex shrink-0 text-text-3" title="Monitor mode: a control would have acted but is not enforcing" aria-label="monitor-mode hit">
          <Eye className="size-3.5" />
        </span>
      ) : null}
      {d.degraded ? (
        <span
          className="inline-flex shrink-0 text-text-4"
          title="Degraded: a semantic stage was unavailable, so its deterministic fallback decided (fail-mode applied)"
          aria-label="degraded: deterministic fallback"
        >
          <CircleDashed className="size-3.5" />
        </span>
      ) : null}
    </>
  );
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
  // Only controls that did something count as "+N" (allow-only checks are not interventions).
  const extra = (d.controls ?? []).filter((c) => c.control_id !== d.control_id && c.action !== 'allow').length;
  const subject = d.tool_name ?? d.model;
  const preview = d.preview || d.reason;
  return (
    <motion.div
      role="row"
      tabIndex={0}
      data-id={d.id}
      initial={isNew && !reduce ? { opacity: 0 } : false}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.15, ease: 'easeOut' }}
      onClick={() => onOpen(d)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onOpen(d);
      }}
      className={cn(
        GRID,
        'block cursor-pointer border-b border-border-subtle px-4 py-2 text-xs outline-none transition-colors hover:bg-surface-2/70 focus-visible:bg-surface-2 @2xl:min-h-[40px] @2xl:py-1.5',
        isNew && !reduce && (d.action === 'block' ? 'animate-row-in-block' : 'animate-row-in'),
        selected && 'bg-brand/10 shadow-[inset_2px_0_0_var(--accent-fg)]',
      )}
    >
      {/* stacked layout (narrow containers) */}
      <div className="flex min-w-0 flex-col gap-1 @2xl:hidden">
        <div className="flex min-w-0 items-center gap-1.5">
          <ActionBadge action={d.action} size="sm" />
          <Flags d={d} />
          {subject ? <span className="min-w-0 truncate font-mono text-[11.5px] font-medium text-text-1">{subject}</span> : <SurfaceTag surface={d.surface} direction={d.direction} />}
          <span className="ml-auto shrink-0 font-mono text-2xs tabular text-text-3">{fmtTime(d.ts, { seconds: true })}</span>
        </div>
        {preview ? <PreviewText text={preview} /> : null}
        <div className="flex min-w-0 items-center gap-2">
          <span className="min-w-0 truncate">
            <IdentityChip identity={d.identity} />
          </span>
          {d.redaction_count ? <span className="shrink-0 rounded-xs bg-redact/12 px-1 font-mono text-[10px] text-redact">{d.redaction_count} redacted</span> : null}
          <span className="ml-auto flex shrink-0 items-center gap-2">
            {d.control_id ? <ControlChip id={d.control_id} /> : null}
            <span className="font-mono text-2xs tabular text-text-2">{fmtMs(d.latency_ms)}</span>
          </span>
        </div>
      </div>

      {/* table cells (≥ @2xl) */}
      <span className="hidden font-mono text-2xs tabular text-text-3 @2xl:block">{fmtTime(d.ts, { seconds: true })}</span>
      <span className="hidden min-w-0 items-center gap-1 @2xl:flex">
        <ActionBadge action={d.action} size="sm" />
        <Flags d={d} />
      </span>
      <span className="hidden min-w-0 truncate @2xl:block">
        <IdentityChip identity={d.identity} />
      </span>
      <span className="hidden min-w-0 @4xl:block">
        <SurfaceTag surface={d.surface} direction={d.direction} />
      </span>
      <span className="hidden min-w-0 items-center gap-1.5 @2xl:flex">
        {subject ? <span className="max-w-[45%] shrink-0 truncate font-mono text-[11.5px] font-medium text-text-1" title={subject}>{subject}</span> : null}
        <PreviewText text={preview} className="min-w-0 flex-1" />
        {d.redaction_count ? (
          <span className="flex shrink-0 items-center gap-1">
            <span className="rounded-xs bg-redact/12 px-1 font-mono text-[10px] font-medium tabular text-redact" title={`${d.redaction_count} redactions`}>
              {d.redaction_count}
            </span>
            {(d.entities ?? []).slice(0, 2).map((e) => (
              <EntityChip key={e} entity={e} className="hidden @7xl:inline-flex" />
            ))}
          </span>
        ) : null}
      </span>
      <span className="hidden min-w-0 items-center gap-1 @2xl:flex">
        {d.control_id ? <ControlChip id={d.control_id} /> : <span className="text-text-4">—</span>}
        {extra > 0 ? <span className="text-[10px] tabular text-text-3" title={`${extra} more control(s) acted`}>+{extra}</span> : null}
      </span>
      <span className="hidden min-w-0 truncate @4xl:block">
        <DestBadge dest={d.destination} className="max-w-full truncate" />
      </span>
      <span className="hidden truncate whitespace-nowrap font-mono text-[10.5px] tabular text-text-3 @5xl:block" title={`policy v${d.policy_version} · feed #${d.feed_serial ?? '—'}`}>
        v{d.policy_version} · #{d.feed_serial ?? '—'}
      </span>
      <span className="hidden text-right font-mono tabular text-text-2 @2xl:block" title={d.upstream_ms !== null ? `upstream ${fmtMs(d.upstream_ms)}` : undefined}>
        {fmtMs(d.latency_ms)}
      </span>
      <span className="hidden text-right font-mono tabular text-text-3 @5xl:block">{costText(d)}</span>
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
    <div className="@container" role="table" aria-label="Live decisions">
      <div
        role="row"
        className={cn(
          GRID,
          'sticky top-0 z-[1] hidden border-b border-border bg-surface-1 px-4 py-2 text-2xs font-medium uppercase tracking-[0.06em] text-text-3 @2xl:grid',
        )}
      >
        <span>Time</span>
        <span>Decision</span>
        <span>Identity</span>
        <span className="hidden @4xl:block">Surface</span>
        <span>Request</span>
        <span>Control</span>
        <span className="hidden @4xl:block">Destination</span>
        <span className="hidden @5xl:block">Policy</span>
        <span className="text-right" title="Aegis decision overhead">
          Overhead
        </span>
        <span className="hidden text-right @5xl:block">Cost</span>
      </div>
      {rows.length === 0 ? (empty ?? null) : rows.map((d) => <FeedRow key={d.id} d={d} isNew={isNew(d.id)} selected={selectedId === d.id} onOpen={onOpen} />)}
    </div>
  );
}
