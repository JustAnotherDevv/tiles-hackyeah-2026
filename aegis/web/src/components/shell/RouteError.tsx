// Router-level errorElement (loader/route errors outside the per-page ErrorBoundary).
import { isRouteErrorResponse, useRouteError } from 'react-router-dom';
import { BrandMark } from './Brand';

export function RouteError() {
  const err = useRouteError();
  const msg = isRouteErrorResponse(err) ? `${err.status} ${err.statusText}` : err instanceof Error ? err.message : String(err);
  return (
    <div className="grid min-h-screen place-items-center bg-background p-6">
      <div className="flex max-w-lg flex-col items-center gap-3 text-center">
        <BrandMark size={40} />
        <div className="text-lg font-semibold">The dashboard hit an unexpected error</div>
        <pre className="max-h-40 w-full overflow-auto rounded-md border border-border bg-surface-1 p-3 text-left font-mono text-xs text-text-3">{msg}</pre>
        <button type="button" onClick={() => window.location.assign(import.meta.env.BASE_URL)} className="h-8 rounded-md border border-border bg-surface-2 px-3 text-sm hover:bg-surface-3">
          Reload dashboard
        </button>
      </div>
    </div>
  );
}
