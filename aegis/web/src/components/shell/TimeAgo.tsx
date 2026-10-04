// Relative time with ONE shared 5 s ticker for the whole app (no interval per row); absolute time in title.
import { useSyncExternalStore } from 'react';
import { fmtAgo, fmtAgoShort, fmtDateTime } from '@/lib/format';

let now = Date.now();
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | null = null;

function subscribe(l: () => void) {
  listeners.add(l);
  if (!timer) {
    timer = setInterval(() => {
      now = Date.now();
      listeners.forEach((x) => x());
    }, 5000);
  }
  return () => {
    listeners.delete(l);
    if (listeners.size === 0 && timer) {
      clearInterval(timer);
      timer = null;
    }
  };
}
const getNow = () => now;

/** Current time that re-renders every 5 s (shared). */
export function useNow(): number {
  return useSyncExternalStore(subscribe, getNow, getNow);
}

export function TimeAgo({ ts, short = false, className }: { ts: string | number; short?: boolean; className?: string }) {
  const n = useNow();
  const d = new Date(ts);
  const valid = !Number.isNaN(d.getTime());
  return (
    <time className={className ?? 'tabular text-text-3'} dateTime={valid ? d.toISOString() : undefined} title={fmtDateTime(ts)}>
      {short ? fmtAgoShort(ts, Math.max(n, Date.now())) : fmtAgo(ts)}
    </time>
  );
}
