// Semantic colours (CONTRACTS §3.4) — the single source for every dashboard page.
// Decision: allow emerald · log slate · redact amber · require_approval violet · block rose.
// Roles: owner fuchsia · admin sky · member slate · agent teal.
// `fg` is for text/badges on dark surfaces, `chart` for marks (never swap them). Badges always carry
// label + icon (never colour alone) — adjacent CVD distance is at the floor band.
// Owner: dashboard-shell (B16).
import type { Action, ApproverLevel, BudgetState, DestClass, Role, Severity } from '@/api/types';

export interface ActionColor {
  label: string;
  icon: string; // lucide name
  fg: string; // text/badge colour
  chart: string; // chart mark colour
  bg: string;
  border: string;
  className: string; // tailwind classes for badges (text + subtle bg + border)
}

export const ACTION_COLORS: Record<Action, ActionColor> = {
  allow: { label: 'Allow', icon: 'ShieldCheck', fg: '#3CCB7F', chart: '#1E9F68', bg: 'rgba(60,203,127,.10)', border: 'rgba(60,203,127,.26)', className: 'text-allow bg-allow/10 border-allow/25' },
  log: { label: 'Log', icon: 'ScrollText', fg: '#8C93A0', chart: '#5B6475', bg: 'rgba(140,147,160,.10)', border: 'rgba(140,147,160,.26)', className: 'text-log bg-log/10 border-log/25' },
  redact: { label: 'Redact', icon: 'EyeOff', fg: '#E8A93A', chart: '#C98500', bg: 'rgba(232,169,58,.10)', border: 'rgba(232,169,58,.28)', className: 'text-redact bg-redact/10 border-redact/30' },
  require_approval: { label: 'Approval', icon: 'UserCheck', fg: '#A78BFA', chart: '#8B5CF6', bg: 'rgba(167,139,250,.10)', border: 'rgba(167,139,250,.30)', className: 'text-approval bg-approval/10 border-approval/30' },
  block: { label: 'Block', icon: 'Ban', fg: '#F2556F', chart: '#E5446D', bg: 'rgba(242,85,111,.10)', border: 'rgba(242,85,111,.30)', className: 'text-block bg-block/10 border-block/30' },
};

/** Stack/legend order for decision charts (interventions last so they sit on top). */
export const ACTION_CHART_ORDER: Action[] = ['allow', 'log', 'redact', 'require_approval', 'block'];

export const ROLE_COLORS: Record<Role | ApproverLevel | 'viewer', { label: string; fg: string; icon: string; className: string }> = {
  owner: { label: 'Owner', fg: '#E879F9', icon: 'Crown', className: 'text-role-owner bg-role-owner/10 border-role-owner/30' },
  admin: { label: 'Admin', fg: '#38BDF8', icon: 'ShieldHalf', className: 'text-role-admin bg-role-admin/10 border-role-admin/30' },
  member: { label: 'Member', fg: '#A2A8B3', icon: 'User', className: 'text-role-member bg-surface-2 border-border-strong' },
  viewer: { label: 'Viewer (read-only)', fg: '#8C93A0', icon: 'Eye', className: 'text-text-3 bg-surface-2 border-border-strong' },
  agent: { label: 'Agent', fg: '#2DD4BF', icon: 'Bot', className: 'text-role-agent bg-role-agent/10 border-role-agent/25' },
  self: { label: 'Self-approve', fg: '#3CCB7F', icon: 'UserCheck', className: 'text-allow bg-allow/10 border-allow/25' },
  auto: { label: 'Auto', fg: '#8C93A0', icon: 'Zap', className: 'text-log bg-log/10 border-log/25' },
  deny: { label: 'Denied', fg: '#F2556F', icon: 'Ban', className: 'text-block bg-block/10 border-block/30' },
};

export const DEST_COLORS: Record<DestClass, { label: string; icon: string; fg: string }> = {
  local: { label: 'Local', icon: 'Laptop', fg: '#3CCB7F' },
  remote: { label: 'Remote', icon: 'Cloud', fg: '#38BDF8' },
  third_party: { label: 'Third party', icon: 'Globe', fg: '#E8A93A' },
};

export const SEVERITY_COLORS: Record<Severity, { label: string; fg: string; className: string }> = {
  info: { label: 'Info', fg: '#8C93A0', className: 'text-log bg-log/10 border-log/25' },
  low: { label: 'Low', fg: '#38BDF8', className: 'text-role-admin bg-role-admin/10 border-role-admin/25' },
  medium: { label: 'Medium', fg: '#E8A93A', className: 'text-redact bg-redact/10 border-redact/30' },
  high: { label: 'High', fg: '#F08A4B', className: 'text-downgrade bg-downgrade/10 border-downgrade/30' },
  critical: { label: 'Critical', fg: '#F2556F', className: 'text-block bg-block/10 border-block/30' },
};

/** Budget meter states (DESIGN_TOKENS §2.5): fill colour, label and badge classes. */
export const BUDGET_STATE_COLORS: Record<BudgetState, { label: string; fill: string; fg: string; className: string }> = {
  ok: { label: 'OK', fill: '#4A7FE0', fg: '#A2A8B3', className: 'text-text-2 bg-surface-2 border-border-strong' },
  soft: { label: 'Downgrading', fill: '#C98500', fg: '#F08A4B', className: 'text-downgrade bg-downgrade/10 border-downgrade/30' },
  hard: { label: 'Blocking', fill: '#E5446D', fg: '#F2556F', className: 'text-block bg-block/10 border-block/30' },
  killed: { label: 'Killed', fill: '#E5446D', fg: '#F2556F', className: 'text-block bg-block/15 border-block/40' },
};

/** Status tones (always pair with an icon + label). */
export const STATUS_TONE = {
  good: { fg: '#3CCB7F', className: 'text-allow', dot: 'bg-allow' },
  warn: { fg: '#E8A93A', className: 'text-redact', dot: 'bg-redact' },
  bad: { fg: '#F2556F', className: 'text-block', dot: 'bg-block' },
  off: { fg: '#4B5160', className: 'text-text-4', dot: 'bg-text-4' },
  neutral: { fg: '#A2A8B3', className: 'text-text-2', dot: 'bg-text-3' },
} as const;
export type StatusTone = keyof typeof STATUS_TONE;

/** Categorical series palette (never reuse decision colours for series). Fixed order, never cycled by rank. */
export const CHART_PALETTE = ['#3987E5', '#DB2777', '#0891B2', '#EA580C', '#D55181'] as const;

/** Team colours by fixed team order (seed Team.color is ignored in charts: it collides with decision hues). */
export const TEAM_PALETTE: Record<string, string> = {
  trading: '#3987E5',
  research: '#DB2777',
  platform: '#0891B2',
};

export function teamColor(teamId: string | null | undefined): string {
  if (!teamId) return '#7A808C';
  const id = teamId.replace(/^team:/, '');
  if (TEAM_PALETTE[id]) return TEAM_PALETTE[id];
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return CHART_PALETTE[h % CHART_PALETTE.length];
}

/** Deterministic avatar tint for member initials (prototype avColor). */
export function avatarColor(seed: string): { bg: string; fg: string } {
  const tints = [
    { bg: '#1B2B3F', fg: '#9CC6FF' },
    { bg: '#2A1F3D', fg: '#C9B5FF' },
    { bg: '#1D3326', fg: '#8FE0B0' },
    { bg: '#3A2A18', fg: '#F5C98A' },
    { bg: '#3A1D2A', fg: '#F7A8C4' },
    { bg: '#173238', fg: '#86E1EC' },
  ];
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 33 + seed.charCodeAt(i)) >>> 0;
  return tints[h % tints.length];
}
