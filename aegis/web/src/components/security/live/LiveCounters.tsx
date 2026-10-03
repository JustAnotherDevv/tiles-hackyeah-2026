// Header strip from the SSE `stats` tick (rps, decisions per action over the last minute, overhead p50/p95)
// + the compact audit-chain status used in the live-feed footer.
import { Link as LinkIcon, ShieldCheck, ShieldX } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useApi, useStatsTick } from '@/api/hooks';
import type { Action, AuditVerifyResult, DecisionSummary } from '@/api/types';
import { AnimatedNumber } from '@/components/shell';
import { ACTION_COLORS } from '@/lib/colors';
import { fmtMs, fmtNum } from '@/lib/format';
import { mockAuditVerify } from '@/mocks/security';
import { shortHash } from '../common/atoms';

const ORDER: Action[] = ['allow', 'redact', 'require_approval', 'block'];

function Tile({ label, children, accent }: { label: string; children: ReactNode; accent?: string }) {
  return (
    <div className="relative overflow-hidden rounded-lg border border-border bg-card px-3.5 py-2.5 shadow-card">
      {accent ? <span className="absolute inset-x-0 top-0 h-px" style={{ background: `linear-gradient(90deg, transparent, ${accent}, transparent)` }} /> : null}
      <div className="text-2xs uppercase tracking-[0.08em] text-text-3">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular text-text-1">{children}</div>
    </div>
  );
}

/** Live counters; falls back to counting the visible feed (last 60 s) until the first stats tick arrives. */
export function LiveCounters({ items }: { items: DecisionSummary[] }) {
  const tick = useStatsTick();
  const now = Date.now();
  const local: Record<Action, number> = { allow: 0, log: 0, redact: 0, require_approval: 0, block: 0 };
  if (!tick) for (const d of items) if (now - Date.parse(d.ts) < 60_000) local[d.action] += 1;
  const per = tick?.decisions_1m ?? local;
  const total = Object.values(per).reduce((a, b) => a + (b ?? 0), 0);
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
      <Tile label="Requests / s" accent="#6366F1">
        <AnimatedNumber value={tick?.rps ?? 0} format={(n) => n.toFixed(1)} from0={false} />
      </Tile>
      <Tile label="Decisions · 1 min">
        <AnimatedNumber value={total} from0={false} />
      </Tile>
      {ORDER.map((a) => (
        <Tile key={a} label={ACTION_COLORS[a].label} accent={ACTION_COLORS[a].chart}>
          <span style={{ color: (per[a] ?? 0) > 0 && a !== 'allow' ? ACTION_COLORS[a].fg : undefined }}>
            <AnimatedNumber value={per[a] ?? 0} from0={false} />
          </span>
        </Tile>
      ))}
      <Tile label="Overhead p50 · p95">
        <span className="text-base">
          {tick ? fmtMs(tick.p50_overhead_ms) : '—'} <span className="text-text-3">·</span> {tick ? fmtMs(tick.p95_overhead_ms) : '—'}
        </span>
      </Tile>
    </div>
  );
}

/** "audit chain verified · head 41d9…c07e" (cached ~60 s). */
export function AuditChainStatus() {
  const res = useApi<AuditVerifyResult>('/api/audit/verify', { mock: mockAuditVerify, refreshMs: 60_000 });
  const v = res.data;
  if (!v) return <span className="text-text-4">verifying audit chain…</span>;
  return (
    <Link to="/security/audit" className="inline-flex items-center gap-1.5 hover:text-text-1">
      {v.ok ? <ShieldCheck className="size-3.5 text-allow" /> : <ShieldX className="size-3.5 text-block" />}
      {v.ok ? (
        <span>
          audit chain verified · {fmtNum(v.records)} records · head <span className="font-mono">{shortHash(v.head_hash)}</span>
        </span>
      ) : (
        <span className="text-block">audit chain broken at seq {v.broken_at_seq}</span>
      )}
      <LinkIcon className="size-3 opacity-50" />
    </Link>
  );
}
