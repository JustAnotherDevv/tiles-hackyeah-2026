// App frame (UIS-07): collapsible sidebar (icon rail 768–1180 px, persisted; off-canvas drawer < 768 px),
// sticky topbar, system banners, global SSE toasts, ⌘K palette + "g <key>" navigation, and the routed page
// area. Pages render inside <PageFrame> (router.tsx). Owner: dashboard-shell (B16).
import { useEffect, useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useViewAs } from '@/api/hooks';
import { GovernanceToaster } from '@/components/governance/GovernanceToaster';
import { useHotkeys } from '@/lib/hotkeys';
import { getPages } from '@/lib/registry';
import { readString, STORAGE_KEYS, writeString } from '@/lib/storage';
import { CommandPalette } from './CommandPalette';
import { ErrorBoundary } from './ErrorBoundary';
import { EventToasts } from './EventToasts';
import { Sidebar } from './Sidebar';
import { SystemBanners } from './SystemBanners';
import { Topbar } from './Topbar';
import { setShellState, useShellState } from './shellStore';

function useNarrow(px: number): boolean {
  const q = `(max-width: ${px}px)`;
  const [narrow, setNarrow] = useState(() => (typeof window !== 'undefined' ? window.matchMedia(q).matches : false));
  useEffect(() => {
    const mql = window.matchMedia(q);
    const on = () => setNarrow(mql.matches);
    mql.addEventListener('change', on);
    return () => mql.removeEventListener('change', on);
  }, [q]);
  return narrow;
}

export function AppShell() {
  const { role } = useViewAs();
  const navigate = useNavigate();
  const narrow = useNarrow(1180);
  const mobile = useNarrow(767);
  const navOpen = useShellState((s) => s.navOpen);
  const { pathname } = useLocation();
  const [pref, setPref] = useState(() => readString(STORAGE_KEYS.sidebarCollapsed) === '1');
  const collapsed = !mobile && (narrow || pref);
  useEffect(() => {
    setShellState({ navOpen: false });
  }, [pathname, mobile]);

  const sequences = useMemo(() => {
    const out: Record<string, () => void> = {};
    for (const p of getPages()) {
      const sc = p.meta.shortcut?.trim().toLowerCase();
      if (!sc || out[sc] || p.meta.path.includes(':')) continue;
      out[sc] = () => navigate(p.meta.path);
    }
    return out;
  }, [navigate]);
  useHotkeys({ onPalette: () => setShellState((s) => ({ paletteOpen: !s.paletteOpen })), sequences });

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      {mobile ? (
        navOpen ? (
          <div className="fixed inset-0 z-50 flex" role="dialog" aria-modal="true" aria-label="Navigation">
            <ErrorBoundary label="sidebar" fallback={null}>
              <Sidebar role={role} collapsed={false} mobile onToggle={() => setShellState({ navOpen: false })} />
            </ErrorBoundary>
            <button type="button" aria-label="Close navigation" className="flex-1 bg-[rgba(3,4,6,.6)]" onClick={() => setShellState({ navOpen: false })} />
          </div>
        ) : null
      ) : (
        <ErrorBoundary label="sidebar" fallback={null}>
          <Sidebar
            role={role}
            collapsed={collapsed}
            onToggle={() => {
              const next = !pref;
              setPref(next);
              writeString(STORAGE_KEYS.sidebarCollapsed, next ? '1' : null);
            }}
          />
        </ErrorBoundary>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <ErrorBoundary label="topbar" fallback={null}>
          <Topbar />
        </ErrorBoundary>
        <ErrorBoundary label="banners" fallback={null}>
          <SystemBanners />
        </ErrorBoundary>
        <main className="aegis-canvas min-h-0 flex-1 overflow-y-auto overflow-x-hidden" id="aegis-main">
          <div className="mx-auto w-full max-w-[var(--content-max)] px-[var(--gutter)] pb-16 pt-6 max-md:pt-4">
            <Outlet />
          </div>
        </main>
      </div>
      <ErrorBoundary label="toasts" fallback={null}>
        <EventToasts />
        <GovernanceToaster />
      </ErrorBoundary>
      <ErrorBoundary label="palette" fallback={null}>
        <CommandPalette />
      </ErrorBoundary>
    </div>
  );
}
