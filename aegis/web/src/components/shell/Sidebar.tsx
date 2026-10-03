// Sidebar: brand, org chip, nav sections from the page registry (locked pages stay visible with a lock),
// live badges (approvals · live · feed) and the health footer → /system/health. Collapses to a 64 px icon rail.
import { ChevronsUpDown, Lock, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { useApi, usePendingApprovals, useSseStatus, useStatsTick, useVersions } from '@/api/hooks';
import type { AuditVerifyResult, OrgResponse } from '@/api/types';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { fmtMs } from '@/lib/format';
import { resolveIcon } from '@/lib/icons';
import { ROLE_COLORS } from '@/lib/colors';
import type { ViewRole } from '@/lib/page';
import { isLocked, navSections, type PageEntry } from '@/lib/registry';
import { cn } from '@/lib/utils';
import { mockOrg } from '@/mocks/shell/org';
import { mockAuditVerify } from '@/mocks/shell/posture';
import { Brand } from './Brand';
import { LiveDot } from './LiveDot';
import { useShellState } from './shellStore';

function NavBadge({ kind, collapsed }: { kind: PageEntry['meta']['badge']; collapsed: boolean }) {
  const pending = usePendingApprovals();
  const sse = useSseStatus();
  const feed = useShellState((s) => s.feedBadge);
  if (kind === 'approvals' && pending > 0) {
    return (
      <span
        key={pending}
        className={cn(
          'grid h-[18px] min-w-5 place-items-center rounded-full border border-approval/30 bg-approval/12 px-1.5 text-[11px] font-medium text-approval tabular animate-in zoom-in-75 duration-300',
          collapsed && 'absolute -right-1 -top-1 h-4 min-w-4 px-1 text-[10px]',
        )}
      >
        {pending}
      </span>
    );
  }
  if (kind === 'live') {
    const on = sse === 'live' || sse === 'mock';
    return <LiveDot paused={!on} className={collapsed ? 'absolute right-1 top-1' : ''} />;
  }
  if (kind === 'feed' && feed) {
    const err = feed.kind === 'error';
    return (
      <span
        className={cn(
          'grid h-[18px] min-w-5 place-items-center rounded-full border px-1.5 text-[11px] font-medium tabular',
          err ? 'border-block/30 bg-block/10 text-block' : 'border-allow/25 bg-allow/10 text-allow',
          collapsed && 'absolute -right-1 -top-1 h-4 min-w-4 px-1 text-[10px]',
        )}
      >
        {err ? '!' : `+${feed.count}`}
      </span>
    );
  }
  return null;
}

function NavItem({ page, role, collapsed }: { page: PageEntry; role: ViewRole; collapsed: boolean }) {
  const { meta } = page;
  const Icon = resolveIcon(meta.icon);
  const locked = isLocked(meta, role);
  const link = (
    <NavLink
      to={meta.path}
      end={meta.path === '/'}
      className={({ isActive }) =>
        cn(
          'group relative flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-[450] text-text-2 transition-colors duration-150',
          'hover:bg-surface-1 hover:text-text-1',
          isActive && 'bg-surface-2 text-text-1 shadow-[inset_0_0_0_1px_var(--border-default)]',
          locked && 'text-text-3',
          collapsed && 'justify-center px-0',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive ? <span className="absolute -left-2.5 top-1.5 bottom-1.5 w-[2px] rounded-r bg-brand" /> : null}
          <Icon className={cn('size-4 shrink-0 transition-colors', isActive ? 'text-accent-fg' : 'text-text-3 group-hover:text-text-2')} />
          {!collapsed ? <span className="truncate">{meta.title}</span> : null}
          {locked ? (
            <Lock className={cn('size-3 shrink-0 text-text-4', collapsed ? 'absolute right-1 top-1' : 'ml-auto')} />
          ) : (
            <span className={cn(collapsed ? '' : 'ml-auto')}>
              <NavBadge kind={meta.badge} collapsed={collapsed} />
            </span>
          )}
        </>
      )}
    </NavLink>
  );
  if (!locked && !collapsed) return link;
  const need = ROLE_COLORS[meta.minRole ?? 'member'].label.toLowerCase();
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">
        {collapsed ? meta.title : null}
        {locked ? `${collapsed ? ' · ' : ''}Requires ${need} — switch View as` : null}
      </TooltipContent>
    </Tooltip>
  );
}

function HealthLine({ label, value, status }: { label: string; value: string; status: 'ok' | 'warn' | 'error' | 'off' }) {
  const dot = { ok: 'bg-allow', warn: 'bg-redact', error: 'bg-block', off: 'bg-text-4' }[status];
  return (
    <div className="flex items-center gap-2 text-xs text-text-2">
      <span className={cn('size-[7px] shrink-0 rounded-full', dot)} />
      <span className="text-text-3">{label}</span>
      <span className="ml-auto truncate font-mono text-[11.5px] text-text-2">{value}</span>
    </div>
  );
}

function SideFooter() {
  const tick = useStatsTick();
  const versions = useVersions();
  const sse = useSseStatus();
  const feed = useShellState((s) => s.feedBadge);
  const audit = useApi<AuditVerifyResult>('/api/audit/verify', { mock: mockAuditVerify, refreshMs: 60_000 });
  return (
    <NavLink to="/system/health" className="mt-2 flex flex-col gap-2 rounded-md border-t border-border-subtle px-1.5 pb-0.5 pt-3 transition-colors hover:bg-white/[0.015]">
      <HealthLine label="Gateway" value={tick ? `p95 ${fmtMs(tick.p95_overhead_ms)}` : sse === 'live' ? 'live' : sse === 'mock' ? 'demo' : sse} status={sse === 'live' || sse === 'mock' ? 'ok' : sse === 'offline' ? 'error' : 'warn'} />
      <HealthLine label="Policy" value={versions.policyVersion !== null ? `v${versions.policyVersion} · hot` : '—'} status={versions.policyVersion !== null ? 'ok' : 'off'} />
      <HealthLine
        label="Feed"
        value={versions.feedSerial !== null ? `#${versions.feedSerial} · ed25519` : 'seed'}
        status={feed?.kind === 'error' ? 'warn' : versions.feedSerial !== null ? 'ok' : 'off'}
      />
      <HealthLine label="Audit chain" value={audit.data ? (audit.data.ok ? 'verified' : `broken @${audit.data.broken_at_seq}`) : '…'} status={audit.data ? (audit.data.ok ? 'ok' : 'error') : 'off'} />
    </NavLink>
  );
}

export function Sidebar({ role, collapsed, onToggle }: { role: ViewRole; collapsed: boolean; onToggle: () => void }) {
  const org = useApi<OrgResponse>('/api/org', { mock: mockOrg });
  const name = org.data?.org.name ?? 'Acme Capital';
  const sections = navSections(role);
  return (
    <aside
      className={cn(
        'no-print relative flex h-full shrink-0 flex-col border-r border-border-subtle bg-sidebar px-2.5 py-3 transition-[width] duration-300 ease-out',
        collapsed ? 'w-[var(--sidebar-w-collapsed)]' : 'w-[var(--sidebar-w)]',
      )}
      aria-label="Primary"
    >
      <Brand collapsed={collapsed} />
      {!collapsed ? (
        <div className="mb-3 flex w-full items-center gap-2.5 rounded-md border border-border bg-surface-1 px-2 py-[7px] text-left">
          <span className="grid size-[22px] shrink-0 place-items-center rounded-[6px] bg-[#1B2B3F] text-[10px] font-bold tracking-[0.02em] text-[#9CC6FF]">
            {name
              .split(/\s+/)
              .map((w) => w[0])
              .join('')
              .slice(0, 2)
              .toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium leading-4 text-text-1">{name}</span>
            <span className="flex items-center gap-[5px] text-[11px] leading-[14px] text-text-3">
              <span className="size-[6px] rounded-full bg-allow" />
              Production · local gateway
            </span>
          </span>
          <ChevronsUpDown className="size-3.5 shrink-0 text-text-3" />
        </div>
      ) : null}
      <nav className="-mx-1 flex min-h-0 flex-1 flex-col gap-px overflow-y-auto overflow-x-hidden px-1">
        {sections.map(({ section, pages }) => (
          <div key={section} className="flex flex-col gap-px">
            {!collapsed ? (
              <div className="px-2.5 pb-1.5 pt-3.5 text-[10.5px] font-medium uppercase tracking-[0.08em] text-text-4">{section}</div>
            ) : (
              <div className="mx-auto my-2 h-px w-6 bg-border-subtle" />
            )}
            {pages.map((p) => (
              <NavItem key={p.meta.path} page={p} role={role} collapsed={collapsed} />
            ))}
          </div>
        ))}
      </nav>
      {!collapsed ? <SideFooter /> : null}
      <button
        type="button"
        onClick={onToggle}
        className={cn('mt-2 flex h-7 items-center gap-2 rounded-md px-2 text-xs text-text-3 hover:bg-surface-1 hover:text-text-2', collapsed && 'justify-center px-0')}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
        {!collapsed ? 'Collapse' : null}
      </button>
    </aside>
  );
}
