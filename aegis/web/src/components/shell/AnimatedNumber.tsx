// Number tween (DESIGN_TOKENS §5: 600 ms ease-out-quart). Counts up from 0 on first mount only when
// `from0` is set; afterwards tweens from the previous value. Reduced motion → no tween.
import { animate, useReducedMotion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { fmtNum } from '@/lib/format';

export interface AnimatedNumberProps {
  value: number;
  format?: (n: number) => string;
  /** seconds (default 0.6) */
  duration?: number;
  /** count up from 0 on first mount (default true) */
  from0?: boolean;
  className?: string;
}

export function AnimatedNumber({ value, format = (n) => fmtNum(n), duration = 0.6, from0 = true, className }: AnimatedNumberProps) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(() => (from0 && !reduce ? 0 : value));
  const prev = useRef(from0 && !reduce ? 0 : value);
  useEffect(() => {
    if (!Number.isFinite(value)) return;
    if (reduce) {
      prev.current = value;
      setShown(value);
      return;
    }
    const controls = animate(prev.current, value, {
      duration,
      ease: [0.25, 1, 0.5, 1],
      onUpdate: (v) => setShown(v),
    });
    prev.current = value;
    return () => controls.stop();
  }, [value, duration, reduce]);
  return <span className={className ?? 'tabular'}>{Number.isFinite(value) ? format(shown) : '—'}</span>;
}
