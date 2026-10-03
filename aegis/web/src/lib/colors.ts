// Semantic colours (CONTRACTS §3.4). Decision: allow emerald · log slate · redact amber ·
// require_approval violet · block rose. Roles: owner fuchsia · admin sky · member slate · agent teal.
// Owner: dashboard-shell (scaffold seed).
import type { Action, ApproverLevel, DestClass, Role } from '@/api/types';

export interface ActionColor {
  label: string;
  icon: string; // lucide name
  fg: string; // text/badge colour
  chart: string; // chart mark colour
  bg: string;
  border: string;
  className: string; // tailwind classes for badges
}

export const ACTION_COLORS: Record<Action, ActionColor> = {
  allow: { label: 'Allow', icon: 'ShieldCheck', fg: '#34D399', chart: '#059669', bg: 'rgba(16,185,129,.10)', border: 'rgba(16,185,129,.28)', className: 'text-allow bg-allow/10 border-allow/30' },
  log: { label: 'Log', icon: 'ScrollText', fg: '#94A3B8', chart: '#64748B', bg: 'rgba(148,163,184,.12)', border: 'rgba(148,163,184,.28)', className: 'text-log bg-log/10 border-log/30' },
  redact: { label: 'Redact', icon: 'EyeOff', fg: '#FBBF24', chart: '#D97706', bg: 'rgba(245,158,11,.10)', border: 'rgba(245,158,11,.28)', className: 'text-redact bg-redact/10 border-redact/30' },
  require_approval: { label: 'Approval', icon: 'UserCheck', fg: '#A78BFA', chart: '#8B5CF6', bg: 'rgba(139,92,246,.10)', border: 'rgba(139,92,246,.28)', className: 'text-approval bg-approval/10 border-approval/30' },
  block: { label: 'Block', icon: 'Ban', fg: '#FB7185', chart: '#E11D48', bg: 'rgba(244,63,94,.10)', border: 'rgba(244,63,94,.30)', className: 'text-block bg-block/10 border-block/30' },
};

export const ROLE_COLORS: Record<Role | ApproverLevel, { label: string; fg: string; className: string }> = {
  owner: { label: 'Owner', fg: '#E879F9', className: 'text-role-owner bg-role-owner/10 border-role-owner/30' },
  admin: { label: 'Admin', fg: '#38BDF8', className: 'text-role-admin bg-role-admin/10 border-role-admin/30' },
  member: { label: 'Member', fg: '#94A3B8', className: 'text-role-member bg-role-member/10 border-role-member/30' },
  agent: { label: 'Agent', fg: '#2DD4BF', className: 'text-role-agent bg-role-agent/10 border-role-agent/30' },
  self: { label: 'Self-approve', fg: '#34D399', className: 'text-allow bg-allow/10 border-allow/30' },
  auto: { label: 'Auto', fg: '#94A3B8', className: 'text-log bg-log/10 border-log/30' },
  deny: { label: 'Denied', fg: '#FB7185', className: 'text-block bg-block/10 border-block/30' },
};

export const DEST_COLORS: Record<DestClass, { label: string; icon: string; fg: string }> = {
  local: { label: 'Local', icon: 'Laptop', fg: '#34D399' },
  remote: { label: 'Remote', icon: 'Cloud', fg: '#38BDF8' },
  third_party: { label: 'Third party', icon: 'Globe', fg: '#FBBF24' },
};

/** Categorical series palette (never reuse decision colours for series). */
export const CHART_PALETTE = ['#2563EB', '#DB2777', '#0891B2', '#EA580C', '#D55181'] as const;
