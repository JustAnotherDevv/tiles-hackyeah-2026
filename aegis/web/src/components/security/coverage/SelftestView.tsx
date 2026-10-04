// Self-test results (GET /api/selftest → reports/results.json, schema aegis.selftest/1): run summary, status
// legend (incl. PARTIAL), per-control matrix, suites and corpus detection/false-positive rates.
import { useMemo, useState, type ReactNode } from 'react';
import { apiUrl } from '@/api/client';
import { ExternalLink } from '@/components/icons';
import { EmptyState, MockBadge } from '@/components/shell';
import { Skeleton } from '@/components/ui/skeleton';
import { fmtAgo, fmtDateTime, fmtDuration, fmtMs, fmtNum } from '@/lib/format';
import { cn } from '@/lib/utils';
import { ControlChip } from '../common/atoms';
import { MiniSelect } from '../live/FeedFilters';

type Ratio = { passed: number; total: number };

export interface SelftestControl {
  control_id: string;
  family: string;
  name: string;
  status: string;
  enabled: boolean;
  mode: string;
  implemented: boolean;
  attack: Ratio;
  benign: Ratio;
  redact: Ratio;
  error: Ratio;
  other_control: number;
  xfail: number;
  p50_ms: number | null;
  p95_ms: number | null;
  owasp: string[];
}

export interface SelftestCorpus {
  corpus: string;
  attacks: number;
  benign: number;
  detection_rate: number | null;
  detection_ci: [number, number] | null;
  fpr: number | null;
  fpr_ci: [number, number] | null;
}

export interface SelftestReport {
  schema: string;
  generated_at: string;
  mode?: string;
  duration_s?: number;
  git_sha?: string | null;
  stack_error?: string | null;
  running?: boolean;
  gateway?: { version?: string; policy_version?: number; profile?: string; feed_serial?: number; semantic?: string } | null;
  totals: { cases: number; passed: number; pass_other?: number; failed: number; skipped: number; xfailed: number; untested_controls?: number; disabled_controls?: number };
  controls: SelftestControl[];
  suites?: { id: string; title: string; passed: number; total: number; status: string }[];
  perf?: { corpora?: Record<string, SelftestCorpus> } | null;
}

// mirrors tests/lib/report.py STATUS_LEGEND (precedence order of tests/lib/matrix.py)
const STATUS_INFO: Record<string, { cls: string; meaning: string }> = {
  PASS: { cls: 'text-allow border-allow/30 bg-allow/10', meaning: 'Every case for the control passed.' },
  PARTIAL: {
    cls: 'text-redact border-redact/30 bg-redact/10',
    meaning: 'Every gating (core) case passed; the control also has documented expected failures (xfail) for known gaps. These never fail the run.',
  },
  FAIL: { cls: 'text-block border-block/30 bg-block/10', meaning: 'A gating (core) case failed.' },
  UNTESTED: { cls: 'text-text-2 border-border-strong bg-surface-2', meaning: 'No must-block or no must-allow case exists for the control.' },
  SKIPPED: { cls: 'text-text-3 border-border bg-surface-2', meaning: 'All cases were skipped, e.g. semantic cases with the semantic tier off.' },
  DISABLED: { cls: 'text-text-3 border-border bg-surface-2', meaning: 'The control is switched off in the loaded policy.' },
  NOT_IMPLEMENTED: { cls: 'text-text-3 border-dashed border-border-strong', meaning: 'In the catalog but not implemented.' },
};
const ORDER = Object.keys(STATUS_INFO);

export function SelftestStatus({ status }: { status: string }) {
  const s = STATUS_INFO[status] ?? STATUS_INFO.SKIPPED;
  return <span className={cn('inline-flex h-5 items-center rounded-[4px] border px-1.5 font-mono text-[10.5px] font-medium tracking-wide', s.cls)}>{status}</span>;
}

function Frac({ r }: { r: Ratio }) {
  if (!r.total) return <span className="text-text-4">—</span>;
  return (
    <span className={cn(r.passed < r.total ? 'text-redact' : 'text-text-1')}>
      {r.passed}
      <span className="text-text-4">/{r.total}</span>
    </span>
  );
}

const pct = (v: number | null | undefined, dp = 1) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(dp)}%`);
const ci = (c: [number, number] | null | undefined) => (c ? `${(c[0] * 100).toFixed(0)}–${(c[1] * 100).toFixed(0)}%` : '');

const TH = 'whitespace-nowrap px-2 py-2 text-left text-2xs font-medium uppercase tracking-[0.06em] text-text-3';
const TD = 'whitespace-nowrap px-2 py-1.5 max-md:py-2.5';

function Section({ title, description, actions, children, flush }: { title: string; description?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean }) {
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card shadow-card">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border-subtle px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-[13px] font-[550] leading-[18px] text-text-1">{title}</h2>
          {description ? <p className="text-xs leading-4 text-text-3">{description}</p> : null}
        </div>
        {actions}
      </header>
      <div className={flush ? '' : 'p-4'}>{children}</div>
    </section>
  );
}

export function SelftestView({ report, error, isMock }: { report: SelftestReport | undefined; error: Error | null; isMock?: boolean }) {
  const [status, setStatus] = useState('');
  const [family, setFamily] = useState('');
  const controls = useMemo(() => report?.controls ?? [], [report]);
  const present = useMemo(() => new Set(controls.map((c) => c.status)), [controls]);
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of controls) m.set(c.status, (m.get(c.status) ?? 0) + 1);
    return m;
  }, [controls]);
  const families = useMemo(() => [...new Set(controls.map((c) => c.family))].sort(), [controls]);
  const rows = useMemo(() => controls.filter((c) => (!status || c.status === status) && (!family || c.family === family)), [controls, status, family]);

  if (!report && !error) return <Skeleton className="h-64 w-full" />;
  if (!report) {
    const missing = error && /no self-test report|not_found|404/i.test(error.message);
    return (
      <section className="rounded-lg border border-border bg-card shadow-card">
        <EmptyState
          icon={missing ? 'FlaskConical' : 'CircleAlert'}
          title={missing ? 'No self-test report yet' : 'Self-test results unavailable'}
          hint={
            missing ? (
              <>
                Run <code className="font-mono text-text-1">make test</code> to generate <code className="font-mono text-text-1">reports/results.json</code>.
              </>
            ) : (
              error?.message
            )
          }
        />
      </section>
    );
  }

  const t = report.totals;
  const verdict = t.failed > 0 ? 'FAIL' : counts.get('PARTIAL') ? 'PARTIAL' : 'PASS';
  const legend = ORDER.filter((s) => s === 'PASS' || s === 'PARTIAL' || s === 'FAIL' || present.has(s));
  const corpora = Object.values(report.perf?.corpora ?? {});

  return (
    <div className="space-y-4">
      <Section
        title="Last run"
        description={
          <>
            {report.mode ? `${report.mode} · ` : ''}
            {report.git_sha ? <span className="font-mono">{report.git_sha}</span> : null}
            {report.gateway?.policy_version !== undefined ? ` · policy v${report.gateway.policy_version}` : ''}
            {report.gateway?.profile ? ` · ${report.gateway.profile}` : ''}
            {report.gateway?.semantic ? ` · semantic ${report.gateway.semantic}` : ''}
          </>
        }
        actions={
          <div className="flex items-center gap-2">
            {isMock ? <MockBadge /> : null}
            {report.running ? <span className="text-xs text-accent-fg">Run in progress…</span> : null}
            <a href={apiUrl('/api/selftest/report')} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs text-accent-fg hover:underline max-md:h-9">
              HTML report <ExternalLink className="size-3" />
            </a>
          </div>
        }
      >
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4 xl:grid-cols-8">
          {(
            [
              ['Result', <SelftestStatus key="v" status={verdict} />],
              ['Cases', fmtNum(t.cases)],
              ['Passed', fmtNum(t.passed + (t.pass_other ?? 0))],
              ['Failed', <span key="f" className={t.failed ? 'text-block' : undefined}>{fmtNum(t.failed)}</span>],
              ['Expected failures', fmtNum(t.xfailed)],
              ['Skipped', fmtNum(t.skipped)],
              ['Duration', report.duration_s !== undefined ? fmtDuration(report.duration_s) : '—'],
              [
                'Run at',
                <span key="t" title={fmtDateTime(report.generated_at)}>
                  {fmtAgo(report.generated_at)}
                </span>,
              ],
            ] as [string, ReactNode][]
          ).map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="text-2xs text-text-3">{k}</dt>
              <dd className="mt-0.5 truncate font-mono text-[13px] tabular text-text-1">{v}</dd>
            </div>
          ))}
        </dl>
        {report.stack_error ? <p className="mt-3 text-xs text-block">{report.stack_error}</p> : null}
      </Section>

      <Section title="Status legend" description="Per-control status, first match wins">
        <dl className="grid gap-x-6 gap-y-2 md:grid-cols-2">
          {legend.map((s) => (
            <div key={s} className="flex items-start gap-2.5 text-xs">
              <dt className="w-[124px] shrink-0">
                <SelftestStatus status={s} />
                <span className="ml-1.5 font-mono tabular text-text-3">{counts.get(s) ?? 0}</span>
              </dt>
              <dd className="leading-5 text-text-2">{STATUS_INFO[s].meaning}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section
        title="Controls"
        description="Attack = must-block cases, benign = must-allow cases; latency measured during the run"
        flush
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <MiniSelect label="Status" value={status} onChange={setStatus} className="max-md:h-9" options={ORDER.filter((s) => present.has(s)).map((s) => ({ value: s, label: s }))} />
            <MiniSelect label="Family" value={family} onChange={setFamily} className="max-md:h-9" options={families.map((f) => ({ value: f, label: f }))} />
          </div>
        }
      >
        {rows.length ? (
          <div className="max-h-[560px] overflow-auto overscroll-contain">
            <table className="w-full min-w-[860px] text-xs">
              <thead className="sticky top-0 z-[1] bg-surface-1">
                <tr className="border-b border-border">
                  <th className={cn(TH, 'pl-4')}>Control</th>
                  <th className={TH}>Status</th>
                  <th className={cn(TH, 'text-right')}>Attack</th>
                  <th className={cn(TH, 'text-right')}>Benign</th>
                  <th className={cn(TH, 'text-right')}>Redact</th>
                  <th className={cn(TH, 'text-right')}>Xfail</th>
                  <th className={cn(TH, 'text-right')}>p50</th>
                  <th className={cn(TH, 'text-right')}>p95</th>
                  <th className={cn(TH, 'pr-4')}>OWASP</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.control_id} className={cn('border-b border-border-subtle hover:bg-surface-2/50', !c.enabled && 'opacity-60')}>
                    <td className={cn(TD, 'max-w-[320px] pl-4')}>
                      <div className="flex items-center gap-2">
                        <ControlChip id={c.control_id} href={`/security/coverage?tab=controls&control=${encodeURIComponent(c.control_id)}`} />
                        <span className="truncate text-text-1" title={c.name}>
                          {c.name}
                        </span>
                      </div>
                    </td>
                    <td className={TD}>
                      <SelftestStatus status={c.status} />
                    </td>
                    <td className={cn(TD, 'text-right font-mono tabular')}>
                      <Frac r={c.attack} />
                    </td>
                    <td className={cn(TD, 'text-right font-mono tabular')}>
                      <Frac r={c.benign} />
                    </td>
                    <td className={cn(TD, 'text-right font-mono tabular')}>
                      <Frac r={c.redact} />
                    </td>
                    <td className={cn(TD, 'text-right font-mono tabular', c.xfail ? 'text-redact' : 'text-text-4')}>{c.xfail || '—'}</td>
                    <td className={cn(TD, 'text-right font-mono tabular text-text-2')}>{fmtMs(c.p50_ms)}</td>
                    <td className={cn(TD, 'text-right font-mono tabular text-text-2')}>{fmtMs(c.p95_ms)}</td>
                    <td className={cn(TD, 'pr-4 font-mono text-2xs text-text-3')}>{c.owasp.slice(0, 3).join(' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon="SearchX" title="No controls match these filters" />
        )}
      </Section>

      <div className="grid min-w-0 gap-4 xl:grid-cols-2">
        {report.suites?.length ? (
          <Section title="Suites" flush>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <th className={cn(TH, 'pl-4')}>Suite</th>
                    <th className={cn(TH, 'text-right')}>Passed</th>
                    <th className={cn(TH, 'pr-4 text-right')}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {report.suites.map((s) => (
                    <tr key={s.id} className="border-b border-border-subtle last:border-0">
                      <td className={cn(TD, 'pl-4 text-text-1')}>{s.title}</td>
                      <td className={cn(TD, 'text-right font-mono tabular')}>
                        <Frac r={s} />
                      </td>
                      <td className={cn(TD, 'pr-4 text-right')}>
                        <SelftestStatus status={s.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        ) : null}
        {corpora.length ? (
          <Section title="Corpora" description="Detection rate and false-positive rate with 95% confidence intervals" flush>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <th className={cn(TH, 'pl-4')}>Corpus</th>
                    <th className={cn(TH, 'text-right')}>Attacks</th>
                    <th className={cn(TH, 'text-right')}>Benign</th>
                    <th className={cn(TH, 'text-right')}>Detection</th>
                    <th className={cn(TH, 'pr-4 text-right')}>False positives</th>
                  </tr>
                </thead>
                <tbody>
                  {corpora.map((c) => (
                    <tr key={c.corpus} className="border-b border-border-subtle last:border-0">
                      <td className={cn(TD, 'pl-4 font-mono text-text-1')}>{c.corpus}</td>
                      <td className={cn(TD, 'text-right font-mono tabular')}>{fmtNum(c.attacks)}</td>
                      <td className={cn(TD, 'text-right font-mono tabular')}>{fmtNum(c.benign)}</td>
                      <td className={cn(TD, 'text-right font-mono tabular text-text-1')}>
                        {pct(c.detection_rate)} <span className="text-2xs text-text-4">{c.detection_rate !== null ? ci(c.detection_ci) : ''}</span>
                      </td>
                      <td className={cn(TD, 'pr-4 text-right font-mono tabular text-text-1')}>
                        {pct(c.fpr)} <span className="text-2xs text-text-4">{c.fpr !== null ? ci(c.fpr_ci) : ''}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        ) : null}
      </div>
    </div>
  );
}
