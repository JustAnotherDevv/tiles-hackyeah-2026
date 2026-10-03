// /security/playground — "Try to break it": run any prompt / tool call through the real pipeline
// (POST /api/playground), watch each stage animate (paced by real timings), see the verdict and the Wire diff.
import { motion } from 'framer-motion';
import { ArrowLeftRight, ExternalLink, RefreshCw, ShieldAlert } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, isApiRequestError } from '@/api/client';
import { useApi, useEvents, useViewerId } from '@/api/hooks';
import type { DecisionDetail, PlaygroundRequest, PlaygroundResponse } from '@/api/types';
import { ActionBadge, EmptyState, MockBadge, PageHeader, Panel } from '@/components/shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
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
import { FlowStrip, RunHistory, ScanningControls, useRevealSchedule, VerdictHero, type RunRecord } from '@/components/security/playground/visuals';
import { RedactionDiff } from '@/components/security/redaction';
import type { PlaygroundPreset } from '@/components/security/types';
import { mockDecisionDetail, mockPlayground } from '@/mocks/security';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/security/playground',
  title: 'Playground',
  icon: 'FlaskConical',
  section: 'Security',
  order: 20,
  shortcut: 'g y',
  description: 'Try to break it — run any prompt or tool call through the live pipeline',
};

interface RunState {
  key: string;
  label: string;
  req: PlaygroundRequest;
  resp: PlaygroundResponse;
  detail: DecisionDetail;
  isMock: boolean;
}

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

async function runPlayground(req: PlaygroundRequest): Promise<{ resp: PlaygroundResponse; isMock: boolean }> {
  const r = await api.post<PlaygroundResponse>('/api/playground', req, () => mockPlayground(req));
  return { resp: r.data, isMock: r.isMock };
}

function CompareCard({ title, detail }: { title: string; detail: DecisionDetail }) {
  const out = detail.wire?.outbound?.[0]?.text ?? detail.preview;
  return (
    <div className="min-w-0 rounded-lg border border-border bg-surface-1 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-medium text-text-1">{title}</span>
        <ActionBadge action={detail.action} size="sm" />
        {detail.control_id ? <ControlChip id={detail.control_id} /> : null}
        <span className="ml-auto text-2xs text-text-3">{detail.redaction_count} redactions</span>
      </div>
      <div className="whitespace-pre-wrap break-words rounded-md bg-background px-2.5 py-2">
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
  const [error, setError] = useState<{ title: string; message: string } | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [autoRerun, setAutoRerun] = useState(false);
  const [policyNotice, setPolicyNotice] = useState<number | null>(null);
  const [compare, setCompare] = useState<{ local: DecisionDetail; remote: DecisionDetail; isMock: boolean } | null>(null);
  const [comparing, setComparing] = useState(false);
  const [tab, setTab] = useState<TraceTab>('trace');

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

  const execute = useCallback(
    async (req: PlaygroundRequest, label: string) => {
      setRunning(true);
      setError(null);
      setPolicyNotice(null);
      try {
        const { resp, isMock } = await runPlayground(req);
        const detail = detailFromPlayground(resp, req, viewer);
        const key = `${Date.now()}`;
        setTab('trace');
        setRun({ key, label, req, resp, detail, isMock });
        setRuns((rs) =>
          [
            { n: Date.now(), at: Date.now(), label, action: detail.action, controlId: detail.control_id, score: detail.score, policyVersion: detail.policy_version, isMock },
            ...rs,
          ].slice(0, 10),
        );
      } catch (e) {
        if (isApiRequestError(e)) setError({ title: `${e.status} · ${e.type}`, message: e.message });
        else setError({ title: 'Request failed', message: e instanceof Error ? e.message : String(e) });
      } finally {
        setRunning(false);
      }
    },
    [viewer],
  );

  const onRun = () => {
    const label = presetId ? (presetById(presetId)?.label ?? 'custom') : 'custom';
    void execute(toRequest(form), label);
  };

  const onPick = (p: PlaygroundPreset) => {
    setPresetId(p.id);
    setForm(formFromPreset(p));
    setCompare(null);
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
      setError({ title: 'Compare failed', message: e instanceof Error ? e.message : String(e) });
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
    <div>
      <PageHeader
        title="Playground"
        icon="FlaskConical"
        subtitle="Try to break it. Every run goes through the same in-line pipeline as production traffic — real controls, real timings, real policy."
        badge={run?.isMock ? <MockBadge label="simulated" /> : undefined}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(380px,0.9fr)_minmax(0,1.3fr)]">
        <div className="space-y-4 xl:sticky xl:top-4 xl:self-start">
          <Panel title="Input" description="Prompt, model response, tool call or MCP message">
            <PlaygroundForm value={form} onChange={setForm} onRun={onRun} running={running} agents={agents} />
            <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-border-subtle pt-3">
              <Button variant="secondary" size="sm" onClick={() => void onCompare()} disabled={comparing || !form.text.trim()}>
                <ArrowLeftRight /> {comparing ? 'Comparing…' : 'Compare local vs remote'}
              </Button>
              <label className="ml-auto inline-flex cursor-pointer items-center gap-2 text-xs text-text-2" title="Re-run the last input when a new policy version is applied">
                <Switch checked={autoRerun} onCheckedChange={setAutoRerun} />
                Auto re-run on policy change
              </label>
            </div>
          </Panel>
          <Panel title="Presets" description="One click per demo scene — secret-shaped values are generated, never stored">
            <PresetPicker activeId={presetId} onPick={onPick} />
          </Panel>
        </div>

        <div className="min-w-0 space-y-4">
          <FlowStrip action={run && done ? run.detail.action : null} dest={destClass} destName={run?.detail.destination.name ?? form.destination} agent={agentLabel} active={running || Boolean(run)} sent={sent} />
          <RunHistory runs={runs} />
          {policyNotice !== null && run ? (
            <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} className="flex items-center gap-3 rounded-lg border border-accent-fg/40 bg-brand/10 px-3.5 py-2.5 text-sm">
              <RefreshCw className="size-4 text-accent-fg" />
              <span>
                Policy <b>v{policyNotice}</b> applied — re-run the last input to see if the verdict flips?
              </span>
              <Button size="sm" className="ml-auto" onClick={() => void execute(run.req, `${run.label} · re-run`)}>
                Re-run
              </Button>
            </motion.div>
          ) : null}
          {error ? (
            <Alert variant="destructive">
              <ShieldAlert />
              <AlertTitle>{error.title}</AlertTitle>
              <AlertDescription>{error.message}</AlertDescription>
            </Alert>
          ) : null}
          {compare ? (
            <Panel title="Same input, two destinations" description="Data minimization is destination-aware: PII may stay on a local model, never leaves for a remote one" isMock={compare.isMock} actions={<Button variant="ghost" size="xs" onClick={() => setCompare(null)}>Close</Button>}>
              <div className="grid gap-3 md:grid-cols-2">
                <CompareCard title="Local · ollama" detail={compare.local} />
                <CompareCard title="Remote · anthropic" detail={compare.remote} />
              </div>
            </Panel>
          ) : null}

          {running && !run ? (
            <Panel title="Pipeline">
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
                  isMock={run.isMock}
                />
              ) : null}
              {done && run.detail.redaction_count > 0 ? (
                <Panel title="On the wire" description="What the destination actually receives — hover a placeholder to find its original" isMock={run.isMock}>
                  <RedactionDiff wire={run.detail.wire} redactions={run.detail.redactions} destination={run.detail.destination} latencyMs={run.detail.latency_ms} animate />
                </Panel>
              ) : null}
              <Panel
                title="Decision trace"
                description={running ? 'Re-running…' : 'Each stage paced by its measured latency (slowed ~25× so you can see it)'}
                isMock={run.isMock}
                actions={
                  traceLink ? (
                    <Button asChild variant="ghost" size="xs">
                      <Link to={traceLink}>
                        <ExternalLink /> Open in trace
                      </Link>
                    </Button>
                  ) : null
                }
              >
                <div className={running ? 'pointer-events-none opacity-50 transition-opacity' : 'transition-opacity'}>
                  <DecisionTrace detail={run.detail} catalog={catalog} current={current} tab={tab} onTabChange={setTab} reveal={reveal} animate timings={timings} />
                </div>
              </Panel>
            </>
          ) : !running ? (
            <Panel>
              <EmptyState
                icon="FlaskConical"
                title="Pick a preset or type anything, then press Run"
                hint="Try the PII preset against Remote, then switch the destination to Local — or paste your own jailbreak."
              />
            </Panel>
          ) : null}
        </div>
      </div>
    </div>
  );
}
