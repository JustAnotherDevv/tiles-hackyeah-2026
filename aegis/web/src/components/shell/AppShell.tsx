// App frame (UIS-07): collapsible sidebar (auto icon rail ≤ 1180 px, persisted), sticky glass topbar,
// system banners, global SSE toasts, ⌘K palette + "g <key>" navigation, and the routed page area on the
// faint grid/glow canvas. Pages render inside <PageFrame> (router.tsx). Owner: dashboard-shell (B16).
import { useEffect, useMemo, useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { useViewAs } from '@/api/hooks';
import { GovernanceToaster } from '@/components/governance/GovernanceToaster';
import { useHotkeys } from '@/lib/hotkeys';
import { getPages } from '@/lib/registry';
import { readString, STORAGE_KEYS, writeString } from '@/lib/storage';
import { CommandPalette } from './CommandPalette';
import { EventToasts } from './EventToasts';
import { Sidebar } from './Sidebar';
import { SystemBanners } from './SystemBanners';
import { Topbar } from './Topbar';
import { setShellState } from './shellStore';

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
  const [pref, setPref] = useState(() => readString(STORAGE_KEYS.sidebarCollapsed) === '1');
  const collapsed = narrow || pref;

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
      <Sidebar
        role={role}
        collapsed={collapsed}
        onToggle={() => {
          const next = !pref;
          setPref(next);
          writeString(STORAGE_KEYS.sidebarCollapsed, next ? '1' : null);
        }}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <SystemBanners />
        <main className="aegis-canvas min-h-0 flex-1 overflow-y-auto overflow-x-hidden" id="aegis-main">
          <div className="mx-auto w-full max-w-[var(--content-max)] px-7 pb-16 pt-6 max-[1280px]:px-5">
            <Outlet />
          </div>
        </main>
      </div>
      <EventToasts />
      <GovernanceToaster />
      <CommandPalette />
    </div>
  );
}
