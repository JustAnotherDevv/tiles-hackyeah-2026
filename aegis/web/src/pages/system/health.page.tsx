// /system/health — overall status, /healthz components, versions, live-event stream status, threat feed,
// local models, audit-chain verification, demo-data toggle and (UIS-20) admin token. Owner: B16.
import { CheckCircle2, KeyRound, Loader2, ShieldCheck, TriangleAlert, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api, isApiRequestError } from '@/api/client';
import { eventHub } from '@/api/sse';
import { useApi, useSseStatus } from '@/api/hooks';
import type { AuditVerifyResult, FeedStatus, HealthResponse, PerfResponse } from '@/api/types';
import { MockBadge, PageHeader, Panel, StatusDot, TimeAgo } from '@/components/shell';
import { toggleDemoData } from '@/components/shell/CommandPalette';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { fmtDuration, fmtNum } from '@/lib/format';
import { isMockForced } from '@/lib/mockMode';
import type { PageMeta } from '@/lib/page';
import { readString, STORAGE_KEYS, writeString } from '@/lib/storage';
import { cn } from '@/lib/utils';
import { mockHealth, mockSemanticStatus } from '@/mocks/shell/health';
import { mockFeedStatus } from '@/mocks/shell/posture';

export const meta: PageMeta = {
  path: '/system/health',
  title: 'System health',
  icon: 'HeartPulse',
  section: 'System',
  order: 20,
  shortcut: 'g h',
  description: 'Components, versions, live stream, feed, models and audit-chain verification',
};

type CompState = HealthResponse['components'][string];
const COMP: Record<CompState, { dot: 'ok' | 'warn' | 'error' | 'off'; label: string }> = {
  ok: { dot: 'ok', label: 'ok' },
  degraded: { dot: 'warn', label: 'degraded' },
  stale: { dot: 'warn', label: 'stale' },
  down: { dot: 'error', label: 'down' },
  off: { dot: 'off', label: 'off' },
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 border-b border-border-subtle py-2 text-[12.5px] last:border-b-0">
      <span className="text-text-3">{label}</span>
      <span className="ml-auto min-w-0 truncate text-right text-text-1">{children}</span>
    </div>
  );
}

function AuditVerifyPanel() {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ data: AuditVerifyResult; isMock: boolean } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.get<AuditVerifyResult>('/api/audit/verify', () => ({
        ok: true,
        records: 48_216,
        head_hash: 'b3f1c0de9a7e4d21f0c8a6e5d4c3b2a1908f7e6d5c4b3a291807f6e5d4c3b2a1',
        broken_at_seq: null,
        files: 3,
        checked_at: new Date().toISOString(),
        message: 'chain intact (demo data)',
      }));
      setRes(r);
    } catch (e) {
      setErr(isApiRequestError(e) ? e.message : 'Gateway unreachable');
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    void run();
  }, []);
  const d = res?.data;
  return (
    <Panel
      title="Audit hash chain"
      description="Every decision is appended to a SHA-256 hash-chained JSONL log; verification re-hashes the whole chain"
      isMock={res?.isMock}
      actions={
        <Button size="sm" variant="secondary" onClick={() => void run()} disabled={busy}>
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : <ShieldCheck className="size-3.5" />}
          Verify audit chain
        </Button>
      }
    >
      {err ? (
        <div className="flex items-center gap-2 text-[13px] text-block">
          <XCircle className="size-4" /> {err}
        </div>
      ) : d ? (
        <div className="flex items-start gap-4">
          <div className={cn('grid size-11 shrink-0 place-items-center rounded-xl border', d.ok ? 'border-allow/30 bg-allow/10 text-allow' : 'border-block/30 bg-block/10 text-block')}>
            {d.ok ? <CheckCircle2 className="size-5" /> : <TriangleAlert className="size-5" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-semibold">{d.ok ? `Chain OK · ${fmtNum(d.records)} records` : `Chain broken at seq ${d.broken_at_seq ?? '?'}`}</div>
            <div className="mt-0.5 text-[12.5px] text-text-3">{d.message}</div>
            <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-text-3">
              <span>
                head <span className="font-mono text-text-2">{d.head_hash.slice(0, 16)}…</span>
              </span>
              <span>{d.files} file(s)</span>
              <span>
                checked <TimeAgo ts={d.checked_at} />
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="skel h-12 w-full" />
      )}
    </Panel>
  );
}

function AdminTokenPanel() {
  const [val, setVal] = useState(() => readString(STORAGE_KEYS.adminToken) ?? '');
  const [saved, setSaved] = useState(Boolean(readString(STORAGE_KEYS.adminToken)));
  return (
    <Panel title="Admin token" description="Only needed when the gateway runs with AEGIS_ADMIN_TOKEN — sent as Authorization: Bearer on mutating /api calls. Stored in this browser only.">
      <div className="flex items-center gap-2">
        <KeyRound className="size-4 shrink-0 text-text-3" />
        <Input type="password" value={val} onChange={(e) => setVal(e.target.value)} placeholder="not set" className="h-8 font-mono text-[12.5px]" autoComplete="off" />
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            writeString(STORAGE_KEYS.adminToken, val.trim() || null);
            setSaved(Boolean(val.trim()));
          }}
        >
          {saved && val ? 'Saved' : 'Save'}
        </Button>
      </div>
    </Panel>
  );
}

export default function HealthPage() {
  const health = useApi<HealthResponse>('/healthz', { mock: mockHealth, refreshMs: 5000 });
  const feed = useApi<FeedStatus>('/api/feed/status', { mock: mockFeedStatus, refreshMs: 15_000, refreshOn: ['feed.updated', 'feed.rejected'] });
  const semantic = useApi<PerfResponse['semantic']>('/api/semantic/status', { mock: mockSemanticStatus, refreshMs: 15_000 });
  const sse = useSseStatus();
  const [, force] = useState(0);
  useEffect(() => {
    const t = setInterval(() => force((n) => n + 1), 2000);
    return () => clearInterval(t);
  }, []);
  const h = health.data;
  const comps = Object.entries(h?.components ?? {});
  const down = comps.filter(([, v]) => v === 'down').length;
  const ok = h?.status === 'ok' && down === 0;
  const mockOn = isMockForced();
  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="System health" icon="HeartPulse" subtitle="Everything runs locally — gateway, policy engine, models, audit log and threat feed" />

      <div
        className={cn(
          'flex items-center gap-3 rounded-lg border px-4 py-3',
          !h ? 'border-border bg-card' : ok ? 'border-allow/25 bg-[linear-gradient(90deg,rgba(30,159,104,.12),rgba(30,159,104,.02))]' : 'border-redact/30 bg-[linear-gradient(90deg,rgba(201,133,0,.14),rgba(201,133,0,.02))]',
        )}
      >
        <StatusDot status={!h ? 'off' : ok ? 'ok' : down ? 'error' : 'warn'} pulse />
        <div className="text-[14px] font-semibold">{!h ? 'Checking…' : ok ? 'All systems operational' : down ? `${down} component${down > 1 ? 's' : ''} down — fail-safe defaults active` : 'Degraded — deterministic controls still enforce'}</div>
        {health.isMock ? <MockBadge /> : null}
        <div className="ml-auto flex items-center gap-4 text-[12px] text-text-3">
          <span>
            gateway <span className="font-mono text-text-2">v{h?.version ?? '—'}</span>
          </span>
          <span>
            uptime <span className="tabular text-text-2">{h ? fmtDuration(h.uptime_s) : '—'}</span>
          </span>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-3">
        <Panel className="col-span-7 max-[1180px]:col-span-12" title="Components" description="GET /healthz · refreshed every 5 s" isMock={health.isMock}>
          <div className="grid grid-cols-3 gap-2 max-[900px]:grid-cols-2">
            {comps.map(([name, st]) => (
              <div key={name} className="flex items-center gap-2.5 rounded-md border border-border bg-surface-2/50 px-3 py-2.5">
                <StatusDot status={COMP[st]?.dot ?? 'off'} />
                <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-text-1">{name}</span>
                <span className={cn('text-[11.5px]', st === 'ok' ? 'text-text-3' : st === 'down' ? 'text-block' : 'text-redact')}>{COMP[st]?.label ?? st}</span>
              </div>
            ))}
            {h && comps.length === 0 ? <div className="col-span-3 text-[12.5px] text-text-3">No components reported.</div> : null}
          </div>
        </Panel>
        <Panel className="col-span-5 max-[1180px]:col-span-12" title="Versions & live stream">
          <Row label="Policy version">
            <span className="font-mono">v{h?.policy_version ?? '—'}</span>
          </Row>
          <Row label="Threat feed serial">
            <span className="font-mono">#{h?.feed_serial ?? '—'}</span>
          </Row>
          <Row label="Live events (SSE)">
            <span className="inline-flex items-center gap-2">
              <StatusDot status={sse === 'live' || sse === 'mock' ? 'ok' : sse === 'offline' ? 'error' : 'warn'} />
              {sse === 'mock' ? 'demo stream (mocks forced)' : sse}
              {sse === 'offline' || sse === 'reconnecting' ? (
                <button type="button" className="text-accent-fg hover:underline" onClick={() => eventHub.retryNow()}>
                  retry
                </button>
              ) : null}
            </span>
          </Row>
          <Row label="Last event">{eventHub.lastEventAt ? <TimeAgo ts={eventHub.lastEventAt} /> : '—'}</Row>
          <Row label="Demo data (mocks forced)">
            <span className="inline-flex items-center gap-2">
              <span className="text-text-3">{mockOn ? 'on' : 'off'}</span>
              <Switch checked={mockOn} onCheckedChange={() => toggleDemoData()} aria-label="Force demo data" />
            </span>
          </Row>
        </Panel>
      </div>

      <div className="grid grid-cols-12 gap-3">
        <Panel className="col-span-6 max-[1180px]:col-span-12" title="Threat feed" description="Ed25519-signed signature bundle" isMock={feed.isMock}>
          {feed.data ? (
            <>
              <Row label="Status">
                <span className={cn(feed.data.status === 'ok' ? 'text-allow' : feed.data.status === 'rejected' || feed.data.status === 'unreachable' ? 'text-block' : 'text-redact')}>{feed.data.status}</span>
              </Row>
              <Row label="Serial · version">
                <span className="font-mono">
                  #{feed.data.serial ?? '—'} · {feed.data.version ?? '—'}
                </span>
              </Row>
              <Row label="Signing key">
                <span className="font-mono">{feed.data.key_id ?? '—'}</span>
              </Row>
              <Row label="Signatures">
                {feed.data.signatures_active} active · {feed.data.signatures_monitor} monitor · {feed.data.signatures_quarantined} quarantined
              </Row>
              <Row label="Last check">{feed.data.last_check ? <TimeAgo ts={feed.data.last_check} /> : '—'}</Row>
              {feed.data.last_error ? (
                <Row label="Last error">
                  <span className="text-block">{feed.data.last_error}</span>
                </Row>
              ) : null}
            </>
          ) : (
            <div className="skel h-24 w-full" />
          )}
        </Panel>
        <Panel className="col-span-6 max-[1180px]:col-span-12" title="Local models" description={semantic.data ? `mode ${semantic.data.mode}${semantic.data.degraded ? ' · degraded' : ''}` : 'GET /api/semantic/status'} isMock={semantic.isMock}>
          {(semantic.data?.models ?? []).map((m) => (
            <Row key={m.name} label={m.name}>
              <span className="inline-flex items-center gap-2">
                <span className="rounded border border-border bg-surface-2 px-1.5 font-mono text-[10.5px] text-text-3">{m.backend}</span>
                <StatusDot status={m.loaded ? 'ok' : 'off'} label={m.loaded ? `${m.p50_ms !== null ? `p50 ${m.p50_ms} ms` : 'loaded'}` : 'not loaded'} />
              </span>
            </Row>
          ))}
          {semantic.data && semantic.data.models.length === 0 ? <div className="text-[12.5px] text-text-3">No local models — deterministic controls only.</div> : null}
          {!semantic.data ? <div className="text-[12.5px] text-text-3">unknown</div> : null}
        </Panel>
      </div>

      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-8 max-[1180px]:col-span-12">
          <AuditVerifyPanel />
        </div>
        <div className="col-span-4 max-[1180px]:col-span-12">
          <AdminTokenPanel />
        </div>
      </div>
    </div>
  );
}
