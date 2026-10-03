// Synthetic decision emitter — used ONLY when mocks are forced (CONTRACTS §5.4).
// Owner: dashboard-security.
import type { DecisionSummary } from '@/api/types';
import { makeMockDecision, toSummary } from './decisions';

/** Emits ~`ratePerSec` decisions with jitter; returns a stop function. */
export function startMockDecisionStream(onDecision: (d: DecisionSummary) => void, ratePerSec = 0.8, shouldEmit: () => boolean = () => true): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;
  const tick = () => {
    if (stopped) return;
    if (shouldEmit()) onDecision(toSummary(makeMockDecision()));
    const base = 1000 / Math.max(0.05, ratePerSec);
    timer = setTimeout(tick, base * (0.4 + Math.random() * 1.2));
  };
  timer = setTimeout(tick, 600);
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}
