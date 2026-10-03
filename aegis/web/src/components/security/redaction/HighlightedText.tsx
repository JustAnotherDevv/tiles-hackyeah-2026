// Renders DiffPart[] with entity / placeholder / dropped / restored spans and shared-key hover linking.
import { motion, useReducedMotion } from 'framer-motion';
import { memo, type CSSProperties } from 'react';
import { cn } from '@/lib/utils';
import { dataClassColor, DROPPED_COLOR, RESTORED_COLOR } from '../common/colors';
import type { DiffPart } from '../types';

function spanStyle(p: DiffPart, active: boolean): CSSProperties {
  const c = p.kind === 'dropped' ? DROPPED_COLOR : p.kind === 'restored' ? RESTORED_COLOR : dataClassColor(p.dataClass);
  const mix = (pct: number) => `color-mix(in srgb, ${c} ${pct}%, transparent)`;
  const base: CSSProperties = { borderRadius: 5, padding: '1px 4px', margin: '0 1px', boxDecorationBreak: 'clone', WebkitBoxDecorationBreak: 'clone', transition: 'background 120ms, box-shadow 120ms' };
  if (active) return { ...base, background: mix(28), boxShadow: `inset 0 0 0 1.5px ${c}, 0 0 0 3px ${mix(18)}`, color: 'var(--text-1)' };
  switch (p.kind) {
    case 'entity':
      return { ...base, background: mix(13), boxShadow: `inset 0 -1.5px 0 0 ${mix(80)}`, color: 'var(--text-1)' };
    case 'placeholder':
    case 'masked':
      return { ...base, background: mix(16), boxShadow: `inset 0 0 0 1px ${mix(45)}`, color: `color-mix(in srgb, ${c} 60%, white)` };
    case 'dropped':
      return { ...base, background: mix(12), boxShadow: `inset 0 0 0 1px ${mix(35)}`, color: c, textDecoration: 'line-through', textDecorationColor: mix(70) };
    case 'restored':
      return { ...base, background: mix(12), boxShadow: `inset 0 -1.5px 0 0 ${c}`, color: 'var(--text-1)' };
    default:
      return base;
  }
}

export const HighlightedText = memo(function HighlightedText({
  parts,
  activeKey,
  onHover,
  animate = false,
  className,
}: {
  parts: DiffPart[];
  activeKey?: string | null;
  onHover?: (key: string | null) => void;
  /** Stagger-in placeholders (playground reveal). */
  animate?: boolean;
  className?: string;
}) {
  const reduce = useReducedMotion();
  let tokenIdx = 0;
  return (
    <div className={cn('whitespace-pre-wrap break-words text-[13.5px] leading-[26px] text-text-2', className)}>
      {parts.map((p, i) => {
        if (p.kind === 'text') return <span key={i}>{p.text}</span>;
        const mono = p.kind !== 'entity' && p.kind !== 'restored';
        const title = [p.entity, p.dataClass, p.kind === 'dropped' ? 'dropped irreversibly (PCI)' : p.kind === 'restored' ? 'rehydrated locally' : p.placeholder !== p.text ? `→ ${p.placeholder}` : null]
          .filter(Boolean)
          .join(' · ');
        const common = {
          title,
          'data-ek': p.key,
          onMouseEnter: p.key && onHover ? () => onHover(p.key ?? null) : undefined,
          onMouseLeave: p.key && onHover ? () => onHover(null) : undefined,
          className: cn('cursor-default', mono && 'font-mono text-[12.5px]'),
          style: spanStyle(p, Boolean(p.key && activeKey === p.key)),
        };
        if (animate && !reduce) {
          const delay = 0.05 * tokenIdx++;
          return (
            <motion.span key={i} {...common} initial={{ opacity: 0, filter: 'blur(3px)' }} animate={{ opacity: 1, filter: 'blur(0px)' }} transition={{ delay, duration: 0.35 }}>
              {p.text}
            </motion.span>
          );
        }
        return (
          <span key={i} {...common}>
            {p.text}
          </span>
        );
      })}
    </div>
  );
});
