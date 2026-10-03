// Policy editor state machine (UIG-04): active policy ↔ draft, debounced validate + diff with a
// latest-request-wins counter, role-aware apply with every ApplyResult status, live reloads from
// elsewhere (clean draft → reload + flash changed lines; dirty → rebase banner), policy.rejected
// banner. Owner: B19-dashboard-gov-policy.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { isApiRequestError } from '@/api/client';
import { useApi, useEvents } from '@/api/hooks';
import { eventHub } from '@/api/sse';
import type { ApplyResult, ApprovalRequest, ApproverLevel, PolicyDiffResponse, PolicyResponse, SseEventMap, ValidationIssue, ValidationReport } from '@/api/types';
import { errorTitle, parseApiError } from '@/components/governance/gov-api';
import { useViewer, useWhoAmI } from '@/components/governance/hooks';
import { roleSatisfies } from '@/components/governance/lib/eligibility';
import { routeChanges } from './config-route';
import type { PolicyEditorHandle } from './editor-types';
import { changedLines } from './line-ops';
import { policyApi, policyMocks, policyPaths, useMockStoreRefresh, type MockViewer } from './policy-api';
import { announcePolicyApplied, toastApplyResult } from './policy-toast';

export type StepState = 'idle' | 'run' | 'ok' | 'fail' | 'skip';
export interface ApplySteps {
  parse: StepState;
  validate: StepState;
  selftest: StepState;
  swap: StepState;
  swapMs: number | null;
  selftestText: string | null;
}

const IDLE_STEPS: ApplySteps = { parse: 'idle', validate: 'idle', selftest: 'idle', swap: 'idle', swapMs: null, selftestText: null };

function issueFromError(e: unknown): ValidationIssue {
  const p = parseApiError(e);
  const m = /line (\d+)(?:,? col(?:umn)? (\d+))?/i.exec(p.message);
  return { path: '', line: m ? Number(m[1]) : null, col: m?.[2] ? Number(m[2]) : null, message: p.message, severity: 'error' };
}

function stepsForRejection(errors: ValidationIssue[]): ApplySteps {
  const text = errors.map((e) => e.message).join(' ').toLowerCase();
  if (/self-test|selftest|expected \w+, got/.test(text)) {
    const n = errors.filter((e) => /self-test|expected \w+, got/i.test(e.message)).length;
    return { parse: 'ok', validate: 'ok', selftest: 'fail', swap: 'skip', swapMs: null, selftestText: `${n} failing` };
  }
  if (/yaml|indent|token|mapping|expected|could not find|tab|scanner|parser|flow/.test(text) && errors.some((e) => e.line)) {
    return { parse: 'fail', validate: 'skip', selftest: 'skip', swap: 'skip', swapMs: null, selftestText: null };
  }
  return { parse: 'ok', validate: 'fail', selftest: 'skip', swap: 'skip', swapMs: null, selftestText: null };
}

export interface RebaseInfo {
  from: number;
  to: number;
  source: string;
}

export function usePolicyDraft() {
  const { viewerId, role, member } = useViewer();
  const who = useWhoAmI();
  const viewer: MockViewer = useMemo(() => ({ id: viewerId, role }), [viewerId, role]);

  const active = useApi<PolicyResponse>(policyPaths.policy, { mock: policyMocks.policy, refreshOn: ['policy.applied'], refreshMs: 15000 });
  useMockStoreRefresh(active.refresh, active.isMock);

  const [base, setBase] = useState<{ version: number; yaml: string } | null>(null);
  const [draft, setDraftState] = useState<string | null>(null);
  const draftRef = useRef<string | null>(null);
  const handle = useRef<PolicyEditorHandle | null>(null);
  const [engine, setEngine] = useState<'monaco' | 'plain' | null>(null);

  const [report, setReport] = useState<ValidationReport | null>(null);
  const [diff, setDiff] = useState<PolicyDiffResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<ValidationIssue | null>(null);
  const [checkMock, setCheckMock] = useState(false);
  const seq = useRef(0);

  const [applying, setApplying] = useState(false);
  const [steps, setSteps] = useState<ApplySteps>(IDLE_STEPS);
  const [applyErrors, setApplyErrors] = useState<ValidationIssue[]>([]);
  const [lastResult, setLastResult] = useState<ApplyResult | null>(null);
  const [pending, setPending] = useState<ApprovalRequest | null>(null);
  const [rebase, setRebase] = useState<RebaseInfo | null>(null);
  const [rejected, setRejected] = useState<SseEventMap['policy.rejected'] | null>(null);
  const [externalFlash, setExternalFlash] = useState<{ version: number; lines: number } | null>(null);

  const setDraft = useCallback((text: string) => {
    draftRef.current = text;
    setDraftState(text);
  }, []);

  // ------------------------------------------------------------ active policy changes
  const a = active.data;
  useEffect(() => {
    if (!a) return;
    if (base === null) {
      setBase({ version: a.version, yaml: a.yaml });
      setDraft(a.yaml);
      return;
    }
    if (a.version === base.version && a.yaml === base.yaml) return;
    const cur = draftRef.current ?? base.yaml;
    if (cur === a.yaml) {
      // our own apply (or identical content) — just move the base
      setBase({ version: a.version, yaml: a.yaml });
      setRebase(null);
      return;
    }
    if (cur === base.yaml) {
      // clean editor: load the new active policy and flash what changed
      const lines = changedLines(base.yaml, a.yaml);
      setBase({ version: a.version, yaml: a.yaml });
      setDraft(a.yaml);
      handle.current?.setValue(a.yaml, { flashLines: lines, reveal: lines[0] });
      setExternalFlash({ version: a.version, lines: lines.length });
      setRebase(null);
      setRejected(null);
      return;
    }
    if (a.version !== base.version) setRebase({ from: base.version, to: a.version, source: a.source });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a?.version, a?.yaml]);

  useEvents(['policy.rejected'], (_n, payload) => setRejected(payload as SseEventMap['policy.rejected']));
  useEvents(['policy.applied'], () => setRejected(null));

  // ------------------------------------------------------------ debounced validate + diff
  const dirty = draft !== null && base !== null && draft !== base.yaml;
  useEffect(() => {
    if (draft === null || base === null) return;
    const my = ++seq.current;
    if (draft === base.yaml) {
      setReport(null);
      setDiff(null);
      setChecking(false);
      setCheckError(null);
      return;
    }
    setChecking(true);
    const t = window.setTimeout(async () => {
      const [v, d] = await Promise.allSettled([policyApi.validate(draft, false, base.yaml), policyApi.diff(draft, base.yaml)]);
      if (my !== seq.current) return;
      if (v.status === 'fulfilled') {
        setReport(v.value.data);
        setCheckMock(v.value.isMock);
        setCheckError(null);
      } else {
        setReport(null);
        setCheckError(issueFromError(v.reason));
      }
      if (d.status === 'fulfilled') setDiff(d.value.data);
      else setDiff(null);
      setChecking(false);
    }, 600);
    return () => window.clearTimeout(t);
  }, [draft, base]);

  // ------------------------------------------------------------ derived
  const issues: ValidationIssue[] = useMemo(() => {
    const out = [...(report?.errors ?? []), ...(report?.warnings ?? [])];
    if (checkError) out.push(checkError);
    for (const e of applyErrors) if (!out.some((o) => o.line === e.line && o.message === e.message)) out.push(e);
    return out;
  }, [report, checkError, applyErrors]);

  const changes = useMemo(() => diff?.changes ?? report?.changes ?? [], [diff, report]);
  const serverRole: ApproverLevel | null = diff?.required_role ?? report?.required_role ?? null;
  const estimate = useMemo(() => routeChanges(changes), [changes]);
  const requiredRole: ApproverLevel | null = serverRole ?? estimate?.level ?? (dirty ? 'owner' : null);
  const ruleId = (diff as (PolicyDiffResponse & { rule_id?: string | null }) | null)?.rule_id ?? estimate?.rule_id ?? null;
  const canApply = who.data?.permissions?.can_apply_policy ?? (role === 'member' ? 'approval' : 'yes');
  const roleOk = requiredRole ? roleSatisfies(role, requiredRole) : true;
  const changed = useMemo(() => (dirty && base && draft !== null ? changedLines(base.yaml, draft) : []), [dirty, base, draft]);
  const valid = !checking && !checkError && (report ? report.valid : true);

  // ------------------------------------------------------------ actions
  const replaceDraft = useCallback((text: string, opts: { reveal?: number; flash?: boolean } = {}) => {
    setDraft(text);
    if (handle.current) handle.current.setValue(text, { reveal: opts.reveal, flashLines: opts.flash && opts.reveal ? [opts.reveal] : undefined });
  }, [setDraft]);

  const handleResult = useCallback(
    (r: ApplyResult, isMock: boolean, what: string, appliedYaml: string | null) => {
      setLastResult(r);
      switch (r.status) {
        case 'applied': {
          setSteps({ parse: 'ok', validate: 'ok', selftest: 'ok', swap: 'ok', swapMs: r.latency_ms, selftestText: report?.selftest?.length ? `${report.selftest.filter((x) => x.passed).length}/${report.selftest.length}` : null });
          setApplyErrors([]);
          setPending(null);
          setRebase(null);
          setRejected(null);
          if (r.version !== null && appliedYaml !== null) setBase({ version: r.version, yaml: appliedYaml });
          if (appliedYaml !== null && draftRef.current !== appliedYaml) replaceDraft(appliedYaml);
          if (r.version !== null) {
            void announcePolicyApplied(
              { version: r.version, previous_version: r.previous_version, source: 'api', actor: member ? { org_id: member.org_id, team_id: member.team_id, member_id: member.id, agent_id: null, role: member.role, display_name: member.name } : null, changes: r.changes ?? changes, latency_ms: r.latency_ms },
              { mock: isMock, force: eventHub.status !== 'live' },
            );
          }
          active.refresh();
          break;
        }
        case 'pending_approval':
          setSteps({ ...IDLE_STEPS, parse: 'ok', validate: 'ok' });
          setPending(r.approval);
          toastApplyResult(r, { what });
          break;
        case 'rejected':
          setApplyErrors(r.errors ?? []);
          setSteps(stepsForRejection(r.errors ?? []));
          toastApplyResult({ ...r, message: r.message || `Rejected — still on v${base?.version ?? '?'}` }, { what });
          {
            const first = (r.errors ?? []).find((e) => e.line);
            if (first?.line) handle.current?.revealLine(first.line);
          }
          break;
        case 'conflict':
          setSteps(IDLE_STEPS);
          setRebase({ from: base?.version ?? 0, to: r.version ?? (base?.version ?? 0) + 1, source: 'api' });
          toastApplyResult(r, { what });
          active.refresh();
          break;
        case 'noop':
          setSteps(IDLE_STEPS);
          toastApplyResult(r, { what });
          break;
      }
    },
    [active, base, changes, member, replaceDraft, report],
  );

  const apply = useCallback(
    async (reason: string) => {
      const text = draftRef.current;
      if (!base || text === null || applying) return;
      setApplying(true);
      setSteps({ ...IDLE_STEPS, parse: 'run' });
      try {
        const r = await policyApi.apply({ yaml: text, base_version: base.version, reason: reason || null }, viewer);
        handleResult(r.data, r.isMock, 'Policy change', text);
      } catch (e) {
        setSteps(IDLE_STEPS);
        if (isApiRequestError(e) && e.status === 409) {
          setRebase({ from: base.version, to: base.version + 1, source: 'api' });
          active.refresh();
          toast.warning('Policy moved on — rebase your draft', { description: e.message });
        } else {
          const p = parseApiError(e);
          toast.error(errorTitle(p), { description: p.message });
        }
      } finally {
        setApplying(false);
      }
    },
    [active, applying, base, handleResult, viewer],
  );

  const rollback = useCallback(
    async (version: number, reason: string) => {
      try {
        const r = await policyApi.rollback({ version, reason: reason || null }, viewer);
        let yaml: string | null = null;
        if (r.data.status === 'applied') {
          try {
            yaml = (await policyApi.version(version)).data.yaml;
          } catch {
            yaml = null;
          }
        }
        handleResult(r.data, r.isMock, `Rollback to v${version}`, yaml);
        if (r.data.status === 'applied' && yaml === null) active.refresh();
      } catch (e) {
        const p = parseApiError(e);
        toast.error(errorTitle(p), { description: p.message });
      }
    },
    [active, handleResult, viewer],
  );

  const doRebase = useCallback(() => {
    if (!a) return;
    setBase({ version: a.version, yaml: a.yaml });
    setRebase(null);
  }, [a]);

  const discard = useCallback(() => {
    if (!a) return;
    setBase({ version: a.version, yaml: a.yaml });
    replaceDraft(a.yaml);
    setRebase(null);
    setPending(null);
    setApplyErrors([]);
    setSteps(IDLE_STEPS);
  }, [a, replaceDraft]);

  return {
    viewer,
    role,
    member,
    who,
    active,
    base,
    draft,
    setDraft: (t: string) => {
      setDraft(t);
      if (applyErrors.length) setApplyErrors([]);
    },
    replaceDraft,
    handle,
    engine,
    setEngine,
    dirty,
    checking,
    checkMock,
    report,
    diff,
    issues,
    changes,
    changedLines: changed,
    requiredRole,
    requiredRoleIsEstimate: serverRole === null && requiredRole !== null,
    ruleId,
    canApply,
    roleOk,
    valid,
    applying,
    steps,
    lastResult,
    pending,
    rebase,
    rejected,
    externalFlash,
    apply,
    rollback,
    doRebase,
    discard,
    dismissRejected: () => setRejected(null),
    dismissPending: () => setPending(null),
  };
}

export type PolicyDraft = ReturnType<typeof usePolicyDraft>;
