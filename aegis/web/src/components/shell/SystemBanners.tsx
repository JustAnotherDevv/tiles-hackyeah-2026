// Persistent banners under the topbar (docs/plan/15 §2.8): kill switch engaged (initialised from
// /api/budgets, kept fresh by `killswitch` SSE events), feed update rejected (until a later feed.updated),
// and "live updates offline" after 10 s offline (never when mocks are forced). Owner: dashboard-shell (B16).
import { AnimatePresence, motion } from 'framer-motion';
import { Power, ShieldAlert, WifiOff, X } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { eventHub } from '@/api/sse';
import { useApi, useSseStatus } from '@/api/hooks';
import type { BudgetsResponse } from '@/api/types';
import { cn } from '@/lib/utils';
import { mockBudgets } from '@/mocks/shell/budgets';
import { killActive, killScopes, setShellState, useShellState } from './shellStore';

function Banner({ tone, icon, children, actions }: { tone: 'bad' | 'warn'; icon: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className="overflow-hidden"
    >
      <div
        className={cn(
          'flex min-h-9 items-center gap-2.5 border-b px-6 py-1.5 text-[12.5px]',
          tone === 'bad' ? 'border-block/30 bg-[linear-gradient(90deg,rgba(225,29,72,0.16),rgba(225,29,72,0.05))] text-[#FECDD3]' : 'border-redact/25 bg-redact/[0.07] text-[#FDE68A]',
        )}
        role="status"
      >
        <span className={cn('grid size-5 shrink-0 place-items-center rounded-md', tone === 'bad' ? 'bg-block/20 text-block' : 'bg-redact/15 text-redact')}>{icon}</span>
        <div className="min-w-0 flex-1 truncate">{children}</div>
        {actions}
      </div>
    </motion.div>
  );
}

function useOfflineFor(ms: number): boolean {
  const status = useSseStatus();
  const [late, setLate] = useState(false);
  useEffect(() => {
    if (status !== 'offline') {
      setLate(false);
      return;
    }
    const t = setTimeout(() => setLate(true), ms);
    return () => clearTimeout(t);
  }, [status, ms]);
  return late;
}

export function SystemBanners() {
  const budgets = useApi<BudgetsResponse>('/api/budgets', { mock: mockBudgets, refreshOn: ['killswitch'] });
  const kill = useShellState((s) => s.kill);
  const killActor = useShellState((s) => s.killActor);
  const feedRejected = useShellState((s) => s.feedRejected);
  const offline = useOfflineFor(10_000);

  // initialise / refresh kill switch state from the budgets snapshot (real endpoint only — never from mocks)
  useEffect(() => {
    if (budgets.data && !budgets.isMock) setShellState({ kill: budgets.data.kill_switch });
  }, [budgets.data, budgets.isMock]);

  const scopes = killScopes(kill);
  return (
    <div className="no-print relative z-10">
      <AnimatePresence initial={false}>
        {killActive(kill) ? (
          <Banner
            key="kill"
            tone="bad"
            icon={<Power className="size-3" />}
            actions={
              <Link to="/governance/budgets" className="shrink-0 rounded-md border border-block/40 px-2 py-0.5 text-[11.5px] font-medium text-[#FECDD3] hover:bg-block/15">
                Manage
              </Link>
            }
          >
            <b className="font-semibold">Kill switch engaged</b>
            <span className="mx-2 text-block/60">·</span>
            <span className="font-mono text-[12px]">{scopes.join(', ')}</span>
            {killActor ? <span className="ml-2 text-[#FDA4AF]/80">by {killActor}</span> : null}
            <span className="ml-2 text-[#FDA4AF]/70">— matching traffic is stopped at the gateway (429 killed)</span>
          </Banner>
        ) : null}
        {feedRejected ? (
          <Banner
            key="feed"
            tone="bad"
            icon={<ShieldAlert className="size-3" />}
            actions={
              <>
                <Link to="/security/threats" className="shrink-0 rounded-md border border-block/40 px-2 py-0.5 text-[11.5px] font-medium text-[#FECDD3] hover:bg-block/15">
                  Details
                </Link>
                <button type="button" aria-label="Dismiss" className="grid size-6 place-items-center rounded-md text-[#FDA4AF] hover:bg-block/15" onClick={() => setShellState({ feedRejected: null })}>
                  <X className="size-3.5" />
                </button>
              </>
            }
          >
            <b className="font-semibold">Feed update rejected:</b> {feedRejected.reason}
            <span className="ml-2 text-[#FDA4AF]/80">— enforcement stays on #{feedRejected.keptSerial ?? '?'}</span>
            {feedRejected.attempted !== null ? <span className="ml-2 font-mono text-[11.5px] text-[#FDA4AF]/60">(attempted #{feedRejected.attempted})</span> : null}
          </Banner>
        ) : null}
        {offline ? (
          <Banner
            key="offline"
            tone="warn"
            icon={<WifiOff className="size-3" />}
            actions={
              <button type="button" className="shrink-0 rounded-md border border-redact/30 px-2 py-0.5 text-[11.5px] font-medium hover:bg-redact/10" onClick={() => eventHub.retryNow()}>
                Retry now
              </button>
            }
          >
            <b className="font-semibold">Live updates offline</b> — retrying. Panels show the last data (or demo data where marked).
          </Banner>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
