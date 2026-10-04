// Semantic change list for a policy draft (UIG-04): PolicyChange.summary with a kind icon; loosening
// changes rose with ShieldOff, tightening emerald. Owner: B19-dashboard-gov-policy.
import { ShieldOff } from 'lucide-react';
import type { PolicyChange } from '@/api/types';
import { changeKindMeta } from '@/components/governance/lib/format-gov';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '∅';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  const s = JSON.stringify(v);
  return s.length > 40 ? `${s.slice(0, 39)}…` : s;
}

export function ChangeList({ changes, compact = false, empty = 'No semantic changes yet — edit the YAML or use a quick edit.' }: { changes: PolicyChange[]; compact?: boolean; empty?: string }) {
  if (changes.length === 0) return <div className="py-2 text-xs text-text-3">{empty}</div>;
  return (
    <ul className="space-y-1.5">
      {changes.map((c, i) => {
        const m = changeKindMeta(c.kind, c.loosening);
        const Icon = m.loosening ? ShieldOff : resolveIcon(m.icon);
        return (
          <li
            key={`${c.path}-${i}`}
            className={cn(
              'flex items-start gap-2 rounded-md border px-2.5 py-1.5',
              m.tone === 'loosen' ? 'border-block/25 bg-block/[0.06]' : m.tone === 'tighten' ? 'border-allow/25 bg-allow/[0.06]' : 'border-border bg-surface-1',
            )}
          >
            <Icon className={cn('mt-0.5 size-3.5 shrink-0', m.tone === 'loosen' ? 'text-block' : m.tone === 'tighten' ? 'text-allow' : 'text-text-3')} />
            <div className="min-w-0 flex-1">
              <div className={cn('text-xs', m.tone === 'loosen' ? 'text-block' : 'text-text-1')}>{c.summary || `${m.label} · ${c.path}`}</div>
              {!compact ? (
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 font-mono text-2xs text-text-3">
                  <span className="truncate">{c.path}</span>
                  {c.before !== undefined || c.after !== undefined ? (
                    <span>
                      {fmtVal(c.before)} → <span className="text-text-2">{fmtVal(c.after)}</span>
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
            <span className={cn('shrink-0 rounded px-1.5 py-px text-[10px] font-medium uppercase tracking-wide', m.tone === 'loosen' ? 'bg-block/15 text-block' : m.tone === 'tighten' ? 'bg-allow/15 text-allow' : 'bg-surface-3 text-text-3')}>
              {m.tone === 'loosen' ? 'loosens' : m.tone === 'tighten' ? 'tightens' : 'neutral'}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
