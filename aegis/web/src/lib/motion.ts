// Shared framer-motion presets (DESIGN_TOKENS §5 "copy these exactly"). Owner: dashboard-shell (B16).
import { useReducedMotion, type Transition, type Variants } from 'framer-motion';

export const ease = {
  out: [0.16, 1, 0.3, 1],
  inOut: [0.65, 0, 0.35, 1],
  in: [0.7, 0, 0.84, 0],
} as const;

export const dur = { instant: 0.08, fast: 0.14, base: 0.22, slow: 0.36, slower: 0.64 } as const;

export const springSnappy: Transition = { type: 'spring', stiffness: 420, damping: 30 };

/** Page enter: opacity 0→1, y 6→0 over 360 ms expo-out. */
export const pageTransition = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0 },
  transition: { duration: dur.slow, ease: ease.out },
} as const;

/** Generic fade-up (cards, tiles). */
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.42, ease: ease.out } },
};

/** Container variants that stagger children (40 ms default). */
export function stagger(step = 0.04, delayChildren = 0): Variants {
  return { hidden: {}, show: { transition: { staggerChildren: step, delayChildren } } };
}

/** Per-index stagger helper (trace stages, lists): x −6→0 over 420 ms. */
export const staggerItem = (i: number, step = 0.045) => ({
  initial: { opacity: 0, x: -6 },
  animate: { opacity: 1, x: 0 },
  transition: { delay: i * step, duration: 0.42, ease: ease.out },
});

/** Live list item: slides in from above with height growth. */
export const listItem: Variants = {
  hidden: { opacity: 0, y: -10, height: 0 },
  show: { opacity: 1, y: 0, height: 'auto', transition: { duration: 0.5, ease: ease.out } },
  exit: { opacity: 0, transition: { duration: 0.2, ease: ease.in } },
};

export const drawer = {
  initial: { x: '104%' },
  animate: { x: 0 },
  exit: { x: '104%' },
  transition: { duration: dur.slow, ease: ease.out },
} as const;

export const modal = {
  initial: { opacity: 0, scale: 0.98, y: 8 },
  animate: { opacity: 1, scale: 1, y: 0 },
  exit: { opacity: 0, scale: 0.98 },
  transition: { duration: dur.slow, ease: ease.out },
} as const;

/** True when motion is allowed (respects prefers-reduced-motion). */
export function useMotionSafe(): boolean {
  return !useReducedMotion();
}
