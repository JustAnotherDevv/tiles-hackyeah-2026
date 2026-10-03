// Formatting helpers (CONTRACTS §5.4 `@/lib/format`). All return "—" for null/undefined/NaN.
// fmtPct takes 0–100 (API *_pct fields); fmtRatio takes 0–1 (scores/thresholds).
// Owner: dashboard-shell (scaffold seed).
import { formatDistanceToNowStrict } from 'date-fns';

const DASH = '—';
type Num = number | null | undefined;
const bad = (v: Num): v is null | undefined => v === null || v === undefined || Number.isNaN(v);

export function fmtNum(v: Num, opts: { dp?: number; compact?: boolean } = {}): string {
  if (bad(v)) return DASH;
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: opts.dp ?? 0,
    minimumFractionDigits: opts.dp ?? 0,
    notation: opts.compact ? 'compact' : 'standard',
  }).format(v);
}

export function fmtUsd(v: Num, opts: { dp?: number; compact?: boolean } = {}): string {
  if (bad(v)) return DASH;
  const dp = opts.dp ?? (Math.abs(v) < 1 && v !== 0 ? 4 : 2);
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: dp,
    minimumFractionDigits: Math.min(dp, 2),
    notation: opts.compact ? 'compact' : 'standard',
  }).format(v);
}

export function fmtPct(pct: Num, dp = 0): string {
  return bad(pct) ? DASH : `${pct.toFixed(dp)}%`;
}

export function fmtRatio(r: Num, dp = 0): string {
  return bad(r) ? DASH : `${(r * 100).toFixed(dp)}%`;
}

export function fmtCompact(n: Num): string {
  return fmtNum(n, { compact: true, dp: n !== null && n !== undefined && Math.abs(n) >= 1000 ? 1 : 0 });
}

export function fmtMs(ms: Num): string {
  if (bad(ms)) return DASH;
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 1000) return `${ms.toFixed(ms < 10 ? 1 : 0)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function toDate(ts: string | number | null | undefined): Date | null {
  if (ts === null || ts === undefined) return null;
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtTime(ts: string | number | null | undefined, opts: { seconds?: boolean } = {}): string {
  const d = toDate(ts);
  if (!d) return DASH;
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: opts.seconds ? '2-digit' : undefined });
}

export function fmtDateTime(ts: string | number | null | undefined): string {
  const d = toDate(ts);
  return d ? d.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : DASH;
}

export function fmtAgo(ts: string | number | null | undefined): string {
  const d = toDate(ts);
  return d ? `${formatDistanceToNowStrict(d)} ago` : DASH;
}

export function fmtDuration(seconds: Num): string {
  if (bad(seconds)) return DASH;
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}
