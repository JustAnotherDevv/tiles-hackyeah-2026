/**
 * Shared shell components (CONTRACTS §5.4 `@/components/shell`; props per docs/plan/15 §4.2 — binding).
 * Owner: dashboard-shell (B16).
 *
 * Conventions for sibling dashboards:
 * - wrap every data panel in `<Panel isMock={result.isMock}>` (shows the "demo data" badge);
 * - use ActionBadge / ACTION_COLORS for any decision, RoleBadge / ROLE_COLORS for roles, teamColor() for teams;
 * - never toast SSE events the shell already toasts (policy.*, feed.*, approval.created/updated,
 *   budget.threshold, killswitch, system) — toast only the results of your own HTTP actions;
 * - keep mock factories in web/src/mocks/<area>/; link decisions via /security/decisions/:id and
 *   approvals via /governance/approvals?id=.
 */
export { ActionBadge } from './ActionBadge';
export { AnimatedNumber, type AnimatedNumberProps } from './AnimatedNumber';
export { AppShell } from './AppShell';
export { DestBadge } from './DestBadge';
export { EmptyState } from './EmptyState';
export { ErrorBoundary } from './ErrorBoundary';
export { AgentAvatar, Avatar, IdentityChip } from './IdentityChip';
export { JsonView } from './JsonView';
export { Kbd } from './Kbd';
export { KpiTile, type KpiTileProps } from './KpiTile';
export { LiveDot } from './LiveDot';
export { MockBadge } from './MockBadge';
export { PageHeader, type PageHeaderProps } from './PageHeader';
export { Panel, type PanelProps } from './Panel';
export { RoleBadge } from './RoleBadge';
export { RoleGate } from './RoleGate';
export { Segmented, type SegmentedOption } from './Segmented';
export { StatusDot } from './StatusDot';
export { TimeAgo, useNow } from './TimeAgo';
export { UsageBar, type UsageBarProps } from './UsageBar';
export { LockedPage } from './LockedPage';
export { NotFound } from './NotFound';
export { RouteError } from './RouteError';
export { SystemBanners } from './SystemBanners';
export { BrandMark, Brand } from './Brand';
