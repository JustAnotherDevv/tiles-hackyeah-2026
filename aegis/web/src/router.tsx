// Router built from auto-discovered pages (CONTRACTS §2.2). Basename = Vite base ('/ui/' -> '/ui').
// Owner: dashboard-shell (scaffold seed).
import { createBrowserRouter } from 'react-router-dom';
import { AppShell } from '@/components/shell/AppShell';
import { EmptyState } from '@/components/shell/EmptyState';
import { pages } from '@/lib/registry';

const basename = import.meta.env.BASE_URL.replace(/\/$/, '') || '/';

function NotFound() {
  return <EmptyState icon="MapPinOff" title="Page not found" hint="Pick a page from the sidebar." />;
}

export const router = createBrowserRouter(
  [
    {
      element: <AppShell />,
      errorElement: <EmptyState icon="TriangleAlert" title="Something went wrong" hint="See the browser console." />,
      children: [
        ...pages.map(({ meta, Component }) => ({ path: meta.path, element: <Component /> })),
        { path: '*', element: <NotFound /> },
      ],
    },
  ],
  { basename },
);
