// Router built from auto-discovered pages (CONTRACTS §2.2). Basename = Vite base ('/ui/' -> '/ui').
// Every page renders inside <PageFrame>: role lock → LockedPage, per-page ErrorBoundary (a broken sibling
// page never kills the shell), framer page transition and document.title. Owner: dashboard-shell (B16).
import { motion } from 'framer-motion';
import { useEffect, type ComponentType } from 'react';
import { createBrowserRouter, useLocation } from 'react-router-dom';
import { useViewAs } from '@/api/hooks';
import { AppShell } from '@/components/shell/AppShell';
import { ErrorBoundary } from '@/components/shell/ErrorBoundary';
import { LockedPage } from '@/components/shell/LockedPage';
import { NotFound } from '@/components/shell/NotFound';
import { RouteError } from '@/components/shell/RouteError';
import { useMotionSafe } from '@/lib/motion';
import { getPages, isLocked, type PageEntry } from '@/lib/registry';

const basename = import.meta.env.BASE_URL.replace(/\/$/, '') || '/';

function PageFrame({ page }: { page: PageEntry }) {
  const { role } = useViewAs();
  const { pathname } = useLocation();
  const motionOk = useMotionSafe();
  const { meta } = page;
  const Component: ComponentType = page.Component;
  useEffect(() => {
    document.title = `${meta.title} · Aegis`;
  }, [meta.title]);
  useEffect(() => {
    document.getElementById('aegis-main')?.scrollTo({ top: 0 });
  }, [pathname]);
  if (isLocked(meta, role)) return <LockedPage meta={meta} />;
  return (
    <ErrorBoundary key={pathname} label={page.file.replace('../', 'web/src/')}>
      <motion.div
        key={meta.path}
        initial={motionOk ? { opacity: 0 } : false}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.12, ease: 'easeOut' }}
      >
        <Component />
      </motion.div>
    </ErrorBoundary>
  );
}

export const router = createBrowserRouter(
  [
    {
      element: <AppShell />,
      errorElement: <RouteError />,
      children: [...getPages().map((p) => ({ path: p.meta.path, element: <PageFrame page={p} /> })), { path: '*', element: <NotFound /> }],
    },
  ],
  { basename },
);
