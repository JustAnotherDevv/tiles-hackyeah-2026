// Row B — live decision ticker (port of prototype startTicker): rAF marquee at ~45 px/s, new decisions are
// appended to the track as they arrive, pause on hover, click → decision detail. DOM capped at 30 items.
// Reduced motion → static row of the latest 6.
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDecisionBatches, useLiveDecisions } from '@/api/hooks';
import type { DecisionSummary } from '@/api/types';
import { fmtMs, truncate } from '@/lib/format';
import { useMotionSafe } from '@/lib/motion';
import { cn } from '@/lib/utils';
import { ActionBadge } from '../ActionBadge';
import { IdentityChip } from '../IdentityChip';
import { LiveDot } from '../LiveDot';

const SPEED = 45; // px per second (tuned for 1080p capture)
const MAX_ITEMS = 30;

function TickerItem({ d, onClick }: { d: DecisionSummary; onClick: () => void }) {
  return (
    <button
      type="button"
      data-id={d.id}
      onClick={onClick}
      className="group flex h-8 shrink-0 items-center gap-2 rounded-md px-2.5 text-[12.5px] whitespace-nowrap transition-colors hover:bg-surface-2"
    >
      <ActionBadge action={d.action} size="sm" />
      <IdentityChip identity={d.identity} />
      <span className="font-mono text-[11.5px] text-text-2">{d.control_id ?? d.surface}</span>
      <span className="max-w-[360px] truncate text-text-3">{truncate(d.preview || d.reason, 60)}</span>
      {d.redaction_count > 0 ? <span className="rounded border border-redact/25 bg-redact/[0.07] px-1 font-mono text-[10.5px] text-redact">{d.redaction_count}×</span> : null}
      <span className="font-mono text-[11px] text-text-4">{fmtMs(d.latency_ms)}</span>
      <span className="ml-1 h-3 w-px bg-border" />
    </button>
  );
}

export function LiveTicker() {
  const navigate = useNavigate();
  const motionOk = useMotionSafe();
  const { items, connected } = useLiveDecisions(MAX_ITEMS);
  const [track, setTrack] = useState<DecisionSummary[]>([]);
  const seeded = useRef(false);
  const trackRef = useRef<HTMLDivElement>(null);
  const offset = useRef(0);
  const paused = useRef(false);
  const dropped = useRef<string | null>(null);

  // seed from the buffer once (oldest → newest so the newest enters last)
  useEffect(() => {
    if (seeded.current || items.length === 0) return;
    seeded.current = true;
    setTrack(items.slice(0, 12).reverse());
  }, [items]);

  useDecisionBatches((batch) => {
    seeded.current = true;
    setTrack((t) => {
      const next = [...t, ...[...batch].reverse()];
      return next.length > MAX_ITEMS ? next.slice(next.length - MAX_ITEMS) : next;
    });
  });

  // rAF marquee: translate the track left; when the first child has fully left, drop it and compensate
  useEffect(() => {
    if (!motionOk) return;
    let raf = 0;
    let last = performance.now();
    const step = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const el = trackRef.current;
      if (el && !paused.current) {
        const parentW = el.parentElement?.clientWidth ?? 0;
        // only scroll when the track overflows the viewport
        if (el.scrollWidth - offset.current > parentW * 0.6) offset.current += SPEED * dt;
        const first = el.firstElementChild as HTMLElement | null;
        if (first && first.dataset.id !== dropped.current && offset.current > first.offsetWidth + 4 && el.childElementCount > 6) {
          dropped.current = first.dataset.id ?? null;
          offset.current -= first.offsetWidth + 2;
          setTrack((t) => t.slice(1));
        }
        el.style.transform = `translate3d(${-offset.current}px,0,0)`;
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [motionOk]);

  const shown = motionOk ? track : items.slice(0, 6);
  return (
    <div className="relative flex h-11 items-center overflow-hidden rounded-lg border border-border bg-card shadow-card">
      <div className="z-10 flex h-full shrink-0 items-center gap-2 border-r border-border-subtle bg-card pl-3.5 pr-3 text-[11.5px] font-medium uppercase tracking-[0.08em] text-text-3">
        <LiveDot paused={!connected} />
        Live
      </div>
      <div
        className="ticker-mask relative h-full min-w-0 flex-1 overflow-hidden"
        onMouseEnter={() => (paused.current = true)}
        onMouseLeave={() => (paused.current = false)}
      >
        {shown.length === 0 ? (
          <div className="flex h-full items-center px-4 text-[12.5px] text-text-3">{connected ? 'Waiting for traffic — run a demo agent or try the playground…' : 'Live stream not connected — decisions appear here as they happen.'}</div>
        ) : (
          <div ref={trackRef} className={cn('flex h-full items-center gap-0.5 pl-2 will-change-transform', !motionOk && 'overflow-hidden')}>
            {shown.map((d) => (
              <TickerItem key={d.id} d={d} onClick={() => navigate(`/security/decisions/${encodeURIComponent(d.id)}`)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
