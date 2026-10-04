// "Who would approve this?" (UIG-07): build a hypothetical request (or pick a SCENARIOS preset),
// POST /api/approvals/simulate (+ Addendum A-28 extras: labels, scope_type, increase_pct,
// control_id, changes) and show the level, matched rule (highlighted in the tables), TTL,
// two-person and the eligible approvers (client-side, contract eligibility). Owner: B18.
import { motion } from 'framer-motion';
import { Ban, Loader2, Route, ShieldCheck, Users, Zap } from '@/components/icons';
import { useEffect, useMemo, useState } from 'react';
import type { ApprovalKind, ApprovalRequest, ApprovalRoute, PolicyChange } from '@/api/types';
import { Slider } from '@/components/ui/slider';
import { cn } from '@/lib/utils';
import { ApproverBadge } from '../ApproverBadge';
import { errorTitle, govApi, parseApiError, type ApprovalSimulateRequestExt } from '../gov-api';
import type { Directory } from '../hooks';
import { canVote, eligibleApprovers } from '../lib/eligibility';
import { firstName, fmtMoney, fmtTtl, levelLabel } from '../lib/format-gov';
import type { Viewer } from '../lib/eligibility';
import { MemberAvatar } from '../MemberAvatar';

interface SimForm {
  kind: ApprovalKind;
  action_type: string;
  amount: number;
  resource: string;
  env: string;
  data_class: string;
  scope_type: string;
  increase_pct: number;
  control_id: string;
  requester: string; // member id or agent id
}

const ACTION_TYPES = [
  'spend.subscription',
  'spend.purchase',
  'db.read',
  'db.write',
  'db.schema',
  'email.external',
  'email.internal',
  'egress.post',
  'code.exec',
  'code.deploy',
  'package.install',
  'org.role.promote_admin',
  'org.agent.update',
];
const CONFIG_KINDS = [
  'budget.raise',
  'control.disable',
  'control.enable',
  'control.mode',
  'killswitch.on',
  'killswitch.off',
  'model.allow',
  'profile.change',
  'approval.rule',
  'control.params',
];
const TABLES = ['db:customers', 'db:payment_cards', 'db:trades', 'db:positions', 'db:research_notes', 'db:market_prices'];
const CONTROLS = ['DLP-01', 'DLP-02', 'INJ-01', 'INJ-02', 'EXE-01', 'ACT-01', 'BUD-01'];

const BASE: SimForm = {
  kind: 'action',
  action_type: 'spend.subscription',
  amount: 50,
  resource: 'vendor:marketpulse',
  env: 'prod',
  data_class: 'CONFIDENTIAL',
  scope_type: 'team',
  increase_pct: 25,
  control_id: 'DLP-02',
  requester: 'trading-copilot@trading',
};

const PRESETS: { label: string; expect: string; form: Partial<SimForm> }[] = [
  {
    label: '$12 research-agent',
    expect: 'self',
    form: {
      action_type: 'spend.subscription',
      amount: 12,
      resource: 'vendor:opendata',
      requester: 'research-agent@research',
    },
  },
  {
    label: '$50 trading-copilot',
    expect: 'admin',
    form: {
      action_type: 'spend.subscription',
      amount: 50,
      resource: 'vendor:marketpulse',
      requester: 'trading-copilot@trading',
    },
  },
  {
    label: '$480 claude-code',
    expect: 'owner',
    form: {
      action_type: 'spend.purchase',
      amount: 480,
      resource: 'vendor:gpucloud',
      requester: 'claude-code@platform',
    },
  },
  {
    label: '$1,500 purchase',
    expect: 'owner · 2p',
    form: {
      action_type: 'spend.purchase',
      amount: 1500,
      resource: 'vendor:gpucloud',
      requester: 'trading-copilot@trading',
    },
  },
  {
    label: 'read db:customers',
    expect: 'admin',
    form: {
      action_type: 'db.read',
      resource: 'db:customers',
      requester: 'research-agent@research',
    },
  },
  {
    label: 'read db:payment_cards',
    expect: 'deny',
    form: {
      action_type: 'db.read',
      resource: 'db:payment_cards',
      requester: 'trading-copilot@trading',
    },
  },
  {
    label: 'prod DELETE',
    expect: 'owner',
    form: {
      action_type: 'db.write',
      resource: 'db:trades',
      env: 'prod',
      requester: 'claude-code@platform',
    },
  },
  {
    label: 'team:trading +25%',
    expect: 'admin',
    form: {
      kind: 'config_change',
      action_type: 'budget.raise',
      scope_type: 'team',
      increase_pct: 25,
      requester: 'u_piotr',
    },
  },
  {
    label: 'team:trading +150%',
    expect: 'owner',
    form: {
      kind: 'config_change',
      action_type: 'budget.raise',
      scope_type: 'team',
      increase_pct: 150,
      requester: 'u_piotr',
    },
  },
  {
    label: 'disable DLP-02',
    expect: 'owner',
    form: {
      kind: 'config_change',
      action_type: 'control.disable',
      control_id: 'DLP-02',
      requester: 'u_marek',
    },
  },
];

const CRITICAL = new Set(['DLP-02', 'EXE-01', 'SIG-01', 'SIG-02']);
const LOOSENING = new Set(['control.disable', 'control.mode', 'budget.raise', 'killswitch.off', 'model.allow', 'profile.change']);

function buildRequest(f: SimForm, dir: Directory): ApprovalSimulateRequestExt {
  const agent = dir.agentById.get(f.requester);
  const base: ApprovalSimulateRequestExt = {
    kind: f.kind,
    action_type: f.action_type,
    requester_agent_id: agent ? agent.id : null,
    requester_member_id: agent ? agent.owner_member_id : f.requester,
  };
  if (f.kind === 'config_change') {
    const scope =
      f.action_type === 'budget.raise'
        ? `${f.scope_type}:${f.scope_type === 'org' ? 'acme-capital' : f.scope_type === 'team' ? 'trading' : 'trading-copilot@trading'}`
        : f.action_type.startsWith('killswitch')
          ? 'agent:chaos-agent@platform'
          : null;
    const control = f.action_type.startsWith('control.') ? f.control_id : null;
    const change: PolicyChange = {
      kind: f.action_type,
      path: control ? `controls[id=${control}].enabled` : scope ? `budgets.limits[scope=${scope}]` : f.action_type,
      before: null,
      after: null,
      control_id: control,
      scope,
      dimension: f.action_type === 'budget.raise' ? 'usd' : null,
      increase_pct: f.action_type === 'budget.raise' ? f.increase_pct : null,
      loosening: LOOSENING.has(f.action_type),
      summary: `${f.action_type}${control ? ` ${control}` : ''}${scope ? ` ${scope}` : ''}`,
    };
    return {
      ...base,
      resource: scope,
      scope_type: f.action_type === 'budget.raise' ? f.scope_type : scope ? scope.split(':')[0] : null,
      increase_pct: change.increase_pct,
      control_id: control,
      loosening: change.loosening,
      labels: control && CRITICAL.has(control) ? { control_severity: 'critical' } : {},
      changes: [change],
    };
  }
  const labels: Record<string, string> = {};
  if (f.action_type === 'db.write' || f.action_type === 'db.schema' || f.action_type === 'code.deploy') labels.env = f.env;
  if (f.action_type === 'email.external' || f.action_type === 'egress.post') labels.data_class = f.data_class;
  return {
    ...base,
    amount_usd: f.action_type.startsWith('spend.') ? f.amount : null,
    resource: f.action_type.startsWith('db.') || f.action_type.startsWith('spend.') ? f.resource || null : null,
    labels,
  };
}

const FIELD =
  'h-9 w-full rounded-md border border-border bg-surface-1 px-2.5 text-[12.5px] text-text-1 outline-none hover:border-border-strong focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40';
const LABEL = 'mb-1 block text-2xs font-medium uppercase tracking-wider text-text-3';

export function RouteSimulator({ dir, viewer, onRoute }: { dir: Directory; viewer: Viewer; onRoute: (route: (ApprovalRoute & { description?: string | null }) | null) => void }) {
  const [form, setForm] = useState<SimForm>({ ...BASE });
  const [preset, setPreset] = useState<string | null>(PRESETS[1].label);
  const [result, setResult] = useState<(ApprovalRoute & { description?: string | null; isMock?: boolean }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const req = useMemo(() => buildRequest(form, dir), [form, dir]);
  const reqKey = JSON.stringify(req);

  // live: re-simulate (debounced) whenever the form changes
  useEffect(() => {
    let alive = true;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await govApi.simulate(JSON.parse(reqKey) as ApprovalSimulateRequestExt, viewer.member_id);
        if (!alive) return;
        const r = {
          ...(res.data as ApprovalRoute & { description?: string | null }),
          isMock: res.isMock,
        };
        setResult(r);
        setError(null);
        onRoute(r);
      } catch (e) {
        if (!alive) return;
        const p = parseApiError(e);
        setError(`${errorTitle(p)} — ${p.message}`);
        setResult(null);
        onRoute(null);
      } finally {
        if (alive) setLoading(false);
      }
    }, 220);
    return () => {
      alive = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reqKey, viewer.member_id]);

  const set = (patch: Partial<SimForm>) => {
    setPreset(null);
    setForm((f) => ({ ...f, ...patch }));
  };
  const applyPreset = (p: (typeof PRESETS)[number]) => {
    setPreset(p.label);
    setForm({ ...BASE, kind: 'action', ...p.form });
  };

  // eligible approvers for a synthetic request (contract eligibility, SoD for the sponsor)
  const synthetic: ApprovalRequest | null = result
    ? {
        id: 'apr_sim',
        org_id: 'acme-capital',
        team_id: null,
        kind: form.kind,
        action_type: form.action_type,
        title: 'simulation',
        summary: null,
        requester: {
          org_id: 'acme-capital',
          team_id: null,
          member_id: req.requester_member_id ?? null,
          agent_id: req.requester_agent_id ?? null,
          role: req.requester_agent_id ? 'agent' : (dir.memberById.get(req.requester_member_id ?? '')?.role ?? 'member'),
          display_name: null,
          authenticated: true,
        },
        amount_usd: req.amount_usd ?? null,
        resource: req.resource ?? null,
        labels: {},
        payload: {},
        fingerprint: 'fp_sim',
        required_role: result.required_role,
        two_person: result.two_person,
        rule_id: result.rule_id,
        votes: [],
        status: 'pending',
        created_at: '1970-01-01T00:00:00Z',
        expires_at: null,
        decided_at: null,
        decided_by: [],
        request_id: null,
        decision_id: null,
        control_id: null,
        uses: 0,
        max_uses: result.max_uses,
        execution: null,
      }
    : null;
  const sponsorId = req.requester_agent_id ? req.requester_member_id : null;
  const eligible = synthetic && result && result.required_role !== 'auto' && result.required_role !== 'deny' ? eligibleApprovers(synthetic, dir.members, { sponsorId }) : [];
  const viewerCheck = synthetic ? canVote(viewer, synthetic, 0, { sponsorId }) : null;
  const requesterName = dir.nameOf(form.requester);
  const isSpend = form.kind === 'action' && form.action_type.startsWith('spend.');
  const isDb = form.kind === 'action' && form.action_type.startsWith('db.');

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <div className="space-y-3.5">
        <div>
          <span className={LABEL}>Presets</span>
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => applyPreset(p)}
                className={cn(
                  'inline-flex h-9 items-center gap-1.5 rounded-md border px-2 text-xs transition-colors sm:h-7',
                  preset === p.label ? 'border-approval/50 bg-approval/10 text-text-1' : 'border-border bg-surface-1 text-text-2 hover:border-border-strong hover:text-text-1',
                )}
              >
                {p.label}
                <span className="font-mono text-2xs text-text-3">→ {p.expect}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label>
            <span className={LABEL}>Kind</span>
            <select
              className={FIELD}
              value={form.kind}
              onChange={(e) => {
                const kind = e.target.value as ApprovalKind;
                set({
                  kind,
                  action_type: kind === 'config_change' ? 'budget.raise' : kind === 'budget_raise' ? 'budget.override' : kind === 'mcp_pin' ? 'mcp.repin' : 'spend.subscription',
                });
              }}
            >
              <option value="action">Agent action</option>
              <option value="config_change">Config change</option>
              <option value="budget_raise">Budget override (hard limit hit)</option>
              <option value="mcp_pin">MCP tool re-pin</option>
            </select>
          </label>
          <label>
            <span className={LABEL}>{form.kind === 'config_change' ? 'Change kind' : 'Action type'}</span>
            <select
              className={cn(FIELD, 'font-mono')}
              value={form.action_type}
              onChange={(e) => set({ action_type: e.target.value })}
              disabled={form.kind === 'budget_raise' || form.kind === 'mcp_pin'}
            >
              {(form.kind === 'config_change' ? CONFIG_KINDS : form.kind === 'action' ? ACTION_TYPES : [form.action_type]).map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
        </div>

        {isSpend ? (
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_180px]">
            <div>
              <span className={LABEL}>
                Amount <span className="ml-1 font-mono normal-case tracking-normal text-text-1">{fmtMoney(form.amount, { whole: true })}</span>
              </span>
              <Slider className="mt-3" min={0} max={2000} step={1} value={[form.amount]} onValueChange={(v) => set({ amount: v[0] ?? 0 })} aria-label="Amount in USD" />
              <div className="mt-1.5 flex justify-between text-2xs tabular text-text-4">
                <span>$0</span>
                <span>$20</span>
                <span>$200</span>
                <span>$1,000</span>
                <span>$2,000</span>
              </div>
            </div>
            <label>
              <span className={LABEL}>Vendor</span>
              <select className={cn(FIELD, 'font-mono')} value={form.resource} onChange={(e) => set({ resource: e.target.value })}>
                {['vendor:marketpulse', 'vendor:opendata', 'vendor:gpucloud', 'vendor:unknown'].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
          </div>
        ) : null}

        {isDb ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={LABEL}>Table</span>
              <select
                className={cn(FIELD, 'font-mono')}
                value={TABLES.includes(form.resource) ? form.resource : 'db:customers'}
                onChange={(e) => set({ resource: e.target.value })}
              >
                {TABLES.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
            {form.action_type !== 'db.read' ? (
              <label>
                <span className={LABEL}>Environment</span>
                <select className={FIELD} value={form.env} onChange={(e) => set({ env: e.target.value })}>
                  <option value="prod">prod</option>
                  <option value="staging">staging</option>
                </select>
              </label>
            ) : null}
          </div>
        ) : null}

        {form.kind === 'action' && form.action_type === 'code.deploy' ? (
          <label className="block sm:w-1/2">
            <span className={LABEL}>Environment</span>
            <select className={FIELD} value={form.env} onChange={(e) => set({ env: e.target.value })}>
              {['prod', 'mainline', 'staging', 'dev'].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
        ) : null}

        {form.kind === 'action' && (form.action_type === 'email.external' || form.action_type === 'egress.post') ? (
          <label className="block sm:w-1/2">
            <span className={LABEL}>Highest data class in payload</span>
            <select className={FIELD} value={form.data_class} onChange={(e) => set({ data_class: e.target.value })}>
              {['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
        ) : null}

        {form.kind === 'config_change' && form.action_type === 'budget.raise' ? (
          <div className="grid gap-3 sm:grid-cols-[160px_minmax(0,1fr)]">
            <label>
              <span className={LABEL}>Scope</span>
              <select className={FIELD} value={form.scope_type} onChange={(e) => set({ scope_type: e.target.value })}>
                {['org', 'team', 'member', 'agent'].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <div>
              <span className={LABEL}>
                Increase <span className="ml-1 font-mono normal-case tracking-normal text-text-1">+{form.increase_pct}%</span>
              </span>
              <Slider
                className="mt-3"
                min={1}
                max={300}
                step={1}
                value={[form.increase_pct]}
                onValueChange={(v) => set({ increase_pct: v[0] ?? 1 })}
                aria-label="Increase in percent"
              />
            </div>
          </div>
        ) : null}

        {form.kind === 'config_change' && form.action_type.startsWith('control.') ? (
          <label className="block sm:w-1/2">
            <span className={LABEL}>Control</span>
            <select className={cn(FIELD, 'font-mono')} value={form.control_id} onChange={(e) => set({ control_id: e.target.value })}>
              {CONTROLS.map((c) => (
                <option key={c} value={c}>
                  {c}
                  {CRITICAL.has(c) ? ' (critical)' : ''}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <label className="block">
          <span className={LABEL}>Requested by</span>
          <select className={FIELD} value={form.requester} onChange={(e) => set({ requester: e.target.value })}>
            <optgroup label="Agents (sponsor fills self slots)">
              {dir.agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.id} — sponsor {dir.memberById.get(a.owner_member_id ?? '')?.name ?? '—'}
                </option>
              ))}
            </optgroup>
            <optgroup label="Members">
              {dir.members.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.role})
                </option>
              ))}
            </optgroup>
          </select>
        </label>
      </div>

      <div className="relative min-h-[260px] rounded-lg border border-border bg-surface-1/60 p-4">
        <div className="mb-3 flex items-center gap-2 text-2xs font-medium uppercase tracking-wider text-text-3">
          <Route className="size-3.5" /> Route
          {loading ? <Loader2 className="size-3 animate-spin" /> : null}
          {result?.isMock ? <span className="ml-auto rounded-xs bg-surface-3 px-1.5 py-0.5 normal-case tracking-normal text-text-3">mock router</span> : null}
        </div>
        {error ? (
          <motion.div key="err" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="rounded-md border border-block/30 bg-block/5 px-3 py-2 text-xs text-block">
            {error}
          </motion.div>
        ) : result ? (
          <motion.div
            key={`${result.required_role}-${result.rule_id}-${result.two_person}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.12 }}
            className="space-y-3.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              {result.required_role === 'deny' ? (
                <Ban className="size-5 text-block" />
              ) : result.required_role === 'auto' ? (
                <Zap className="size-5 text-log" />
              ) : (
                <ShieldCheck className="size-5 text-approval" />
              )}
              <span className="text-lg font-semibold tracking-[-0.01em] text-text-1">
                {result.required_role === 'deny' ? 'Always denied' : result.required_role === 'auto' ? 'Auto-approved' : `Needs ${levelLabel(result.required_role).toLowerCase()}`}
              </span>
              <ApproverBadge level={result.required_role} />
              {result.two_person ? (
                <span className="inline-flex h-5 items-center gap-1 rounded-sm border border-border bg-surface-2 px-1.5 text-2xs font-medium text-text-1">
                  <Users className="size-3" /> two-person
                </span>
              ) : null}
            </div>
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[12.5px]">
              <dt className="text-text-3">Matched rule</dt>
              <dd className="font-mono text-approval">{result.rule_id ?? 'default route (no rule matched; fail closed)'}</dd>
              <dt className="text-text-3">Requester</dt>
              <dd className="truncate text-text-2">
                {requesterName}
                {req.requester_agent_id && req.requester_member_id ? <span className="text-text-3"> · sponsor {dir.nameOf(req.requester_member_id)}</span> : null}
              </dd>
              <dt className="text-text-3">Approval valid</dt>
              <dd className="tabular text-text-2">
                {fmtTtl(result.ttl_s)} · {result.max_uses} use
                {result.max_uses === 1 ? '' : 's'}
              </dd>
              {result.description ? (
                <>
                  <dt className="text-text-3">Rule</dt>
                  <dd className="text-text-2">{result.description}</dd>
                </>
              ) : null}
            </dl>
            {result.required_role === 'deny' ? (
              <div className="rounded-md border border-block/30 bg-block/5 px-3 py-2 text-xs text-block">
                No one can approve this, whatever their role. The caller gets a 403 with the rule id.
              </div>
            ) : result.required_role === 'auto' ? (
              <div className="rounded-md border border-border bg-surface-2 px-3 py-2 text-xs text-text-2">Allowed without a card; still audited as approval.decided (auto).</div>
            ) : (
              <div>
                <div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-text-3">
                  Who could approve
                  {result.two_person ? ' (two distinct people needed)' : ''}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {eligible.map((m) => {
                    const me = m.id === viewer.member_id;
                    return (
                      <span
                        key={m.id}
                        className={cn(
                          'inline-flex h-7 items-center gap-1.5 rounded-md border px-1 pr-2.5 text-xs',
                          me ? 'border-border-strong bg-surface-3 text-text-1' : 'border-border bg-surface-2 text-text-2',
                        )}
                      >
                        <MemberAvatar member={m} size="xs" />
                        {firstName(m.name)}
                        <span className="text-2xs text-text-3">{m.role}</span>
                        {me ? <span className="text-2xs font-medium text-text-2">(you)</span> : null}
                      </span>
                    );
                  })}
                  {eligible.length === 0 ? <span className="text-xs text-text-3">Nobody active is eligible.</span> : null}
                </div>
                {viewerCheck && !viewerCheck.ok && viewerCheck.reason ? <div className="mt-2 text-xs text-text-3">You (view-as): {viewerCheck.reason}</div> : null}
              </div>
            )}
          </motion.div>
        ) : (
          <div className="grid h-40 place-items-center text-xs text-text-3">Simulating</div>
        )}
      </div>
    </div>
  );
}
