// Placeholder Command Center page (proves page auto-discovery). Owner: dashboard-shell.
import { useApi } from '@/api/hooks';
import type { HealthResponse } from '@/api/types';
import { JsonView, KpiTile, PageHeader, Panel } from '@/components/shell';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/',
  title: 'Command Center',
  icon: 'Gauge',
  section: 'Overview',
  order: 10,
  shortcut: 'g o',
  description: 'Live management overview',
};

const mockHealth = (): HealthResponse => ({
  status: 'degraded',
  version: '0.0.0-mock',
  uptime_s: 0,
  policy_version: 0,
  feed_serial: null,
  components: { gateway: 'off' },
});

export default function OverviewPage() {
  const health = useApi<HealthResponse>('/healthz', { mock: mockHealth, refreshMs: 10000 });
  return (
    <div>
      <PageHeader title="Command Center" subtitle="Scaffold placeholder — dashboard-shell replaces this page." icon="Gauge" />
      <div className="mb-3 grid grid-cols-1 gap-3 md:grid-cols-3">
        <KpiTile label="Gateway" icon="Server" value={health.data?.status ?? '…'} tone={health.data?.status === 'ok' ? 'good' : 'warn'} />
        <KpiTile label="Policy version" icon="FileCode" value={health.data?.policy_version ?? 0} />
        <KpiTile label="Feed serial" icon="Radar" value={health.data?.feed_serial ?? '—'} />
      </div>
      <Panel title="GET /healthz" description="Live from the gateway (mock fallback when unreachable)" isMock={health.isMock}>
        <JsonView value={health.data ?? null} />
      </Panel>
    </div>
  );
}
