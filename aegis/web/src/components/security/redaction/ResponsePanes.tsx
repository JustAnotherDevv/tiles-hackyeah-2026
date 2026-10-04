// "Model returned" (placeholders only) ↔ "You see · rehydrated locally" (restored values in green).
import { ArrowDown, ArrowRight, User } from '@/components/icons';
import { useMemo } from 'react';
import type { Redaction } from '@/api/types';
import { buildResponseParts } from '../lib/redactionDiff';
import { HighlightedText } from './HighlightedText';

export function ResponsePanes({
  raw,
  local,
  redactions,
  originals,
  activeKey,
  onHover,
  animate,
}: {
  raw: string | null;
  local: string | null;
  redactions: Redaction[];
  originals: Map<string, string>;
  activeKey?: string | null;
  onHover?: (k: string | null) => void;
  animate?: boolean;
}) {
  const rawParts = useMemo(() => (raw ? buildResponseParts(raw, 'raw', redactions, originals) : []), [raw, redactions, originals]);
  const localParts = useMemo(() => (local ? buildResponseParts(local, 'local', redactions, originals) : []), [local, redactions, originals]);
  const restored = localParts.filter((p) => p.kind === 'restored').length;
  return (
    <div className="@container overflow-hidden rounded-md border border-border bg-surface-1">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b border-border px-4 py-2.5">
        <div className="text-[13px] font-semibold text-text-1">Response</div>
        <div className="text-2xs text-text-3">Placeholders are rehydrated locally, only for the requesting user{restored ? ` · ${restored} restored` : ''}</div>
      </div>
      <div className="relative grid grid-cols-1 @xl:grid-cols-2">
        <div className="min-w-0 px-4 pb-4 pt-3">
          <div className="mb-2.5 flex items-center gap-2 text-xs text-text-3">
            <ArrowDown className="size-3.5" />
            <b className="text-xs font-medium text-text-1">Model returned</b>
            <span>Placeholders only</span>
          </div>
          {raw ? <HighlightedText parts={rawParts} activeKey={activeKey} onHover={onHover} /> : <span className="text-xs text-text-4">—</span>}
        </div>
        <div className="min-w-0 border-t border-border-subtle px-4 pb-4 pt-3 @xl:border-l @xl:border-t-0">
          <div className="mb-2.5 flex items-center gap-2 text-xs text-text-3">
            <User className="size-3.5" />
            <b className="text-xs font-medium text-text-1">You see</b>
            <span>Rehydrated locally</span>
          </div>
          {local ? <HighlightedText parts={localParts} activeKey={activeKey} onHover={onHover} animate={animate} /> : <span className="text-xs text-text-4">—</span>}
        </div>
        <span className="absolute left-1/2 top-1/2 z-[1] hidden size-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-border bg-surface-2 text-text-3 @xl:grid" aria-hidden>
          <ArrowRight className="size-3" />
        </span>
      </div>
    </div>
  );
}
