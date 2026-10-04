// The Wire view (F1 headline): original (local) ↔ on-the-wire panes with linked placeholders,
// stats strip, legend, response panes (model returned ↔ user sees) and the entity table.
import { ArrowRight, Ban, EyeOff, Lock, Send, ShieldCheck } from '@/components/icons';
import { useMemo, useState, type ReactNode } from 'react';
import type { Destination, Redaction, WireView } from '@/api/types';
import { EmptyState } from '@/components/shell';
import { fmtMs } from '@/lib/format';
import { cn } from '@/lib/utils';
import { DATA_CLASS_COLORS, DROPPED_COLOR, RESTORED_COLOR } from '../common/colors';
import { buildOriginalParts, buildOutboundParts, changedSegmentIndexes, originalsFromWire, redactionStats } from '../lib/redactionDiff';
import { splitTokens } from '../lib/placeholders';
import { EntityTable } from './EntityTable';
import { HighlightedText } from './HighlightedText';
import { ResponsePanes } from './ResponsePanes';

const CAP = 4000;

function Pane({ head, children, className }: { head: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn('min-w-0 px-4 pb-4 pt-3', className)}>
      <div className="mb-2.5 flex min-h-5 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-3">{head}</div>
      {children}
    </div>
  );
}

function Capped({ text, children }: { text: string; children: (shown: string) => ReactNode }) {
  const [open, setOpen] = useState(false);
  if (text.length <= CAP || open) return <>{children(text)}</>;
  return (
    <>
      {children(text.slice(0, CAP))}
      <button type="button" className="mt-1 text-xs text-accent-fg hover:underline" onClick={() => setOpen(true)}>
        Show {text.length - CAP} more characters
      </button>
    </>
  );
}

export function StatsStrip({ items }: { items: [ReactNode, string][] }) {
  return (
    <div className="@container">
      <div className="grid grid-cols-2 gap-px bg-border-subtle @md:grid-cols-3 @3xl:grid-cols-6">
        {items.map(([v, l], i) => (
          <div key={i} className="min-w-0 bg-surface-1 px-3.5 py-2.5">
            <div className="truncate text-2xs font-medium uppercase tracking-[0.06em] text-text-3">{l}</div>
            <div className="mt-0.5 truncate font-mono text-[15px] font-medium tabular text-text-1">{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RedactionLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-text-2">
      {(['CONFIDENTIAL', 'RESTRICTED', 'SECRET', 'INTERNAL'] as const).map((k) => (
        <span key={k} className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-[2px]" style={{ background: `color-mix(in srgb, ${DATA_CLASS_COLORS[k].color} 30%, transparent)`, boxShadow: `inset 0 0 0 1px ${DATA_CLASS_COLORS[k].color}` }} />
          {DATA_CLASS_COLORS[k].label}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5">
        <span className="size-2.5 rounded-[2px]" style={{ background: `color-mix(in srgb, ${DROPPED_COLOR} 15%, transparent)`, boxShadow: `inset 0 0 0 1px ${DROPPED_COLOR}` }} />
        Dropped (PCI)
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="size-2.5 rounded-[2px]" style={{ background: `color-mix(in srgb, ${RESTORED_COLOR} 15%, transparent)`, boxShadow: `inset 0 0 0 1px ${RESTORED_COLOR}` }} />
        Restored locally
      </span>
    </div>
  );
}

function PreviewText({ text }: { text: string }) {
  return (
    <span className="font-mono text-xs text-text-2">
      {splitTokens(text).map((p, i) =>
        p.token ? (
          <span key={i} className="rounded-xs bg-redact/10 px-1 text-redact">
            {p.text}
          </span>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </span>
  );
}

export function RedactionDiff({
  wire,
  redactions,
  destination,
  latencyMs,
  preview,
  animate = false,
  showTable = true,
}: {
  wire: WireView | null;
  redactions: Redaction[];
  destination?: Destination | null;
  latencyMs?: number | null;
  preview?: string;
  animate?: boolean;
  showTable?: boolean;
}) {
  const [active, setActive] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const originals = useMemo(() => originalsFromWire(wire, redactions), [wire, redactions]);
  const stats = useMemo(() => redactionStats(wire, redactions), [wire, redactions]);

  if (!wire) {
    return (
      <div className="space-y-3">
        <div className="rounded-md border border-border bg-surface-1">
          <EmptyState
            icon={Lock}
            title="Wire view expired"
            hint="Raw content is held in gateway memory for up to 1 h and never persisted. The audit log keeps placeholders and HMAC fingerprints only."
          />
          {preview ? (
            <div className="border-t border-border-subtle px-4 py-3 text-xs">
              <div className="mb-1 text-2xs uppercase tracking-wider text-text-3">Masked preview</div>
              <PreviewText text={preview} />
            </div>
          ) : null}
        </div>
        {redactions.length ? (
          <div className="overflow-hidden rounded-md border border-border bg-surface-1">
            <EntityTable redactions={redactions} originals={new Map()} />
          </div>
        ) : null}
      </div>
    );
  }

  const blocked = wire.outbound.length === 0 && wire.original.length > 0;
  const changed = changedSegmentIndexes(wire, redactions);
  const all = Array.from({ length: wire.original.length }, (_, i) => i);
  const shown = blocked ? all.filter((i) => wire.original[i]?.role !== 'system') : showAll || changed.length === 0 ? all : changed;
  const hidden = wire.original.length - shown.length;
  const destName = destination?.name ?? 'destination';

  return (
    <div className="space-y-3">
      <div className="overflow-hidden rounded-md border border-border bg-surface-1">
        <StatsStrip
          items={[
            [stats.entities, 'Entities detected'],
            [stats.tokenized, 'Tokenized (reversible)'],
            [stats.dropped + stats.masked, 'Dropped / masked'],
            [`${stats.segmentsChanged}/${wire.original.length}`, 'Segments changed'],
            [blocked ? 'blocked' : (destination?.dest_class?.replace('_', ' ') ?? '—'), 'Destination class'],
            [fmtMs(latencyMs ?? null), 'Aegis latency'],
          ]}
        />
      </div>

      <div className="@container overflow-hidden rounded-md border border-border bg-surface-1">
        {shown.map((i) => {
          const o = wire.original[i];
          const w = wire.outbound[i];
          if (!o) return null;
          return (
            <div key={i} className="border-b border-border-subtle last:border-0">
              <div className="flex min-w-0 items-center gap-2 border-b border-border-subtle bg-surface-2/50 px-4 py-1.5 font-mono text-2xs text-text-3">
                <span className="min-w-0 truncate text-text-2" title={o.path}>{o.path}</span>
                <span className="shrink-0">· {o.role}</span>
                {!o.trusted ? <span className="shrink-0 rounded-xs border border-redact/30 px-1 text-redact">untrusted</span> : null}
              </div>
              <div className="relative grid grid-cols-1 @xl:grid-cols-2">
                <Pane
                  head={
                    <>
                      <Lock className="size-3.5 shrink-0" />
                      <b className="text-xs font-medium text-text-1">Local original</b>
                      <span className="ml-auto inline-flex h-[18px] items-center rounded-xs border border-border px-1.5 text-2xs">Stays on this host</span>
                    </>
                  }
                >
                  <Capped text={o.text}>{(t) => <HighlightedText parts={buildOriginalParts(t, redactions, i)} activeKey={active} onHover={setActive} />}</Capped>
                </Pane>
                <Pane
                  className="border-t border-border-subtle @xl:border-l @xl:border-t-0"
                  head={
                    blocked ? (
                      <>
                        <Ban className="size-3.5 shrink-0 text-block" />
                        <b className="text-xs font-medium text-block">Blocked</b>
                        <span className="min-w-0 [overflow-wrap:anywhere]">nothing was sent to {destName}</span>
                      </>
                    ) : (
                      <>
                        <Send className="size-3.5 shrink-0" />
                        <b className="text-xs font-medium text-text-1">On the wire</b>
                        <span className="min-w-0 truncate font-mono text-2xs" title={destName}>
                          to {destName}
                        </span>
                        <span className="ml-auto inline-flex h-[18px] shrink-0 items-center gap-1 rounded-xs border border-allow/30 bg-allow/10 px-1.5 text-2xs text-allow">
                          <ShieldCheck className="size-3" />
                          Minimized
                        </span>
                      </>
                    )
                  }
                >
                  {blocked ? (
                    <div className="grid min-h-20 place-items-center rounded-sm border border-dashed border-block/30 bg-block/5 px-3 py-4 text-center text-xs text-block">
                      <span className="inline-flex items-center gap-2">
                        <EyeOff className="size-4 shrink-0" /> Stopped in-line. 0 bytes left the host.
                      </span>
                    </div>
                  ) : w ? (
                    <Capped text={w.text}>{(t) => <HighlightedText parts={buildOutboundParts(t, redactions, i)} activeKey={active} onHover={setActive} animate={animate} />}</Capped>
                  ) : (
                    <span className="text-xs text-text-4">Segment not sent</span>
                  )}
                </Pane>
                <span className="absolute left-1/2 top-1/2 z-[1] hidden size-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-border bg-surface-2 text-text-3 @xl:grid" aria-hidden>
                  <ArrowRight className="size-3" />
                </span>
              </div>
            </div>
          );
        })}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border-subtle bg-surface-2/40 px-4 py-2">
          <RedactionLegend />
          <span className="ml-auto hidden text-2xs text-text-3 md:inline">Hover a span to trace it across panes</span>
          {hidden > 0 || showAll ? (
            <button type="button" className="min-h-8 text-xs text-accent-fg hover:underline" onClick={() => setShowAll((v) => !v)}>
              {showAll ? 'Only changed segments' : `Show all ${wire.original.length} segments`}
            </button>
          ) : null}
        </div>
      </div>

      {wire.response_raw || wire.response_local ? (
        <ResponsePanes raw={wire.response_raw} local={wire.response_local} redactions={redactions} originals={originals} activeKey={active} onHover={setActive} animate={animate} />
      ) : null}

      {showTable && redactions.length ? (
        <div className="overflow-hidden rounded-md border border-border bg-surface-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b border-border px-4 py-2.5">
            <div className="text-[13px] font-semibold text-text-1">Detected entities</div>
            <div className="text-2xs text-text-3">Audit stores keyed HMAC fingerprints, never raw values</div>
          </div>
          <EntityTable redactions={redactions} originals={originals} activeKey={active} onHover={setActive} />
        </div>
      ) : null}
    </div>
  );
}
