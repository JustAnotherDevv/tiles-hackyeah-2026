// /security/coverage — OWASP LLM 2026 / Agentic (ASI) 2026 / MCP 2025 coverage regenerated live from the policy,
// the controls catalog, self-test results and per-control performance. Tabs in ?tab= (coverage | controls | selftest | performance).
import { Link, useSearchParams } from 'react-router-dom';
import { useApi } from '@/api/hooks';
import type { CoverageResponse, PerfResponse } from '@/api/types';
import { EmptyState, Segmented, PageHeader, Panel } from '@/components/shell';
import { Skeleton } from '@/components/ui/skeleton';
import { ControlsTable, CoverageMatrix, SelftestView, type SelftestReport } from '@/components/security/coverage';
import { useControlsCatalog } from '@/components/security/hooks';
import { BenchPanel, ControlLatencyChart, OverheadTiles, SemanticModels } from '@/components/security/perf';
import { mockCoverage, mockPerf } from '@/mocks/security';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/security/coverage',
  title: 'Coverage & controls',
  icon: 'ShieldCheck',
  section: 'Security',
  order: 50,
  shortcut: 'g c',
  description: 'OWASP coverage, the controls catalog, self-test results and per-control latency',
};

type Tab = 'coverage' | 'controls' | 'selftest' | 'performance';
const TABS: Tab[] = ['coverage', 'controls', 'selftest', 'performance'];

function PerformanceTab() {
  const perf = useApi<PerfResponse>('/api/perf', { mock: mockPerf, refreshMs: 5000 });
  const p = perf.data;
  if (!p) return perf.error ? <TabError title="Performance data unavailable" error={perf.error} onRetry={perf.refresh} /> : <Skeleton className="h-64 w-full" />;
  return (
    <div className="space-y-4">
      <OverheadTiles perf={p} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Panel title="Per-control latency" description="Time each control adds to a decision" isMock={perf.isMock}>
          <ControlLatencyChart items={p.by_control} />
        </Panel>
        <div className="min-w-0 space-y-4">
          <Panel title="Semantic models" description="Local ONNX and Ollama models; nothing leaves the host" isMock={perf.isMock}>
            <SemanticModels semantic={p.semantic} />
          </Panel>
          <Panel
            title="Benchmark"
            description="reports/bench.json (aegis.bench/1)"
            actions={
              <Link to="/system/perf" className="text-xs text-accent-fg hover:underline">
                System performance →
              </Link>
            }
            isMock={perf.isMock}
          >
            <BenchPanel bench={p.bench} />
          </Panel>
        </div>
      </div>
    </div>
  );
}

function SelftestTab() {
  const st = useApi<SelftestReport>('/api/selftest', { refreshMs: 30_000 });
  return <SelftestView report={st.data} error={st.error} isMock={st.isMock} />;
}

function TabError({ title, error, onRetry }: { title: string; error: Error; onRetry: () => Promise<void> }) {
  return (
    <section className="rounded-lg border border-border bg-card shadow-card">
      <EmptyState
        icon="CircleAlert"
        title={title}
        hint={error.message}
        action={
          <button type="button" onClick={() => void onRetry()} className="h-8 rounded-md border border-border px-3 text-xs text-text-2 hover:border-border-strong hover:text-text-1">
            Retry
          </button>
        }
      />
    </section>
  );
}

export default function CoveragePage() {
  const [params, setParams] = useSearchParams();
  const raw = params.get('tab');
  const tab: Tab = TABS.includes(raw as Tab) ? (raw as Tab) : 'coverage';
  const highlight = params.get('control');
  const coverage = useApi<CoverageResponse>('/api/coverage', { mock: () => mockCoverage(), refreshOn: ['policy.applied'], refreshMs: 15_000 });
  const controls = useControlsCatalog();
  const setTab = (t: Tab) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        n.set('tab', t);
        if (t !== 'controls') n.delete('control');
        return n;
      },
      { replace: true },
    );
  const enabled = controls.items.filter((c) => c.enabled && c.mode !== 'off').length;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Coverage & controls"
        icon="ShieldCheck"
        subtitle={
          <>
            <span className="font-mono tabular text-text-2">
              {enabled}/{controls.items.length || '—'}
            </span>{' '}
            controls active · OWASP LLM 2026, Agentic 2026 and MCP 2025 mapping, regenerated on every policy change
          </>
        }
        actions={
          <div className="max-w-full overflow-x-auto">
            <Segmented
              value={tab}
              onChange={setTab}
              ariaLabel="View"
              size="lg"
              options={[
                { value: 'coverage', label: 'Coverage' },
                { value: 'controls', label: 'Controls' },
                { value: 'selftest', label: 'Self-test' },
                { value: 'performance', label: 'Performance' },
              ]}
            />
          </div>
        }
      />
      {tab === 'coverage' ? (
        coverage.data ? (
          <div className="space-y-4">
            {coverage.isMock ? <Panel isMock title="Coverage" description="Endpoint unavailable; derived from the demo catalog" /> : null}
            <CoverageMatrix data={coverage.data} />
          </div>
        ) : coverage.error ? (
          <TabError title="Coverage unavailable" error={coverage.error} onRetry={coverage.refresh} />
        ) : (
          <Skeleton className="h-96 w-full" />
        )
      ) : null}
      {tab === 'controls' ? (
        <Panel title="Controls catalog" description="Live from the loaded policy; refreshed on every policy change" flush isMock={controls.isMock}>
          {controls.items.length ? <ControlsTable items={controls.items} highlight={highlight} /> : <Skeleton className="m-4 h-64" />}
        </Panel>
      ) : null}
      {tab === 'selftest' ? <SelftestTab /> : null}
      {tab === 'performance' ? <PerformanceTab /> : null}
    </div>
  );
}
