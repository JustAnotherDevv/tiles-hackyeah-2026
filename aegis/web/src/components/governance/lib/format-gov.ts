// Governance formatting helpers — pure, erasable TS (type-only imports, no relative value imports).
// Icons are lucide PascalCase names (resolve with `resolveIcon` from @/lib/icons in components).
// Owner: B18-dashboard-gov-approvals. B19 imports this read-only.
import type { ApprovalKind, ApprovalStatus, ApproverLevel, BudgetDimension, BudgetWindow } from '@/api/types';

const usd2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const num0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });

export function fmtMoney(v: number | null | undefined, opts: { whole?: boolean } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  if (opts.whole || (Number.isInteger(v) && Math.abs(v) >= 100)) return usd0.format(v);
  return usd2.format(v);
}

/** Format a budget value by dimension: usd → $1,200.00 · tokens → 4.1M · compute_s → 1h 30m. */
export function fmtDimension(dim: BudgetDimension | string, v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  switch (dim) {
    case 'usd':
    case 'spend_usd':
      return fmtMoney(v);
    case 'tokens':
      return Math.abs(v) >= 10000 ? compact.format(v) : num0.format(v);
    case 'compute_s':
      return fmtSeconds(v);
    default:
      return Math.abs(v) >= 10000 ? compact.format(v) : num0.format(v);
  }
}

export function dimensionLabel(dim: BudgetDimension | string): string {
  return (
    ({ usd: 'USD', tokens: 'Tokens', compute_s: 'Compute', requests: 'Requests', tool_calls: 'Tool calls', spend_usd: 'Spend $' } as Record<string, string>)[dim] ??
    dim
  );
}

export function windowLabel(w: BudgetWindow | string): string {
  return ({ hour: 'hour', day: 'day', week: 'week', month: 'month', session: 'session', total: 'total' } as Record<string, string>)[w] ?? w;
}

export function fmtSeconds(s: number): string {
  const v = Math.round(s);
  if (v < 60) return `${v}s`;
  if (v < 3600) return `${Math.floor(v / 60)}m ${String(v % 60).padStart(2, '0')}s`;
  const h = Math.floor(v / 3600);
  const m = Math.floor((v % 3600) / 60);
  return `${h}h ${String(m).padStart(2, '0')}m`;
}

/** TTL seconds → "15 min", "1 h", "2 h". */
export function fmtTtl(s: number | null | undefined): string {
  if (s === null || s === undefined) return '—';
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  const h = s / 3600;
  return `${Number.isInteger(h) ? h : h.toFixed(1)} h`;
}

/** Countdown for ms remaining: "04:59", "1:02:03", "expired". */
export function fmtCountdown(ms: number): string {
  if (ms <= 0) return 'expired';
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** "team:trading" → {type: 'team', id: 'trading', label: 'Team · trading'}. */
export function scopeParts(scope: string): { type: string; id: string } {
  const i = scope.indexOf(':');
  return i < 0 ? { type: scope, id: '' } : { type: scope.slice(0, i), id: scope.slice(i + 1) };
}

export function scopeLabel(scope: string | null | undefined): string {
  if (!scope) return '—';
  if (scope === 'global') return 'Global';
  const { type, id } = scopeParts(scope);
  const t = type.charAt(0).toUpperCase() + type.slice(1);
  return id ? `${t} · ${id}` : t;
}

export function levelLabel(level: ApproverLevel | null | undefined): string {
  switch (level) {
    case 'auto':
      return 'Auto-approve';
    case 'self':
      return 'Self-approve';
    case 'admin':
      return 'Requires admin';
    case 'owner':
      return 'Requires owner';
    case 'deny':
      return 'Always denied';
    default:
      return '—';
  }
}

export function kindLabel(kind: ApprovalKind | string): string {
  return ({ action: 'Agent action', config_change: 'Config change', budget_raise: 'Budget override', mcp_pin: 'MCP tool re-pin' } as Record<string, string>)[kind] ?? kind;
}

export function statusMeta(status: ApprovalStatus | string): { label: string; tone: 'approval' | 'allow' | 'block' | 'log' } {
  switch (status) {
    case 'pending':
      return { label: 'Pending', tone: 'approval' };
    case 'approved':
      return { label: 'Approved', tone: 'allow' };
    case 'denied':
      return { label: 'Denied', tone: 'block' };
    case 'expired':
      return { label: 'Expired', tone: 'block' };
    case 'cancelled':
      return { label: 'Cancelled', tone: 'log' };
    default:
      return { label: String(status), tone: 'log' };
  }
}

/** lucide icon name for an approval by action type / kind. */
export function approvalIcon(kind: ApprovalKind | string, actionType: string | null | undefined): string {
  if (kind === 'budget_raise') return 'Wallet';
  if (kind === 'config_change') return actionType?.startsWith('budget.') ? 'Wallet' : 'SlidersHorizontal';
  if (kind === 'mcp_pin') return 'Plug';
  const a = actionType ?? '';
  if (a.startsWith('spend.')) return 'CreditCard';
  if (a === 'db.read') return 'Database';
  if (a.startsWith('db.')) return 'DatabaseZap';
  if (a === 'email.external' || a === 'email.internal' || a.startsWith('egress.')) return 'Send';
  if (a === 'code.deploy') return 'Rocket';
  if (a === 'code.exec') return 'SquareTerminal';
  if (a === 'package.install') return 'Package';
  if (a === 'file.sensitive') return 'FileLock';
  if (a.startsWith('org.')) return 'Users';
  if (a.startsWith('tool:')) return 'Wrench';
  return 'ShieldQuestionMark';
}

export interface ChangeKindMeta {
  icon: string;
  tone: 'loosen' | 'tighten' | 'neutral';
  loosening: boolean;
  label: string;
}

/** Metadata for a PolicyChange.kind (ChangeKind, CONTRACTS §4.2). `loosening` from the change wins. */
export function changeKindMeta(kind: string, loosening?: boolean | null): ChangeKindMeta {
  const table: Record<string, [string, ChangeKindMeta['tone'], string]> = {
    'budget.raise': ['TrendingUp', 'loosen', 'Budget raised'],
    'budget.lower': ['TrendingDown', 'tighten', 'Budget lowered'],
    'budget.add': ['Plus', 'tighten', 'Budget added'],
    'budget.remove': ['Minus', 'loosen', 'Budget removed'],
    'control.enable': ['ShieldCheck', 'tighten', 'Control enabled'],
    'control.disable': ['ShieldOff', 'loosen', 'Control disabled'],
    'control.add': ['ShieldPlus', 'tighten', 'Control added'],
    'control.remove': ['ShieldOff', 'loosen', 'Control removed'],
    'control.mode': ['ToggleLeft', 'loosen', 'Control mode'],
    'control.action.loosen': ['ShieldMinus', 'loosen', 'Action loosened'],
    'control.action.tighten': ['ShieldPlus', 'tighten', 'Action tightened'],
    'control.threshold.loosen': ['SlidersHorizontal', 'loosen', 'Threshold loosened'],
    'control.threshold.tighten': ['SlidersHorizontal', 'tighten', 'Threshold tightened'],
    'control.params': ['Settings2', 'neutral', 'Control params'],
    'model.allow': ['Cpu', 'loosen', 'Model allowed'],
    'model.disallow': ['Cpu', 'tighten', 'Model disallowed'],
    'route.change': ['Route', 'neutral', 'Route change'],
    'provider.change': ['Cloud', 'neutral', 'Provider change'],
    'approval.rule': ['Scale', 'neutral', 'Approval rule'],
    'killswitch.on': ['Power', 'tighten', 'Kill switch on'],
    'killswitch.off': ['Power', 'loosen', 'Kill switch off'],
    'mcp.server': ['Plug', 'neutral', 'MCP server'],
    'feed.override': ['Radar', 'neutral', 'Feed override'],
    'profile.change': ['Gauge', 'neutral', 'Profile change'],
    other: ['FileDiff', 'neutral', 'Other change'],
  };
  const [icon, tone0, label] = table[kind] ?? table.other;
  const tone: ChangeKindMeta['tone'] = loosening === true ? 'loosen' : loosening === false && tone0 === 'loosen' ? 'neutral' : tone0;
  return { icon, tone, loosening: tone === 'loosen', label };
}

/** Human list: ["a","b","c"] → "a, b and c". */
export function joinHuman(items: string[], max = 4): string {
  if (items.length === 0) return '';
  const shown = items.slice(0, max);
  const rest = items.length - shown.length;
  const tail = rest > 0 ? [...shown, `${rest} more`] : shown;
  if (tail.length === 1) return tail[0];
  return `${tail.slice(0, -1).join(', ')} and ${tail[tail.length - 1]}`;
}

export function initials(name: string | null | undefined): string {
  if (!name) return '?';
  const parts = name.replace(/@.*$/, '').split(/[\s._-]+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** First name for compact UI ("Emily Carter" → "Emily"). */
export function firstName(name: string | null | undefined): string {
  if (!name) return '';
  return name.split(/\s+/)[0];
}
