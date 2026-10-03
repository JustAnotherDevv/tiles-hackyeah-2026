import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { Sparkline } from '@/components/charts/Sparkline';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';

export interface KpiTileProps {
  label: ReactNode;
  value: ReactNode | number;
  delta?: number;
  deltaGoodWhen?: 'up' | 'down';
  hint?: ReactNode;
  icon?: string | LucideIcon;
  tone?: 'neutral' | 'good' | 'warn' | 'bad';
  sparkline?: number[];
  format?: (n: number) => string;
  footer?: ReactNode;
  href?: string;
  loading?: boolean;
}

const TONE: Record<NonNullable<KpiTileProps['tone']>, string> = {
  neutral: 'text-text-1',
  good: 'text-allow',
  warn: 'text-redact',
  bad: 'text-block',
};

export function KpiTile({ label, value, delta, deltaGoodWhen = 'up', hint, icon, tone = 'neutral', sparkline, format, footer, loading }: KpiTileProps) {
  const Icon = typeof icon === 'string' ? resolveIcon(icon) : icon;
  const shown = typeof value === 'number' && format ? format(value) : value;
  const good = delta === undefined ? null : (delta >= 0) === (deltaGoodWhen === 'up');
  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-card">
      <div className="flex items-center gap-1.5 text-xs text-text-3">
        {Icon ? <Icon className="size-3.5" /> : null}
        {label}
      </div>
      <div className={cn('mt-1 text-2xl font-semibold tabular', TONE[tone])}>{loading ? '…' : shown}</div>
      <div className="mt-1 flex items-center gap-2 text-xs text-text-3">
        {delta !== undefined ? (
          <span className={good ? 'text-allow' : 'text-block'}>
            {delta >= 0 ? '+' : ''}
            {delta.toFixed(1)}%
          </span>
        ) : null}
        {hint}
      </div>
      {sparkline && sparkline.length > 1 ? <Sparkline data={sparkline} /> : null}
      {footer}
    </div>
  );
}
