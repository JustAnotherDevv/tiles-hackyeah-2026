// Detected entities table (type · original (local) · sent as · control · reversible), hover-linked to the panes.
import type { Redaction } from '@/api/types';
import { cn } from '@/lib/utils';
import { ControlChip } from '../common/atoms';
import { dataClassColor } from '../common/colors';
import { keyedRedactions } from '../lib/redactionDiff';

export function EntityTable({
  redactions,
  originals,
  activeKey,
  onHover,
}: {
  redactions: Redaction[];
  originals: Map<string, string>;
  activeKey?: string | null;
  onHover?: (key: string | null) => void;
}) {
  const segs = Array.from(new Set(redactions.map((r) => r.segment_index))).sort((a, b) => a - b);
  const rows = segs.flatMap((s) => keyedRedactions(redactions, s));
  if (!rows.length) return <div className="px-4 py-6 text-center text-xs text-text-3">No entities were redacted.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full whitespace-nowrap text-xs">
        <thead>
          <tr className="border-b border-border text-left text-2xs uppercase tracking-[0.06em] text-text-3">
            <th className="px-4 py-2 font-medium">Type</th>
            <th className="px-2 py-2 font-medium">Original (local only)</th>
            <th className="px-2 py-2 font-medium">Sent as</th>
            <th className="px-2 py-2 font-medium">Control</th>
            <th className="px-4 py-2 text-right font-medium">Reversible</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ key, r }) => {
            const color = dataClassColor(r.data_class);
            const dropped = r.placeholder.startsWith('[REDACTED:');
            return (
              <tr
                key={key}
                onMouseEnter={onHover ? () => onHover(key) : undefined}
                onMouseLeave={onHover ? () => onHover(null) : undefined}
                className={cn('border-b border-border-subtle transition-colors last:border-0', activeKey === key ? 'bg-surface-3' : 'hover:bg-surface-2')}
              >
                <td className="px-4 py-1.5">
                  <span className="inline-flex items-center gap-2">
                    <span className="size-2 shrink-0 rounded-[2px]" style={{ background: color }} />
                    <span className="font-mono">{r.entity}</span>
                    <span className="text-2xs text-text-4">{r.data_class ?? ''}</span>
                  </span>
                </td>
                <td className="max-w-[220px] truncate px-2 py-1.5 font-mono text-text-2" title={originals.get(r.placeholder) ?? undefined}>{originals.get(r.placeholder) ?? <span className="text-text-4">not retained</span>}</td>
                <td className="px-2 py-1.5 font-mono">
                  <span className={cn(dropped ? 'text-block line-through' : '')} style={dropped ? undefined : { color }}>
                    {r.placeholder}
                  </span>
                </td>
                <td className="px-2 py-1.5">
                  <ControlChip id={r.control_id} />
                </td>
                <td className="px-4 py-1.5 text-right">{r.reversible ? <span className="text-allow">Yes · vault</span> : dropped ? <span className="text-block">No · dropped</span> : <span className="text-orange-300">No · masked</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
