// Ring gauge (SVG, framer pathLength draw over 1.1 s). tone 'auto' derives from value/max:
// ≥ 85 % good, ≥ 70 % warn, else bad (posture-score convention).
import { motion, useReducedMotion } from 'framer-motion';

export interface GaugeProps {
  value: number;
  max: number;
  label: string;
  sublabel?: string;
  tone?: 'auto' | 'good' | 'warn' | 'bad' | 'neutral';
  size?: number;
  format?: (v: number) => string;
  stroke?: number;
}

const TONES = { good: '#1E9F68', warn: '#C98500', bad: '#E5446D', neutral: '#6366F1' } as const;

export function Gauge({ value, max, label, sublabel, tone = 'auto', size = 72, format, stroke }: GaugeProps) {
  const reduce = useReducedMotion();
  const ratio = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const t = tone === 'auto' ? (ratio >= 0.85 ? 'good' : ratio >= 0.7 ? 'warn' : 'bad') : tone;
  const sw = stroke ?? Math.max(5, Math.round(size / 10));
  const r = (size - sw) / 2;
  const c = size / 2;
  return (
    <div className="relative inline-grid shrink-0 place-items-center" style={{ width: size, height: size }} role="img" aria-label={`${label}: ${value} of ${max}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={c} cy={c} r={r} fill="none" stroke="#191C21" strokeWidth={sw} />
        <motion.circle
          cx={c}
          cy={c}
          r={r}
          fill="none"
          stroke={TONES[t]}
          strokeWidth={sw}
          strokeLinecap="round"
          initial={reduce ? false : { pathLength: 0 }}
          animate={{ pathLength: ratio }}
          transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1] }}
          style={{ filter: `drop-shadow(0 0 6px ${TONES[t]}55)` }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <div className="font-semibold leading-none tracking-[-0.03em] text-text-1 tabular" style={{ fontSize: Math.round(size * 0.28) }}>
            {format ? format(value) : Math.round(value)}
          </div>
          {sublabel ? <div className="mt-0.5 text-[10px] leading-none text-text-3">{sublabel}</div> : null}
        </div>
      </div>
    </div>
  );
}
