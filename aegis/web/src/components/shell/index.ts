/**
 * Shared shell components (CONTRACTS §5.4 `@/components/shell`; props per docs/plan/15 §4.2).
 * Owner: dashboard-shell (scaffold seeded minimal working versions; names and props are binding).
 * Conventions: wrap data panels in `<Panel isMock={result.isMock}>`; use ActionBadge/ACTION_COLORS for
 * decisions; link decisions via /security/decisions/:id and approvals via /governance/approvals?id=.
 */
export { ActionBadge } from './ActionBadge';
export { AppShell } from './AppShell';
export { DestBadge } from './DestBadge';
export { EmptyState } from './EmptyState';
export { IdentityChip } from './IdentityChip';
export { JsonView } from './JsonView';
export { KpiTile, type KpiTileProps } from './KpiTile';
export { MockBadge } from './MockBadge';
export { PageHeader, type PageHeaderProps } from './PageHeader';
export { Panel, type PanelProps } from './Panel';
export { RoleBadge } from './RoleBadge';
export { RoleGate } from './RoleGate';
export { StatusDot } from './StatusDot';
export { TimeAgo } from './TimeAgo';
