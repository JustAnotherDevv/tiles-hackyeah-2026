import type { ReactNode } from 'react';

export interface BarListItem {
  key: string;
  label: ReactNode;
  value: number;
  color?: string;
  hint?: ReactNode;
  href?: string;
}

export function BarList({ items, valueFormat = (n) => String(n), max, limit, emptyText = 'No data' }: { items: BarListItem[]; valueFormat?: (n: number) => string; max?: number; limit?: number; emptyText?: string }) {
  const shown = limit ? items.slice(0, limit) : items;
  if (shown.length === 0) return <div className="py-6 text-center text-xs text-text-3">{emptyText}</div>;
  const top = max ?? Math.max(...shown.map((i) => i.value), 1);
  return (
    <ul className="space-y-1.5">
      {shown.map((i) => (
        <li key={i.key} className="relative overflow-hidden rounded-md bg-surface-2">
          <div className="absolute inset-y-0 left-0 opacity-25" style={{ width: `${(i.value / top) * 100}%`, background: i.color ?? '#6366F1' }} />
          <div className="relative flex items-center justify-between px-2.5 py-1.5 text-xs">
            <span className="truncate">{i.label}</span>
            <span className="tabular text-text-2">{valueFormat(i.value)}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}
