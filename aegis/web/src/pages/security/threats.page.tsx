// /security/threats — signed threat-intel feed: serial, verified key, expiry, update pipeline, signatures, hits.
// Reacts live to feed.updated (serial change + new-row highlight) and feed.rejected (red banner, failed verify step).
// Availability problems (feed server unreachable, bundle expired, updates disabled) get their own calmer banner and
// are never reported as a rejected bundle.
import { CloudOff, ExternalLink, RefreshCw } from '@/components/icons';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { api, isApiRequestError } from '@/api/client';
import { useApi, useEvents, useLiveDecisions } from '@/api/hooks';
import type { DecisionSummary, FeedSignatureView, FeedStatus, Page } from '@/api/types';
import { EmptyState, PageHeader, Panel, RoleGate } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { LockedAction } from '@/components/security/common';
import { DecisionDrawer } from '@/components/security/decision';
import { deriveFeedSteps } from '@/components/security/lib/feedSteps';
import { FeedBanner, FeedStatusStrip, FeedTimeline, FeedUpdateSteps, issueKind, SignatureHits, SignatureTable, type RejectInfo, type TimelineEvent } from '@/components/security/threats';
import { mockFeedSignatures, mockFeedStatus, mockSignatureHits } from '@/mocks/security';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/security/threats',
  title: 'Threat feed',
  icon: 'Radar',
  section: 'Security',
  order: 30,
  badge: 'feed',
  shortcut: 'g t',
  description: 'Signed threat-intel signatures, hot-swapped without a restart',
};

function consoleUrl(url: string | null | undefined): string {
  try {
    return url ? `${new URL(url).origin}/` : 'http://127.0.0.1:8790/';
  } catch {
    return 'http://127.0.0.1:8790/';
  }
}

export default function ThreatsPage() {
  const [params] = useSearchParams();
  const highlight = params.get('sig');
  const status = useApi<FeedStatus>('/api/feed/status', { mock: mockFeedStatus, refreshOn: ['feed.updated', 'feed.rejected'], refreshMs: 10_000 });
  const sigs = useApi<{ items: FeedSignatureView[] }>('/api/feed/signatures', { mock: () => mockFeedSignatures(), refreshOn: ['feed.updated'] });
  const hitsRes = useApi<Page<DecisionSummary>>('/api/decisions?control_id=SIG-01&limit=20', { mock: mockSignatureHits, refreshOn: ['feed.updated'], refreshMs: 15_000 });
  const live = useLiveDecisions(300);
  const [reject, setReject] = useState<RejectInfo | null>(null);
  const [dismissedAt, setDismissedAt] = useState<string | null>(null);
  const [prevIds, setPrevIds] = useState<Set<string> | null>(null);
  const [sessionEvents, setSessionEvents] = useState<TimelineEvent[]>([]);
  const [checking, setChecking] = useState(false);
  const [openHit, setOpenHit] = useState<DecisionSummary | null>(null);

  useEvents(['feed.updated', 'feed.rejected'], (name, data) => {
    if (name === 'feed.updated') {
      const d = data as { serial: number | null; version: string | null; added: number; removed: number; modified: number };
      setPrevIds(new Set((sigs.data?.items ?? []).map((s) => s.id)));
      setReject(null);
      setSessionEvents((ev) => [{ key: `u${Date.now()}`, at: Date.now(), kind: 'applied' as const, title: `#${d.serial} verified & active`, detail: `${d.version ?? ''} · +${d.added} −${d.removed} ~${d.modified}` }, ...ev].slice(0, 20));
    } else {
      const d = data as { reason: string; serial_attempted: number | null; kept_serial: number | null };
      const unreachable = /^unreachable/i.test(d.reason ?? '');
      setReject({ ...d, at: Date.now(), kind: unreachable ? 'unreachable' : 'rejected' });
      setDismissedAt(null);
      if (!unreachable)
        setSessionEvents((ev) => [{ key: `r${Date.now()}`, at: Date.now(), kind: 'rejected' as const, title: `${d.serial_attempted !== null ? `#${d.serial_attempted}` : 'Bundle'} rejected`, detail: d.reason }, ...ev].slice(0, 20));
    }
  });

  const s = status.data;
  // Feed health from /api/feed/status. Only status === 'rejected' means a bundle failed verification; an
  // `unreachable: …` error (status unreachable, or a failed poll while still ok) is an availability problem.
  const statusReject: RejectInfo | null = (() => {
    if (!s) return null;
    const err = s.last_error ?? '';
    const kind: RejectInfo['kind'] | null =
      s.status === 'unreachable' || /^unreachable/i.test(err)
        ? 'unreachable'
        : s.status === 'rejected'
          ? 'rejected'
          : s.status === 'stale'
            ? 'stale'
            : s.status === 'disabled'
              ? 'disabled'
              : null;
    if (!kind || dismissedAt === `${kind}:${err}`) return null;
    return { reason: err, serial_attempted: null, kept_serial: s.serial, at: 0, kind };
  })();
  const banner = reject ?? statusReject;
  const issue = banner ? issueKind(banner) : null;
  const steps = useMemo(() => deriveFeedSteps(s ?? null, reject?.reason ?? null), [s, reject]);
  const newIds = useMemo(() => {
    if (!prevIds) return new Set<string>();
    return new Set((sigs.data?.items ?? []).filter((x) => !prevIds.has(x.id)).map((x) => x.id));
  }, [prevIds, sigs.data]);

  useEffect(() => {
    if (!highlight || !sigs.data) return;
    const t = setTimeout(() => document.getElementById(`sig-${highlight}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 200);
    return () => clearTimeout(t);
  }, [highlight, sigs.data]);

  const hits = useMemo(() => {
    const seen = new Set<string>();
    const out: DecisionSummary[] = [];
    const isSigHit = (d: DecisionSummary) => d.action !== 'allow' && ((d.controls ?? []).some((c) => c.control_id.startsWith('SIG-') && c.action !== 'allow') || Boolean(d.control_id?.startsWith('SIG-')));
    const liveSig = live.items.filter(isSigHit);
    for (const d of [...liveSig, ...(hitsRes.data?.items ?? []).filter((x) => x.action !== 'allow')]) {
      if (seen.has(d.id)) continue;
      seen.add(d.id);
      out.push(d);
    }
    return out.sort((a, b) => (a.ts < b.ts ? 1 : -1)).slice(0, 20);
  }, [live.items, hitsRes.data]);

  const timeline: TimelineEvent[] = useMemo(
    () => [
      ...sessionEvents,
      ...[...(s?.history ?? [])]
        .sort((a, b) => (a.applied_at < b.applied_at ? 1 : -1))
        .map((h) => ({ key: `h${h.serial}`, at: h.applied_at, kind: 'applied' as const, title: `#${h.serial} applied`, detail: `${h.version} · +${h.added} −${h.removed} ~${h.modified}` })),
    ],
    [sessionEvents, s],
  );

  const checkNow = async () => {
    setChecking(true);
    try {
      const r = await api.post<FeedStatus>('/api/feed/refresh', {});
      const st = r.data.status;
      if (st === 'ok' || st === 'seed') toast.success(`Feed checked · active serial #${r.data.serial ?? '—'}`);
      else if (st === 'unreachable' || /^unreachable/i.test(r.data.last_error ?? '')) toast.warning('Feed server unreachable', { description: `Still enforcing #${r.data.serial ?? '—'}` });
      else toast.warning(`Feed checked · status ${st}`, { description: r.data.last_error ?? undefined });
      void status.refresh();
      void sigs.refresh();
    } catch (e) {
      toast.error(isApiRequestError(e) ? e.message : 'Feed refresh failed');
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Threat feed"
        icon="Radar"
        subtitle="Ed25519-signed signature bundles, verified and self-tested before they replace the active set. No restart required."
        actions={
          <div className="flex items-center gap-2">
            <Button asChild variant="ghost" size="sm">
              <a href={consoleUrl(s?.url)} target="_blank" rel="noreferrer">
                <ExternalLink /> Publisher console
              </a>
            </Button>
            <RoleGate min="admin" fallback={<LockedAction label="Check now" />}>
              <Button variant="secondary" size="sm" onClick={() => void checkNow()} disabled={checking}>
                <RefreshCw className={checking ? 'animate-spin' : undefined} /> Check now
              </Button>
            </RoleGate>
          </div>
        }
      />
      {banner ? (
        <FeedBanner
          info={banner}
          onDismiss={() => {
            setReject(null);
            setDismissedAt(statusReject ? `${statusReject.kind}:${statusReject.reason}` : null);
          }}
        />
      ) : null}
      {s ? (
        <FeedStatusStrip status={s} issue={issue === 'disabled' ? null : issue} />
      ) : status.error ? (
        <EmptyState icon={CloudOff} title="Feed status unavailable" hint={status.error.message} className="rounded-lg border border-border bg-card py-6" />
      ) : (
        <Skeleton className="h-[92px] w-full" />
      )}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel title="Signatures" description={sigs.data ? `${sigs.data.items.length} in the active bundle` : 'Loading active bundle'} flush isMock={sigs.isMock}>
          {sigs.data ? (
            <SignatureTable items={sigs.data.items} newIds={newIds} highlight={highlight} />
          ) : sigs.error ? (
            <EmptyState icon={CloudOff} title="Signatures unavailable" hint={sigs.error.message} />
          ) : (
            <Skeleton className="m-4 h-64" />
          )}
        </Panel>
        <div className="min-w-0 space-y-4">
          <Panel
            title="Update pipeline"
            description={issue === 'rejected' ? 'Last bundle failed verification' : issue === 'unreachable' ? 'Fetch failed · no bundle received' : 'Checks run on every bundle before it is applied'}
            isMock={status.isMock}
          >
            <FeedUpdateSteps steps={steps} />
          </Panel>
          <Panel title="Recent signature hits" description="Decisions matched by feed signatures" flush isMock={hitsRes.isMock}>
            <SignatureHits hits={hits} onOpen={setOpenHit} />
          </Panel>
          <Panel title="Bundle history" description={s?.history?.length ? `${s.history.length} bundles applied` : undefined}>
            <FeedTimeline events={timeline} />
          </Panel>
        </div>
      </div>
      <DecisionDrawer decisionId={openHit?.id ?? null} open={Boolean(openHit)} onOpenChange={(o) => (o ? undefined : setOpenHit(null))} hint={openHit} />
    </div>
  );
}
