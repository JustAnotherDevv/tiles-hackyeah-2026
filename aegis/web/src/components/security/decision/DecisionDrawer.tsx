// Decision drawer (~640 px Sheet) + full-page container + DecisionLink (exported for other dashboards).
import { Download, ExternalLink, FlaskConical, SearchX } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { DecisionDetail, DecisionSummary } from '@/api/types';
import { ActionBadge, EmptyState, MockBadge, TimeAgo } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { CopyButton, SurfaceTag } from '../common/atoms';
import { useControlsCatalog, useCurrentVersions, useDecisionDetail } from '../hooks';
import { DecisionTrace, type TraceTab } from './DecisionTrace';

function downloadRecord(detail: DecisionDetail): void {
  const { wire: _w, ...rest } = detail;
  const blob = new Blob([JSON.stringify(rest, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${detail.id}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function defaultTab(d: Pick<DecisionSummary, 'redaction_count'> | null | undefined): TraceTab {
  return d && d.redaction_count > 0 ? 'wire' : 'trace';
}

/** Header line: badge + surface + tool + time. */
export function DecisionHeader({ d, isMock, right }: { d: DecisionSummary; isMock?: boolean; right?: ReactNode }) {
  const title = d.tool_name ?? d.model ?? d.surface;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <ActionBadge action={d.action} size="lg" />
        <SurfaceTag surface={d.surface} direction={d.direction} />
        {d.tool_name ? <span className="rounded-[5px] border border-border bg-surface-2 px-1.5 font-mono text-2xs text-text-2">{d.tool_name}</span> : null}
        <span className="text-xs text-text-3">
          <TimeAgo ts={d.ts} />
        </span>
        {d.dry_run ? <span className="rounded-full border border-border px-1.5 text-2xs text-text-3">dry run</span> : null}
        {isMock ? <MockBadge /> : null}
        {right ? <div className="ml-auto flex items-center gap-1">{right}</div> : null}
      </div>
      <div className="line-clamp-2 break-all font-mono text-[13px] leading-5 text-text-1" title={d.preview}>
        {d.preview || title}
      </div>
    </div>
  );
}

export function DecisionFooter({ detail, onOpenPage }: { detail: DecisionDetail; onOpenPage?: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-1 font-mono text-2xs text-text-3">
        {detail.id}
        <CopyButton value={detail.id} label="decision id" />
      </span>
      <span className="inline-flex items-center gap-1 font-mono text-2xs text-text-3">
        req
        <CopyButton value={detail.request_id} label="request id" />
      </span>
      <div className="ml-auto flex flex-wrap items-center gap-1.5">
        <Button asChild variant="secondary" size="sm">
          <Link to={`/security/playground?from=${encodeURIComponent(detail.id)}`}>
            <FlaskConical /> Replay in playground
          </Link>
        </Button>
        <Button variant="ghost" size="sm" onClick={() => downloadRecord(detail)}>
          <Download /> Record
        </Button>
        {onOpenPage ? (
          <Button asChild variant="ghost" size="sm" onClick={onOpenPage}>
            <Link to={`/security/decisions/${encodeURIComponent(detail.id)}`}>
              <ExternalLink /> Full page
            </Link>
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function TraceSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-16 w-full" />
      <div className="grid grid-cols-4 gap-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-12" />
        ))}
      </div>
      <Skeleton className="h-8 w-64" />
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}

/** Fetches detail + catalog + versions and renders DecisionTrace (drawer and full page share this). */
export function DecisionView({
  decisionId,
  hint,
  layout = 'drawer',
  onOpenPage,
}: {
  decisionId: string;
  hint?: DecisionSummary | null;
  layout?: 'drawer' | 'page';
  onOpenPage?: () => void;
}) {
  const res = useDecisionDetail(decisionId, hint);
  const { catalog } = useControlsCatalog();
  const current = useCurrentVersions();
  const detail = res.data && res.data.id === decisionId ? res.data : undefined;
  const [tab, setTab] = useState<TraceTab>(() => defaultTab(hint));
  const [tabTouched, setTabTouched] = useState(false);
  useEffect(() => {
    setTabTouched(false);
    setTab(defaultTab(hint));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [decisionId]);
  useEffect(() => {
    if (detail && !tabTouched) setTab(defaultTab(detail));
  }, [detail, tabTouched]);

  const summary: DecisionSummary | null = detail ?? hint ?? null;
  if (!detail && !res.loading && res.error) {
    return (
      <div className={cn(layout === 'drawer' && 'px-5 py-4')}>
        {summary ? <DecisionHeader d={summary} /> : null}
        <EmptyState icon={SearchX} title="Decision not found or not yet indexed" hint={res.error.message} />
      </div>
    );
  }
  return (
    <div className={cn('flex min-h-0 flex-col', layout === 'drawer' ? 'h-full' : '')}>
      <div className={cn(layout === 'drawer' ? 'border-b border-border px-5 pb-3 pt-4 pr-12' : 'mb-4')}>
        {summary ? <DecisionHeader d={summary} isMock={res.isMock} /> : <Skeleton className="h-12 w-full" />}
      </div>
      <div className={cn(layout === 'drawer' ? 'min-h-0 flex-1 overflow-y-auto px-5 py-4' : '')}>
        {detail ? (
          <DecisionTrace
            detail={detail}
            catalog={catalog}
            current={current}
            tab={tab}
            onTabChange={(t) => {
              setTabTouched(true);
              setTab(t);
            }}
          />
        ) : (
          <TraceSkeleton />
        )}
      </div>
      {detail ? (
        <div className={cn(layout === 'drawer' ? 'border-t border-border bg-surface-1/60 px-5 py-3' : 'mt-6 border-t border-border pt-3')}>
          <DecisionFooter detail={detail} onOpenPage={layout === 'drawer' ? onOpenPage : undefined} />
        </div>
      ) : null}
    </div>
  );
}

export function DecisionDrawer({
  decisionId,
  open,
  onOpenChange,
  hint,
}: {
  decisionId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  hint?: DecisionSummary | null;
}) {
  return (
    <Sheet open={open && Boolean(decisionId)} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-[680px] data-[side=right]:sm:max-w-[680px]">
        <SheetTitle className="sr-only">Decision trace</SheetTitle>
        <SheetDescription className="sr-only">Why Aegis decided what it did for this request</SheetDescription>
        {decisionId ? <DecisionView decisionId={decisionId} hint={hint} layout="drawer" onOpenPage={() => onOpenChange(false)} /> : null}
      </SheetContent>
    </Sheet>
  );
}

/** Link that opens a decision in its own drawer (usable from any dashboard). */
export function DecisionLink({ id, children, className }: { id: string; children?: ReactNode; className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={cn('font-mono text-xs text-accent-fg hover:underline', className)}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
      >
        {children ?? id}
      </button>
      <DecisionDrawer decisionId={id} open={open} onOpenChange={setOpen} />
    </>
  );
}
