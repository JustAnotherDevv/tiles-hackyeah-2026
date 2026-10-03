// /security/threats — signed threat-intel feed: serial, verified key, expiry, update pipeline, signatures, hits.
// Reacts live to feed.updated (serial flip + new-row glow) and feed.rejected (red banner, failed verify step).
import { ExternalLink, RefreshCw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { api, isApiRequestError } from '@/api/client';
import { useApi, useEvents, useLiveDecisions } from '@/api/hooks';
import type { DecisionSummary, FeedSignatureView, FeedStatus, Page } from '@/api/types';
import { PageHeader, Panel, RoleGate } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { LockedAction } from '@/components/security/common';
import { DecisionDrawer } from '@/components/security/decision';
import { deriveFeedSteps } from '@/components/security/lib/feedSteps';
import { FeedBanner, FeedStatusStrip, FeedTimeline, FeedUpdateSteps, SignatureHits, SignatureTable, type RejectInfo, type TimelineEvent } from '@/components/security/threats';
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
      setReject({ ...d, at: Date.now() });
      setDismissedAt(null);
      setSessionEvents((ev) => [{ key: `r${Date.now()}`, at: Date.now(), kind: 'rejected' as const, title: `#${d.serial_attempted ?? '?'} rejected`, detail: d.reason }, ...ev].slice(0, 20));
    }
  });

  const s = status.data;
  const statusReject: RejectInfo | null =
    s && (s.status === 'rejected' || s.status === 'unreachable' || s.last_error) && dismissedAt !== (s.last_error ?? s.status)
      ? { reason: s.last_error ?? s.status, serial_attempted: s.serial !== null ? s.serial + 1 : null, kept_serial: s.serial, at: 0 }
      : null;
  const banner = reject ?? statusReject;
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
      ...(s?.history ?? []).map((h) => ({ key: `h${h.serial}`, at: h.applied_at, kind: 'applied' as const, title: `#${h.serial} applied`, detail: `${h.version} · +${h.added} −${h.removed} ~${h.modified}` })),
    ],
    [sessionEvents, s],
  );

  const checkNow = async () => {
    setChecking(true);
    try {
      const r = await api.post<FeedStatus>('/api/feed/refresh', {});
      toast.success(`Feed checked · serial #${r.data.serial ?? '—'} (${r.data.status})`);
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
        subtitle="Signed (ed25519) signature bundles — verified, self-tested and hot-swapped in-line, without a restart."
        actions={
          <div className="flex items-center gap-2">
            <Button asChild variant="ghost" size="sm">
              <a href={consoleUrl(s?.url)} target="_blank" rel="noreferrer">
                <ExternalLink /> Feed console
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
            setDismissedAt(s?.last_error ?? s?.status ?? 'x');
          }}
        />
      ) : null}
      {s ? <FeedStatusStrip status={s} rejected={Boolean(banner)} /> : <Skeleton className="h-[92px] w-full" />}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel title="Signatures" description={`${sigs.data?.items.length ?? 0} in the active bundle · hits over the last 24 h`} flush isMock={sigs.isMock}>
          {sigs.data ? <SignatureTable items={sigs.data.items} newIds={newIds} highlight={highlight} /> : <Skeleton className="m-4 h-64" />}
        </Panel>
        <div className="space-y-4">
          <Panel title="Update pipeline" description={banner ? 'Last bundle failed — later steps skipped' : 'Every bundle passes all six gates'} isMock={status.isMock}>
            <FeedUpdateSteps steps={steps} />
          </Panel>
          <Panel title="Recent signature hits" description="SIG-01/02/03 decisions — click to open the trace" flush isMock={hitsRes.isMock}>
            <SignatureHits hits={hits} onOpen={setOpenHit} />
          </Panel>
          <Panel title="Feed history">
            <FeedTimeline events={timeline} />
          </Panel>
        </div>
      </div>
      <DecisionDrawer decisionId={openHit?.id ?? null} open={Boolean(openHit)} onOpenChange={(o) => (o ? undefined : setOpenHit(null))} hint={openHit} />
    </div>
  );
}
