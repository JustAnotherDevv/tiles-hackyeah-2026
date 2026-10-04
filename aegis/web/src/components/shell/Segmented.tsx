// Segmented control with a sliding thumb (DESIGN_TOKENS §6; framer layoutId, 220 ms expo-out).
import { LayoutGroup, motion } from 'framer-motion';
import { useId, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

export interface SegmentedOption<V extends string> {
  value: V;
  label: ReactNode;
  title?: string;
  disabled?: boolean;
}

export function Segmented<V extends string>({
  value,
  options,
  onChange,
  size = 'md',
  className,
  ariaLabel,
}: {
  value: V;
  options: SegmentedOption<V>[];
  onChange: (v: V) => void;
  size?: 'md' | 'lg';
  className?: string;
  ariaLabel?: string;
}) {
  const id = useId();
  return (
    <LayoutGroup id={id}>
      <div role="radiogroup" aria-label={ariaLabel} className={cn('relative inline-flex shrink-0 rounded-md border border-border bg-surface-1 p-0.5', className)}>
        {options.map((o) => {
          const on = o.value === value;
          return (
            <button
              key={o.value}
              type="button"
              role="radio"
              aria-checked={on}
              title={o.title}
              disabled={o.disabled}
              onClick={() => !on && onChange(o.value)}
              className={cn(
                'relative z-[1] inline-flex items-center gap-1.5 whitespace-nowrap rounded-[4px] font-medium transition-colors duration-150 disabled:opacity-40',
                size === 'lg' ? 'h-7 px-3 text-[12.5px] max-md:h-9' : 'h-6 px-2.5 text-xs max-md:h-8',
                on ? 'text-text-1' : 'text-text-3 hover:text-text-2',
              )}
            >
              {on ? (
                <motion.span
                  layoutId="thumb"
                  className="absolute inset-0 -z-[1] rounded-[4px] bg-surface-4"
                  style={{ boxShadow: 'inset 0 1px 0 rgba(255,255,255,.06), 0 1px 2px rgba(0,0,0,.5), 0 0 0 1px #2A2F37' }}
                  transition={{ duration: 0.14, ease: [0.16, 1, 0.3, 1] }}
                />
              ) : null}
              {o.label}
            </button>
          );
        })}
      </div>
    </LayoutGroup>
  );
}
