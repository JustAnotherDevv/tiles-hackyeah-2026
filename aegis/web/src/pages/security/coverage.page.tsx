// /security/coverage — OWASP LLM 2026 / Agentic (ASI) 2026 / MCP 2025 coverage regenerated live from the policy,
// the controls catalog, and per-control performance. Tabs in ?tab= (coverage | controls | performance).
import { Link, useSearchParams } from 'react-router-dom';
import { useApi } from '@/api/hooks';
import type { CoverageResponse, PerfResponse } from '@/api/types';
import { Segmented, PageHeader, Panel } from '@/components/shell';
import { Skeleton } from '@/components/ui/skeleton';
import { ControlsTable, CoverageMatrix } from '@/components/security/coverage';
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
  description: 'OWASP coverage, the controls catalog and per-control latency — generated from the live policy',
};

type Tab = 'coverage' | 'controls' | 'performance';

function PerformanceTab() {
  const perf = useApi<PerfResponse>('/api/perf', { mock: mockPerf, refreshMs: 5000 });
  const p = perf.data;
  if (!p) return <Skeleton className="h-64 w-full" />;
  return (
    <div className="space-y-4">
      <OverheadTiles perf={p} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Panel title="Per-control latency" description="p50 (grey) and p95 (by kind) · sorted by p95 · sqrt scale" isMock={perf.isMock}>
          <ControlLatencyChart items={p.by_control} />
        </Panel>
        <div className="space-y-4">
          <Panel title="Semantic models" description="Local ONNX / Ollama — nothing leaves the host" isMock={perf.isMock}>
            <SemanticModels semantic={p.semantic} />
          </Panel>
          <Panel title="Benchmark" description="reports/bench.json (aegis.bench/1)" actions={<Link to="/system/perf" className="text-xs text-accent-fg hover:underline">System perf →</Link>} isMock={perf.isMock}>
            <BenchPanel bench={p.bench} />
          </Panel>
        </div>
      </div>
    </div>
  );
}

export default function CoveragePage() {
  const [params, setParams] = useSearchParams();
  const raw = params.get('tab');
  const tab: Tab = raw === 'controls' || raw === 'performance' ? raw : 'coverage';
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
        subtitle={`${enabled} of ${controls.items.length || '—'} controls active · coverage is regenerated from the live policy — disable a control and its tiles turn red within a second.`}
        actions={
          <Segmented
            value={tab}
            onChange={setTab}
            ariaLabel="View"
            options={[
              { value: 'coverage', label: 'Coverage' },
              { value: 'controls', label: 'Controls' },
              { value: 'performance', label: 'Performance' },
            ]}
          />
        }
      />
      {tab === 'coverage' ? (
        coverage.data ? (
          <div className="space-y-2">
            {coverage.isMock ? <Panel isMock title="Coverage" description="Endpoint unavailable — derived from the demo catalog" /> : null}
            <CoverageMatrix data={coverage.data} />
          </div>
        ) : (
          <Skeleton className="h-96 w-full" />
        )
      ) : null}
      {tab === 'controls' ? (
        <Panel title="Controls catalog" description="GET /api/controls · refreshed on every policy.applied" flush isMock={controls.isMock}>
          {controls.items.length ? <ControlsTable items={controls.items} highlight={highlight} /> : <Skeleton className="m-4 h-64" />}
        </Panel>
      ) : null}
      {tab === 'performance' ? <PerformanceTab /> : null}
    </div>
  );
}
