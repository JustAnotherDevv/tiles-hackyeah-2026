// /security/playground — run any prompt / tool call through the real pipeline (POST /api/playground),
// replay each stage paced by its measured timing, and show the verdict and the Wire diff.
import { ArrowLeftRight, ExternalLink, RefreshCw, WifiOff, Timer, ShieldAlert } from '@/components/icons';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, isApiRequestError, request } from '@/api/client';
import { useApi, useEvents, useViewerId } from '@/api/hooks';
import type { DecisionDetail, PlaygroundRequest, PlaygroundResponse } from '@/api/types';
import { ActionBadge, EmptyState, MockBadge, PageHeader, Panel } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { ControlChip } from '@/components/security/common';
import { DecisionTrace, type TraceTab } from '@/components/security/decision';
import { useAgentsIndex, useControlsCatalog, useCurrentVersions } from '@/components/security/hooks';
import { buildTrace } from '@/components/security/lib/trace';
import { PreviewText } from '@/components/security/live';
import { closestCall, detailFromPlayground, destClassOf } from '@/components/security/playground/adapter';
import { formFromPreset, INITIAL_FORM, parseToolArgs, PlaygroundForm, PresetPicker, type PlaygroundFormState } from '@/components/security/playground/PlaygroundForm';
import { presetById, PRESETS } from '@/components/security/playground/presets';
import { FlowStrip, RunHistory, ScanningControls, Spinner, useRevealSchedule, VerdictHero, type RunRecord } from '@/components/security/playground/visuals';
import { RedactionDiff } from '@/components/security/redaction';
import type { PlaygroundPreset } from '@/components/security/types';
import { mockDecisionDetail, mockPlayground } from '@/mocks/security';
import { isMockForced } from '@/lib/mockMode';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/security/playground',
  title: 'Playground',
  icon: 'FlaskConical',
  section: 'Security',
  order: 20,
  shortcut: 'g y',
  description: 'Run a prompt or tool call through the live control pipeline',
};

const TIMEOUT_MS = 30_000;

interface RunState {
  key: string;
  label: string;
  req: PlaygroundRequest;
  resp: PlaygroundResponse;
  detail: DecisionDetail;
  isMock: boolean;
}

type RunError = { kind: 'offline' | 'timeout' | 'rejected' | 'server' | 'unknown'; title: string; message: string; retry: 'run' | 'compare' };

function toRequest(f: PlaygroundFormState): PlaygroundRequest {
  const args = parseToolArgs(f.toolArgs).value;
  return {
    text: f.text,
    surface: f.surface,
    destination: f.destination,
    model: f.model.trim() || null,
    agent_id: f.agentId || null,
    tool_name: f.toolName.trim() || null,
    tool_args: args,
    send: f.send,
  };
}

class TimeoutError extends Error {}

/** Live gateway only (demo data is used solely when mock mode is forced), with a hard timeout. */
async function runPlayground(req: PlaygroundRequest, outer?: AbortSignal): Promise<{ resp: PlaygroundResponse; isMock: boolean }> {
  const ctl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    ctl.abort();
  }, TIMEOUT_MS);
  const onOuter = () => ctl.abort();
  outer?.addEventListener('abort', onOuter);
  try {
    const r = await request<PlaygroundResponse>('POST', '/api/playground', req, isMockForced() ? () => mockPlayground(req) : undefined, { signal: ctl.signal });
    return { resp: r.data, isMock: r.isMock };
  } catch (e) {
    if (timedOut) throw new TimeoutError();
    throw e;
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener('abort', onOuter);
  }
}

function describeError(e: unknown, retry: RunError['retry']): RunError {
  if (e instanceof TimeoutError)
    return { kind: 'timeout', title: 'Request timed out', message: `The gateway did not answer within ${TIMEOUT_MS / 1000} s. If "Send to model" is on, the upstream model may be slow; try again with it off.`, retry };
  if (isApiRequestError(e)) {
    if (e.status >= 500 && !e.envelope)
      return { kind: 'offline', title: 'Gateway unavailable', message: `The dashboard could not reach the Aegis gateway (HTTP ${e.status}). Check that the stack is running (make up), then retry.`, retry };
    if (e.status >= 500) return { kind: 'server', title: `Gateway error · ${e.status}`, message: e.message, retry };
    return { kind: 'rejected', title: `Request rejected · ${e.status} ${e.type}`, message: e.message, retry };
  }
  if (e instanceof TypeError) return { kind: 'offline', title: 'Gateway unreachable', message: 'No response from the Aegis gateway. Check that the stack is running (make up), then retry.', retry };
  return { kind: 'unknown', title: 'Request failed', message: e instanceof Error ? e.message : String(e), retry };
}

function InlineError({ error, onRetry, onDismiss }: { error: RunError; onRetry: () => void; onDismiss: () => void }) {
  const Icon = error.kind === 'offline' ? WifiOff : error.kind === 'timeout' ? Timer : ShieldAlert;
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-lg border border-border bg-card px-4 py-3 shadow-card sm:flex-row sm:items-start">
      <Icon className="mt-0.5 size-4 shrink-0 text-redact" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-text-1">{error.title}</div>
        <p className="mt-0.5 break-words text-xs leading-5 text-text-3">{error.message}</p>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
        <Button variant="ghost" size="sm" onClick={onDismiss}>
          Dismiss
        </Button>
      </div>
    </div>
  );
}

function CompareColumn({ title, detail }: { title: string; detail: DecisionDetail }) {
  const out = detail.wire?.outbound?.[0]?.text ?? detail.preview;
  return (
    <div className="min-w-0 py-3 first:pt-0 md:px-4 md:py-0 md:first:pl-0 md:last:pr-0">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-text-1">{title}</span>
        <ActionBadge action={detail.action} size="sm" />
        {detail.control_id ? <ControlChip id={detail.control_id} /> : null}
        <span className="ml-auto font-mono text-2xs tabular-nums text-text-3">
          {detail.redaction_count} redaction{detail.redaction_count === 1 ? '' : 's'}
        </span>
      </div>
      <div className="whitespace-pre-wrap break-words rounded-md border border-border-subtle bg-background px-2.5 py-2 text-xs">
        <PreviewText text={out} className="whitespace-pre-wrap" />
      </div>
    </div>
  );
}

export default function PlaygroundPage() {
  const [params] = useSearchParams();
  const viewer = useViewerId();
  const { agents } = useAgentsIndex();
  const { catalog } = useControlsCatalog();
  const current = useCurrentVersions();
  const [presetId, setPresetId] = useState<string | null>(() => (params.get('from') ? null : (presetById(params.get('preset'))?.id ?? 'pii')));
  const [form, setForm] = useState<PlaygroundFormState>(() => {
    if (params.get('from')) return INITIAL_FORM;
    const p = presetById(params.get('preset')) ?? PRESETS[0];
    return p ? formFromPreset(p) : INITIAL_FORM;
  });
  const [run, setRun] = useState<RunState | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<RunError | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [autoRerun, setAutoRerun] = useState(false);
  const [policyNotice, setPolicyNotice] = useState<number | null>(null);
  const [compare, setCompare] = useState<{ local: DecisionDetail; remote: DecisionDetail; isMock: boolean } | null>(null);
  const [comparing, setComparing] = useState(false);
  const [tab, setTab] = useState<TraceTab>('trace');
  const inflight = useRef<AbortController | null>(null);
  const resultsRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => () => inflight.current?.abort(), []);

  // ?from=dec_… prefill (id only in the URL; text is fetched, never put in the URL)
  const fromId = params.get('from');
  useEffect(() => {
    if (!fromId) return;
    let cancelled = false;
    void api
      .get<DecisionDetail>(`/api/decisions/${encodeURIComponent(fromId)}`, () => mockDecisionDetail(fromId))
      .then((r) => {
        if (cancelled) return;
        const d = r.data;
        setForm({
          ...INITIAL_FORM,
          text: d.wire?.original?.[0]?.text ?? d.preview,
          surface: d.surface,
          destination: d.destination?.dest_class ?? 'remote',
          agentId: d.identity?.agent_id ?? '',
          toolName: d.tool_name ?? '',
          toolArgs: '',
          model: d.model ?? '',
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [fromId]);

  const revealResults = () => {
    // Narrow layouts stack the result under the form: bring it into view.
    if (window.matchMedia('(max-width: 1279px)').matches) resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const execute = useCallback(
    async (req: PlaygroundRequest, label: string) => {
      inflight.current?.abort();
      const ctl = new AbortController();
      inflight.current = ctl;
      setRunning(true);
      setError(null);
      setPolicyNotice(null);
      requestAnimationFrame(revealResults);
      try {
        const { resp, isMock } = await runPlayground(req, ctl.signal);
        if (ctl.signal.aborted) return;
        const detail = detailFromPlayground(resp, req, viewer);
        const now = Date.now();
        setTab('trace');
        setRun({ key: `${now}`, label, req, resp, detail, isMock });
        setRuns((rs) =>
          [
            {
              n: now,
              at: now,
              label,
              action: detail.action,
              controlId: detail.control_id,
              score: detail.score,
              policyVersion: detail.policy_version,
              latencyMs: resp.timings?.total_ms ?? detail.latency_ms,
              isMock,
            },
            ...rs,
          ].slice(0, 10),
        );
      } catch (e) {
        if (ctl.signal.aborted && !(e instanceof TimeoutError)) return;
        setError(describeError(e, 'run'));
      } finally {
        if (inflight.current === ctl) {
          inflight.current = null;
          setRunning(false);
        }
      }
    },
    [viewer],
  );

  const onRun = () => {
    const label = presetId ? (presetById(presetId)?.label ?? 'Custom input') : 'Custom input';
    void execute(toRequest(form), label);
  };

  const onPick = (p: PlaygroundPreset) => {
    setPresetId(p.id);
    setForm(formFromPreset(p));
    setCompare(null);
  };

  const onFormChange = (f: PlaygroundFormState) => {
    if (presetId && f.text !== form.text) setPresetId(null);
    setForm(f);
  };

  const onCompare = async () => {
    setComparing(true);
    setError(null);
    try {
      const base = toRequest(form);
      const [l, r] = await Promise.all([runPlayground({ ...base, destination: 'local', send: false }), runPlayground({ ...base, destination: 'remote', send: false })]);
      setCompare({
        local: detailFromPlayground(l.resp, { ...base, destination: 'local' }, viewer),
        remote: detailFromPlayground(r.resp, { ...base, destination: 'remote' }, viewer),
        isMock: l.isMock || r.isMock,
      });
    } catch (e) {
      setError(describeError(e, 'compare'));
    } finally {
      setComparing(false);
    }
  };

  // F7: policy hot-reload → offer (or auto) re-run of the last input
  useEvents(['policy.applied'], (_n, data) => {
    if (!run) return;
    if (autoRerun) void execute(run.req, `${run.label} · re-run`);
    else setPolicyNotice(data.version);
  });

  const timings = run?.resp.timings?.controls;
  const trace = useMemo(() => (run ? buildTrace(run.detail, catalog, { timings }) : null), [run, catalog, timings]);
  const { reveal, done } = useRevealSchedule(trace, run?.key ?? null);
  const surfaceControls = useMemo(() => catalog.filter((c) => c.surfaces.includes(form.surface) && c.enabled !== false && c.mode !== 'off'), [catalog, form.surface]);

  // "Open in trace" only when the decision is indexed (A-11: playground runs are recorded)
  const indexed = useApi<DecisionDetail>(run && !run.isMock && done ? `/api/decisions/${encodeURIComponent(run.detail.id)}` : null);
  const traceLink = run && !run.isMock && indexed.data && !indexed.error ? `/security/decisions/${encodeURIComponent(run.detail.id)}` : null;

  const destClass = run ? run.detail.destination.dest_class : destClassOf(form.destination);
  const agentLabel = (run ? run.req.agent_id : form.agentId) || viewer || 'you';
  const sent = Boolean(run?.resp.response);

  return (
    <div className="min-w-0">
      <PageHeader
        title="Playground"
        icon="FlaskConical"
        subtitle="Run any prompt or tool call through the same in-line pipeline as production traffic: live controls, measured timings, current policy."
        badge={run?.isMock ? <MockBadge label="simulated" /> : undefined}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(400px,0.9fr)_minmax(0,1.3fr)]">
        <div className="min-w-0 space-y-4 xl:sticky xl:top-4 xl:self-start">
          <Panel title="Input" description="Prompt, model response, tool call or MCP message" bordered>
            <PlaygroundForm value={form} onChange={onFormChange} onRun={onRun} running={running} agents={agents} />
            <div className="mt-3 flex flex-col gap-2 border-t border-border-subtle pt-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
              <Button variant="secondary" size="sm" className="w-full sm:w-auto" onClick={() => void onCompare()} disabled={comparing || !form.text.trim()}>
                {comparing ? <Spinner className="size-3" /> : <ArrowLeftRight />} {comparing ? 'Comparing…' : 'Compare local vs remote'}
              </Button>
              <label className="inline-flex min-h-9 cursor-pointer items-center gap-2 text-xs text-text-2 sm:ml-auto" title="Re-run the last input when a new policy version is applied">
                <Switch checked={autoRerun} onCheckedChange={setAutoRerun} />
                Re-run on policy change
              </label>
            </div>
          </Panel>
          <Panel title="Presets" description="Demo scenarios. Secret-shaped values are generated at runtime, never stored." bordered>
            <PresetPicker activeId={presetId} onPick={onPick} />
          </Panel>
        </div>

        <div ref={resultsRef} className="min-w-0 scroll-mt-4 space-y-4">
          <FlowStrip action={run && done ? run.detail.action : null} dest={destClass} destName={run?.detail.destination.name ?? form.destination} agent={agentLabel} active={running} sent={sent} />

          {policyNotice !== null && run ? (
            <div role="status" className="flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm shadow-card sm:flex-row sm:items-center sm:gap-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <RefreshCw className="size-4 shrink-0 text-accent-fg" />
                <span className="text-text-2">
                  Policy <span className="font-mono text-text-1">v{policyNotice}</span> applied. Re-run the last input to check the verdict.
                </span>
              </div>
              <Button size="sm" variant="secondary" className="sm:ml-auto" onClick={() => void execute(run.req, `${run.label} · re-run`)}>
                Re-run
              </Button>
            </div>
          ) : null}

          {error ? <InlineError error={error} onRetry={() => (error.retry === 'compare' ? void onCompare() : onRun())} onDismiss={() => setError(null)} /> : null}

          {compare ? (
            <Panel
              title="Same input, two destinations"
              description="Minimization is destination-aware: PII may stay on a local model but is tokenized before it leaves"
              isMock={compare.isMock}
              bordered
              actions={
                <Button variant="ghost" size="xs" onClick={() => setCompare(null)}>
                  Close
                </Button>
              }
            >
              <div className="grid divide-y divide-border-subtle md:grid-cols-2 md:divide-x md:divide-y-0">
                <CompareColumn title="Local · ollama" detail={compare.local} />
                <CompareColumn title="Remote · anthropic" detail={compare.remote} />
              </div>
            </Panel>
          ) : null}

          {running && !run ? (
            <Panel title="Evaluating" bordered>
              <ScanningControls controls={surfaceControls} />
            </Panel>
          ) : null}

          {run ? (
            <>
              {done ? (
                <VerdictHero
                  action={run.detail.action}
                  controlId={run.detail.control_id ?? (run.detail.action === 'allow' ? (closestCall(run.detail.decisions)?.control_id ?? null) : null)}
                  reason={run.detail.reason}
                  score={run.detail.score}
                  threshold={run.detail.threshold}
                  policyVersion={run.detail.policy_version}
                  feedSerial={run.detail.feed_serial}
                  totalMs={run.resp.timings?.total_ms ?? run.detail.latency_ms}
                  redactions={run.detail.redaction_count}
                  isMock={run.isMock}
                />
              ) : (
                <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-3 text-xs text-text-2 shadow-card" role="status">
                  <Spinner /> Replaying pipeline stages
                </div>
              )}
              {done && run.detail.redaction_count > 0 ? (
                <Panel title="On the wire" description="What the destination receives; hover a placeholder for its original" isMock={run.isMock} bordered>
                  <RedactionDiff wire={run.detail.wire} redactions={run.detail.redactions} destination={run.detail.destination} latencyMs={run.detail.latency_ms} animate />
                </Panel>
              ) : null}
              <Panel
                title="Decision trace"
                description={running ? 'Running again…' : 'Per-control findings; measured timings, replayed 25× slower'}
                isMock={run.isMock}
                bordered
                actions={
                  traceLink ? (
                    <Button asChild variant="ghost" size="xs">
                      <Link to={traceLink}>
                        <ExternalLink /> Open decision
                      </Link>
                    </Button>
                  ) : null
                }
              >
                <div className={running ? 'pointer-events-none min-w-0 opacity-50 transition-opacity duration-150' : 'min-w-0 transition-opacity duration-150'}>
                  <DecisionTrace detail={run.detail} catalog={catalog} current={current} tab={tab} onTabChange={setTab} reveal={reveal} animate timings={timings} />
                </div>
              </Panel>
            </>
          ) : !running ? (
            <Panel>
              <EmptyState icon="FlaskConical" title="No runs yet" hint="Choose a preset or enter your own input, then select Run (⌘↵)." />
            </Panel>
          ) : null}

          {runs.length ? (
            <Panel title="Run history" description="This session only. Inputs are kept in memory, never stored." bordered flush>
              <RunHistory runs={runs} />
            </Panel>
          ) : null}
        </div>
      </div>
    </div>
  );
}
