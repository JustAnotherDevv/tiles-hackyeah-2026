// Placeholder layout shell: sidebar from the page registry + topbar with "view as" switcher.
// Owner: dashboard-shell (scaffold seed — replace with the real shell from the design prototype).
import { Lock } from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';
import { useLiveDecisions, usePendingApprovals, useSseStatus, useViewAs } from '@/api/hooks';
import { resolveIcon } from '@/lib/icons';
import { isLocked, navSections } from '@/lib/registry';
import { cn } from '@/lib/utils';
import { RoleBadge } from './RoleBadge';
import { StatusDot } from './StatusDot';

function Badge({ kind }: { kind: 'approvals' | 'live' | 'feed' | null | undefined }) {
  const pending = usePendingApprovals();
  const live = useLiveDecisions(1);
  if (kind === 'approvals' && pending > 0) return <span className="ml-auto rounded-full bg-approval/15 px-1.5 text-2xs text-approval">{pending}</span>;
  if (kind === 'live') return <span className="ml-auto">{live.connected ? <StatusDot status="ok" pulse /> : null}</span>;
  return null;
}

export function AppShell() {
  const { member, role, members, setViewAs } = useViewAs();
  const sse = useSseStatus();
  return (
    <div className="flex min-h-screen bg-background">
      <aside className="sticky top-0 flex h-screen w-[var(--sidebar-w)] shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
        <div className="flex h-[var(--topbar-h)] items-center gap-2 px-4">
          <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" className="size-7" />
          <span className="text-md font-semibold tracking-tight">Aegis</span>
        </div>
        <nav className="flex-1 space-y-4 overflow-y-auto px-2 py-2">
          {navSections(role).map(({ section, pages }) => (
            <div key={section}>
              <div className="px-2 pb-1 text-2xs font-medium uppercase tracking-wider text-text-3">{section}</div>
              {pages.map(({ meta }) => {
                const Icon = resolveIcon(meta.icon);
                const locked = isLocked(meta, role);
                return (
                  <NavLink
                    key={meta.path}
                    to={meta.path}
                    end={meta.path === '/'}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-sidebar-foreground hover:bg-sidebar-accent hover:text-text-1',
                        isActive && 'bg-sidebar-accent text-text-1',
                        locked && 'opacity-60',
                      )
                    }
                  >
                    <Icon className="size-4" />
                    <span className="truncate">{meta.title}</span>
                    {locked ? <Lock className="ml-auto size-3 text-text-4" /> : <Badge kind={meta.badge} />}
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="border-t border-sidebar-border px-4 py-3 text-xs text-text-3">
          <StatusDot status={sse === 'live' ? 'ok' : sse === 'connecting' ? 'warn' : sse === 'mock' ? 'warn' : 'off'} label={`events: ${sse}`} />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-[var(--topbar-h)] items-center justify-end gap-3 border-b border-border bg-background/85 px-6 backdrop-blur">
          <span className="text-xs text-text-3">View as</span>
          <select
            className="h-8 rounded-md border border-border bg-surface-2 px-2 text-sm"
            value={member?.id ?? ''}
            onChange={(e) => setViewAs(e.target.value)}
          >
            {members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} · {m.role}
              </option>
            ))}
          </select>
          <RoleBadge role={role} />
        </header>
        <main className="mx-auto w-full max-w-[var(--content-max)] flex-1 px-7 pb-16 pt-6 animate-page-in">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
