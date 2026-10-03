// KPI tile (DESIGN_TOKENS §6): label + icon → 28 px tabular value (count-up, bump on increase) →
// foot (delta pill + hint) → 28 px sparkline. Optional tone accent hairline, footer slot and link.
import type { LucideIcon } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Sparkline } from '@/components/charts/Sparkline';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';
import { AnimatedNumber } from './AnimatedNumber';

export interface KpiTileProps {
  label: ReactNode;
  value: ReactNode | number;
  /** signed % change */
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
  /** small muted suffix after the value, e.g. "/ $150" */
  suffix?: ReactNode;
  /** right side of the label row (badge) */
  right?: ReactNode;
  sparkColor?: string;
  className?: string;
}

const TONE_FG: Record<NonNullable<KpiTileProps['tone']>, string> = {
  neutral: '#7A808C',
  good: '#1E9F68',
  warn: '#C98500',
  bad: '#E5446D',
};
const BUMP: Record<NonNullable<KpiTileProps['tone']>, string> = {
  neutral: 'var(--accent-fg)',
  good: 'var(--allow)',
  warn: 'var(--redact)',
  bad: 'var(--block)',
};

function DeltaPill({ delta, goodWhen }: { delta: number; goodWhen: 'up' | 'down' }) {
  const flat = Math.abs(delta) < 0.05;
  const good = (delta >= 0) === (goodWhen === 'up');
  return (
    <span
      className={cn(
        'inline-flex h-[18px] items-center gap-0.5 rounded-[5px] px-[5px] text-[11.5px] font-medium tabular',
        flat ? 'bg-surface-2 text-text-2' : good ? 'bg-allow/10 text-allow' : 'bg-block/10 text-block',
      )}
    >
      {flat ? '±' : delta > 0 ? '▲' : '▼'} {Math.abs(delta).toFixed(1)}%
    </span>
  );
}

export function KpiTile({ label, value, delta, deltaGoodWhen = 'up', hint, icon, tone = 'neutral', sparkline, format, footer, href, loading, suffix, right, sparkColor, className }: KpiTileProps) {
  const Icon = typeof icon === 'string' ? resolveIcon(icon) : icon;
  const numeric = typeof value === 'number';
  const prev = useRef<number | null>(numeric ? value : null);
  const [bump, setBump] = useState(0);
  useEffect(() => {
    if (!numeric || loading) return;
    // first real value counts up from 0 (no bump); later increases flash without restarting the count-up
    if (prev.current !== null && prev.current > 0 && value > prev.current) setBump((b) => b + 1);
    prev.current = value;
  }, [value, numeric, loading]);

  const body = (
    <>
      {tone !== 'neutral' ? (
        <span className="pointer-events-none absolute inset-x-4 top-0 h-px" style={{ background: `linear-gradient(90deg, transparent, ${TONE_FG[tone]}, transparent)`, opacity: 0.7 }} />
      ) : null}
      <div className="flex items-center gap-1.5 text-xs leading-4 text-text-3">
        {Icon ? <Icon className="size-3.5 shrink-0" /> : null}
        <span className="truncate">{label}</span>
        {right ? <span className="ml-auto shrink-0">{right}</span> : null}
      </div>
      <div className="flex items-baseline gap-1 whitespace-nowrap">
        {loading ? (
          <span className="skel my-1 inline-block h-6 w-24" />
        ) : (
          <span
            key={bump}
            className={cn('text-2xl font-semibold tracking-[-0.03em] text-text-1 tabular', bump > 0 && 'value-bump')}
            style={{ ['--bump-color' as string]: BUMP[tone] }}
          >
            {numeric ? <AnimatedNumber value={value} format={format} from0={bump === 0} /> : value}
          </span>
        )}
        {suffix && !loading ? <span className="text-sm font-medium tracking-[-0.01em] text-text-3">{suffix}</span> : null}
      </div>
      {delta !== undefined || hint ? (
        <div className="flex min-h-[18px] items-center gap-2 overflow-hidden whitespace-nowrap text-[11.5px] text-text-3">
          {delta !== undefined && Number.isFinite(delta) ? <DeltaPill delta={delta} goodWhen={deltaGoodWhen} /> : null}
          {hint ? <span className="truncate">{hint}</span> : null}
        </div>
      ) : null}
      {sparkline && sparkline.length > 1 ? (
        <div className="mt-0.5 h-7">
          <Sparkline data={sparkline} color={sparkColor ?? TONE_FG[tone]} height={28} />
        </div>
      ) : null}
      {footer}
    </>
  );
  const cls = cn(
    'relative flex min-w-0 flex-col gap-1.5 overflow-hidden rounded-lg border border-border bg-card px-4 pb-3 pt-3.5 shadow-card',
    href && 'transition-colors duration-150 hover:border-border-strong',
    className,
  );
  return href ? (
    <Link to={href} className={cls}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}
