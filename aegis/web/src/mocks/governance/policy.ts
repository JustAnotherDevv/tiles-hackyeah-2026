// Mock policy engine for the policy page (?mock=1 or endpoints missing). Stateful in-memory store so
// validate → diff → apply → history → rollback behave consistently offline. Contract cast and
// control catalog ids only (CONTRACTS §4.3/§4.4). Owner: B19-dashboard-gov-policy.
import type {
  ApplyResult,
  ControlView,
  PolicyChange,
  PolicyDiffResponse,
  PolicyResponse,
  PolicyVersionInfo,
  SelfTestResult,
  ValidationIssue,
  ValidationReport,
} from '@/api/types';
import { roleSatisfies } from '@/components/governance/lib/eligibility';
import {
  getNestedScalar,
  getTopLevelScalar,
  parseBudgetLimits,
  parseControls,
  addBudgetLimit,
  setBudgetLimit,
  setControlField,
  setKillSwitch,
  setNestedScalar,
  setTopLevelScalar,
} from '@/components/governance/lib/yaml-text';
import { routeChanges } from '@/components/governance/policy/config-route';
import { unifiedDiff } from '@/components/governance/policy/line-ops';
import { govStore } from './store';

export const MOCK_POLICY_YAML = `# Aegis policy — Acme Capital (demo). One file, hot-reloaded: validate → self-test → atomic swap.
version: 1
metadata: {name: acme-capital-default, description: "Default control catalog for Acme Capital (demo)", owner: u_marek}
profile: balanced                       # permissive | balanced | strict | paranoid

defaults:
  mode: enforce                         # enforce | monitor (log "would block" only)
  fail_mode: closed
  semantic_timeout_ms: 400
  stream_mode: buffered
  block_response: message
  require_auth: false
  rehydrate_responses: true

destinations:
  matrix:                               # data class x destination -> action (DLP-01/02/03)
    CONFIDENTIAL: {local: allow,  remote: redact, third_party: block}
    RESTRICTED:   {local: redact, remote: redact, third_party: block}
    SECRET:       {local: log,    remote: block,  third_party: block}
    INTERNAL:     {local: allow,  remote: redact, third_party: redact}
  internal_domains: ["*.acme-capital.example", "*.corp.local"]

models:
  allowed: ["claude-*", "gpt-4.1-mini", "aegis-judge*", "qwen*", "mock-*"]
  denied: ["*:cloud", "aegis-guard*"]
  default_local: "aegis-judge"

budgets:
  defaults: {soft_pct: 80, on_soft: downgrade, on_hard: block, local_concurrency: 1, max_output_tokens: 4096}
  limits:
    - {scope: "org:acme-capital",              window: day,     usd: 150, compute_s: 14400}
    - {scope: "org:acme-capital",              window: month,   usd: 3000, spend_usd: 10000}
    - {scope: "team:trading",                  window: day,     usd: 60, tokens: 4000000}
    - {scope: "team:trading",                  window: month,   usd: 1200, spend_usd: 2000}
    - {scope: "team:research",                 window: day,     usd: 15, compute_s: 7200}
    - {scope: "team:platform",                 window: day,     usd: 50}
    - {scope: "member:*",                      window: day,     usd: 5}
    - {scope: "agent:claude-code@platform",    window: day,     usd: 30}
    - {scope: "agent:trading-copilot@trading", window: day,     usd: 20}
    - {scope: "agent:research-agent@research", window: day,     compute_s: 5400}
    - {scope: "agent:chaos-agent@platform",    window: day,     usd: 0.50, tokens: 100000, on_hard: require_approval}
    - {scope: "session:*",                     window: session, usd: 5.0, tokens: 3000000}
  loops: {repeat: 3, window: 20, cycle_k: 3, error_streak: 5, ladder: [tool_error, block, kill]}
  rate: {requests_per_min: 120, tool_calls_per_min: 60}
  kill_switch: {global: false, teams: [], members: [], agents: [], sessions: []}

approvals:
  defaults: {ttl_s: 900, default_approver: admin, default_config_approver: owner}
  config_rules:                         # first match wins; multi-change = max level
    - {id: tighten,          when: {action: ["budget.lower", "control.enable", "control.*.tighten", "killswitch.on"]}, approver: admin}
    - {id: raise-small,      when: {action: ["budget.raise"], scope_type: [member, agent, session], increase_pct_lte: 100}, approver: admin}
    - {id: raise-team-small, when: {action: ["budget.raise"], scope_type: [team], increase_pct_lte: 50}, approver: admin}
    - {id: raise-large,      when: {action: ["budget.raise"]}, approver: owner}
    - {id: loosen-threshold, when: {action: ["control.threshold.loosen", "model.allow", "killswitch.off"]}, approver: admin}
    - {id: disable-control,  when: {action: ["control.disable", "control.remove", "control.mode", "control.action.loosen"]}, approver: owner}

controls:
  - id: GOV-01
    name: Caller identity & attribution
    action: log
  - id: GOV-02
    name: Model allowlist & destination tiering
    action: block
  - id: GOV-03
    name: Tool authorization (RBAC + arg constraints)
    action: block
  - id: GOV-04
    name: Human approval gate for other high-impact tools
    action: require_approval
  - id: GOV-05
    name: Config-change governance (who may change what)
    action: require_approval
  - id: ACT-01
    name: Spend guard (purchases, subscriptions, top-ups)
    action: require_approval
    params: {auto_allow_max_usd: 0, hard_block_above_usd: 5000}
  - id: ACT-02
    name: Data access guard (tables by sensitivity & environment)
    action: require_approval
  - id: ACT-03
    name: External send guard (email, webhooks, uploads)
    action: require_approval
  - id: ACT-04
    name: Code execution & deploy guard
    action: require_approval
  - id: DLP-01
    name: Egress PII & payment-card tokenization (destination-aware)
    action: redact
    severity: high
    params: {redaction_ratio_block: 0.6, mask_style: placeholder}
  - id: DLP-02
    name: Secrets & credentials
    action: block
    severity: critical
    params: {entropy_min: 4.0, min_len: 20, allow_doc_examples: true}
  - id: DLP-03
    name: Metadata stripping & generalization
    action: redact
  - id: DLP-04
    name: Tool-arg / egress exfiltration scan
    action: block
  - id: DLP-05
    name: Output & tool-result leak detection (+ canary)
    action: redact
  - id: DLP-06
    name: Exfil-channel neutralization (md images/links, ANSI)
    action: redact
  - id: DLP-07
    name: Multilingual NER sensitive data (incl. Polish)
    action: redact
    threshold: 0.6
    fail_mode: open
  - id: DLP-08
    name: Vault & controlled re-identification
    action: allow
  - id: INJ-01
    name: Normalization + deterministic injection signatures
    action: block
  - id: INJ-02
    name: Semantic injection / jailbreak classifier
    action: block
    threshold: 0.90                     # demo lever: 0.90 -> 0.50 flips the borderline prompt
    fail_mode: deterministic_only
    timeout_ms: 400
  - id: INJ-03
    name: Content safety + topic adherence %
    action: block
    threshold: 0.8
  - id: INJ-04
    name: Hidden-context exposure (extraction + canary + overlap)
    action: block
  - id: INJ-05
    name: Goal-drift / grounding check
    action: require_approval
    mode: monitor
  - id: EXE-01
    name: Dangerous command guard
    action: block
  - id: EXE-02
    name: Filesystem & network scope (SSRF)
    action: block
  - id: EXE-03
    name: Taint-flow breaker (lethal trifecta)
    action: require_approval
  - id: EXE-04
    name: Loop / rate / circuit breaker / kill switch
    action: block
  - id: MCP-01
    name: Server registry & launch check
    action: block
  - id: MCP-02
    name: Tool-definition poisoning scan
    action: redact
  - id: MCP-03
    name: Tool pinning (rug pull) & shadowing
    action: block
  - id: BUD-01
    name: Token & cost budgets (remote + local, spend)
    action: block
  - id: BUD-02
    name: Local compute & concurrency
    action: block
  - id: SIG-01
    name: External exploit-signature engine
    action: block
  - id: SIG-02
    name: Model-artifact gate (pickle / GGUF)
    action: block
  - id: SIG-03
    name: Package-install / slopsquatting guard
    action: block
  - id: CUS-01
    name: Customer-defined rules
    action: block
    timeout_ms: 2500
    fail_mode: deterministic_only
    params:
      rules: [{id: deal-codenames, text: "Confidential M&A code names must not leave the firm", keywords: ["Project Falcon", "Projekt Sokół", "Project Vistula"], action: block}]

tests:
  - {name: aws-key-blocked, generate: aws_access_key, expect: block, control: DLP-02}   # key generated at runtime
  - {name: benign-earnings, text: "Summarise the Q3 earnings call", expect: allow}
`;

interface PolicyState {
  version: number;
  yaml: string;
  appliedAt: string;
  appliedBy: string | null;
  source: string;
  history: PolicyVersionInfo[];
  versions: Map<number, string>;
}

const t0 = Date.now();
const iso = (ms: number) => new Date(ms).toISOString();

function seedState(): PolicyState {
  const versions = new Map<number, string>();
  // older versions differ in a believable way (threshold / budget / disabled control)
  const v9 = MOCK_POLICY_YAML.replace('threshold: 0.90                     # demo lever', 'threshold: 0.85                     # demo lever');
  const v10 = MOCK_POLICY_YAML.replace('window: day,     usd: 60, tokens', 'window: day,     usd: 50, tokens');
  const v11 = MOCK_POLICY_YAML.replace('    name: Goal-drift / grounding check\n    action: require_approval\n    mode: monitor', '    name: Goal-drift / grounding check\n    action: require_approval\n    mode: off');
  versions.set(9, v9);
  versions.set(10, v10);
  versions.set(11, v11);
  versions.set(12, MOCK_POLICY_YAML);
  const sha = (n: number) => `${(0x9f3a1c00 + n * 7919).toString(16)}e1d0b7c4a5`;
  const history: PolicyVersionInfo[] = [
    { version: 12, sha256: sha(12), applied_at: iso(t0 - 6 * 60_000), applied_by: 'u_marek', source: 'file', reason: 'INJ-05 back to monitor', changes_count: 1, summary: 'INJ-05 mode off → monitor' },
    { version: 11, sha256: sha(11), applied_at: iso(t0 - 52 * 60_000), applied_by: 'u_emily', source: 'approval', reason: 'Earnings week load', changes_count: 1, summary: 'team:trading daily usd 50 → 60 (+20%)' },
    { version: 10, sha256: sha(10), applied_at: iso(t0 - 3 * 3600_000), applied_by: 'u_katarzyna', source: 'api', reason: 'Tune injection classifier', changes_count: 1, summary: 'INJ-02 threshold 0.85 → 0.90' },
    { version: 9, sha256: sha(9), applied_at: iso(t0 - 9 * 3600_000), applied_by: null, source: 'startup', reason: null, changes_count: 0, summary: 'startup' },
  ];
  return { version: 12, yaml: MOCK_POLICY_YAML, appliedAt: iso(t0 - 6 * 60_000), appliedBy: 'u_marek', source: 'file', history, versions };
}

const state: PolicyState = seedState();

export function mockPolicyState(): Readonly<PolicyState> {
  return state;
}

/** The shared mock policy version lives in B18's govStore (approvals executors bump it too). */
function syncVersion(): void {
  if (govStore.policyVersion !== state.version) {
    // someone else (B18 default executor) bumped it: keep the YAML, adopt the version
    state.versions.set(govStore.policyVersion, state.yaml);
    state.version = govStore.policyVersion;
  }
}

export function mockPolicy(): PolicyResponse {
  syncVersion();
  return {
    version: state.version,
    yaml: state.yaml,
    sha256: state.history[0]?.sha256 ?? 'mock',
    applied_at: state.appliedAt,
    applied_by: state.appliedBy,
    source: state.source,
    profile: getTopLevelScalar(state.yaml, 'profile') ?? 'balanced',
    controls_count: parseControls(state.yaml).length,
  };
}

// ---------------------------------------------------------------- validation (prototype heuristics)
const ENUMS: Record<string, string[]> = {
  mode: ['enforce', 'monitor', 'off'],
  action: ['allow', 'log', 'redact', 'require_approval', 'block'],
  fail_mode: ['open', 'closed', 'deterministic_only'],
  profile: ['permissive', 'balanced', 'strict', 'paranoid'],
};

export function mockLint(yaml: string): ValidationIssue[] {
  const ls = yaml.split('\n');
  const issues: ValidationIssue[] = [];
  for (let i = 0; i < ls.length; i++) {
    const raw = ls[i];
    const tab = raw.indexOf('\t');
    if (tab >= 0 && /^\s*$/.test(raw.slice(0, tab))) {
      issues.push({ path: '', line: i + 1, col: tab + 1, message: "found character '\\t' that cannot start any token (YAML indentation must use spaces)", severity: 'error' });
      return issues;
    }
    const code = raw.replace(/(^|\s)#.*$/, '');
    if (!code.trim()) continue;
    const ind = /^ */.exec(code)?.[0].length ?? 0;
    if (ind % 2) {
      issues.push({ path: '', line: i + 1, col: ind + 1, message: 'bad indentation of a mapping entry', severity: 'error' });
      return issues;
    }
    const body = code.trim();
    const opens = (body.match(/[[{]/g) || []).length;
    const closes = (body.match(/[\]}]/g) || []).length;
    if (opens !== closes) {
      issues.push({ path: '', line: i + 1, col: ind + body.length + 1, message: `unclosed flow collection — expected '${opens > closes ? (body.lastIndexOf('[') > body.lastIndexOf('{') ? ']' : '}') : '['}'`, severity: 'error' });
      return issues;
    }
    if (/^- /.test(body) || body === '-') continue;
    if (!/^[^:[\]{}]+:(\s|$)/.test(body)) {
      issues.push({ path: '', line: i + 1, col: ind + body.length + 1, message: `could not find expected ':' after "${body.slice(0, 28)}"`, severity: 'error' });
      return issues;
    }
  }
  // schema checks
  for (let i = 0; i < ls.length; i++) {
    const l = ls[i];
    const thr = /^\s+threshold:\s*([^\s#]+)/.exec(l);
    if (thr) {
      const v = Number(thr[1]);
      if (Number.isNaN(v) || v < 0 || v > 1) issues.push({ path: 'controls[].threshold', line: i + 1, col: l.indexOf(thr[1]) + 1, message: 'threshold must be a number in [0, 1]', severity: 'error' });
    }
    const en = /^\s+enabled:\s*([^\s#]+)/.exec(l);
    if (en && !/^(true|false)$/.test(en[1])) issues.push({ path: 'controls[].enabled', line: i + 1, col: l.indexOf(en[1]) + 1, message: 'enabled must be true or false', severity: 'error' });
    for (const key of ['mode', 'action', 'fail_mode']) {
      const m = new RegExp(`^\\s+${key}:\\s*([^\\s#,}]+)`).exec(l);
      if (m && !ENUMS[key].includes(m[1])) issues.push({ path: `controls[].${key}`, line: i + 1, col: l.indexOf(m[1]) + 1, message: `${key} must be one of ${ENUMS[key].join(' | ')}`, severity: 'error' });
    }
    const p = /^profile:\s*([^\s#]+)/.exec(l);
    if (p && !ENUMS.profile.includes(p[1])) issues.push({ path: 'profile', line: i + 1, col: l.indexOf(p[1]) + 1, message: `profile must be one of ${ENUMS.profile.join(' | ')}`, severity: 'error' });
    const neg = /\b(usd|tokens|compute_s|spend_usd):\s*(-[\d.]+)/.exec(l);
    if (neg) issues.push({ path: 'budgets.limits[]', line: i + 1, col: l.indexOf(neg[2]) + 1, message: 'budget limits must be ≥ 0', severity: 'error' });
  }
  const ids = parseControls(yaml).map((c) => c.id);
  const dup = ids.find((id, k) => ids.indexOf(id) !== k);
  if (dup) {
    const line = parseControls(yaml).filter((c) => c.id === dup)[1]?.line ?? null;
    issues.push({ path: `controls[id=${dup}]`, line, col: 5, message: `duplicate control id ${dup}`, severity: 'error' });
  }
  return issues;
}

// ---------------------------------------------------------------- semantic diff
const ACTION_RANK: Record<string, number> = { allow: 0, log: 1, redact: 2, require_approval: 3, block: 4 };
const PROFILE_RANK: Record<string, number> = { permissive: 0, balanced: 1, strict: 2, paranoid: 3 };

function change(p: Partial<PolicyChange> & Pick<PolicyChange, 'kind' | 'path' | 'summary'>): PolicyChange {
  return { before: null, after: null, control_id: null, scope: null, dimension: null, increase_pct: null, loosening: false, ...p };
}

export function mockChanges(before: string, after: string): PolicyChange[] {
  const out: PolicyChange[] = [];
  const pb = getTopLevelScalar(before, 'profile');
  const pa = getTopLevelScalar(after, 'profile');
  if (pb !== pa) {
    out.push(change({ kind: 'profile.change', path: 'profile', before: pb, after: pa, loosening: (PROFILE_RANK[pa ?? ''] ?? 1) < (PROFILE_RANK[pb ?? ''] ?? 1), summary: `profile ${pb} → ${pa}` }));
  }
  const mb = getNestedScalar(before, 'defaults', 'mode');
  const ma = getNestedScalar(after, 'defaults', 'mode');
  if (mb !== ma) out.push(change({ kind: 'control.mode', path: 'defaults.mode', before: mb, after: ma, loosening: ma !== 'enforce', summary: `defaults.mode ${mb} → ${ma} (all controls)` }));

  const cb = new Map(parseControls(before).map((c) => [c.id, c]));
  const ca = new Map(parseControls(after).map((c) => [c.id, c]));
  for (const [id, a] of ca) {
    const b = cb.get(id);
    const path = `controls[id=${id}]`;
    if (!b) {
      out.push(change({ kind: 'control.add', path, control_id: id, after: a.action, summary: `${id} added (${a.action ?? 'block'})` }));
      continue;
    }
    if (b.enabled !== a.enabled) {
      out.push(change({ kind: a.enabled ? 'control.enable' : 'control.disable', path: `${path}.enabled`, control_id: id, before: b.enabled, after: a.enabled, loosening: !a.enabled, summary: `${a.enabled ? 'control.enable' : 'control.disable'} ${id}` }));
    }
    if ((b.mode ?? 'enforce') !== (a.mode ?? 'enforce')) {
      const loosen = (a.mode ?? 'enforce') !== 'enforce';
      out.push(change({ kind: loosen ? 'control.mode' : 'control.enable', path: `${path}.mode`, control_id: id, before: b.mode ?? 'enforce', after: a.mode ?? 'enforce', loosening: loosen, summary: `${id} mode ${b.mode ?? 'enforce'} → ${a.mode ?? 'enforce'}` }));
    }
    if (b.threshold !== a.threshold) {
      const loosen = (a.threshold ?? 1) > (b.threshold ?? 1);
      out.push(change({ kind: loosen ? 'control.threshold.loosen' : 'control.threshold.tighten', path: `${path}.threshold`, control_id: id, before: b.threshold, after: a.threshold, loosening: loosen, summary: `${id} threshold ${b.threshold ?? '—'} → ${a.threshold ?? '—'}` }));
    }
    if ((b.action ?? 'block') !== (a.action ?? 'block')) {
      const loosen = (ACTION_RANK[a.action ?? 'block'] ?? 4) < (ACTION_RANK[b.action ?? 'block'] ?? 4);
      out.push(change({ kind: loosen ? 'control.action.loosen' : 'control.action.tighten', path: `${path}.action`, control_id: id, before: b.action, after: a.action, loosening: loosen, summary: `${id} action ${b.action} → ${a.action}` }));
    }
  }
  for (const id of cb.keys()) {
    if (!ca.has(id)) out.push(change({ kind: 'control.remove', path: `controls[id=${id}]`, control_id: id, loosening: true, summary: `${id} removed` }));
  }
  // budgets
  const lb = parseBudgetLimits(before);
  const la = parseBudgetLimits(after);
  for (const a of la) {
    const b = lb.find((x) => x.scope === a.scope && x.window === a.window);
    if (!b) {
      out.push(change({ kind: 'budget.add', path: `budgets.limits[scope=${a.scope},window=${a.window}]`, scope: a.scope, summary: `budget added ${a.scope} ${a.window}` }));
      continue;
    }
    for (const [dim, v] of Object.entries(a.values)) {
      const old = b.values[dim];
      if (old === undefined || old === v) continue;
      const pct = old > 0 ? ((v - old) / old) * 100 : 100;
      const raise = v > old;
      out.push(change({ kind: raise ? 'budget.raise' : 'budget.lower', path: `budgets.limits[scope=${a.scope},window=${a.window}].${dim}`, scope: a.scope, dimension: dim, before: old, after: v, increase_pct: Math.round(pct * 10) / 10, loosening: raise, summary: `${a.scope} ${a.window === 'day' ? 'daily' : a.window} ${dim} ${old} → ${v} (${pct >= 0 ? '+' : ''}${Math.round(pct)}%)` }));
    }
  }
  // CUS-01 keyword edits & anything else
  const kwb = /keywords:\s*\[([^\]]*)\]/.exec(before)?.[1] ?? '';
  const kwa = /keywords:\s*\[([^\]]*)\]/.exec(after)?.[1] ?? '';
  if (kwb !== kwa && ca.has('CUS-01')) out.push(change({ kind: 'control.params', path: 'controls[id=CUS-01].params.rules', control_id: 'CUS-01', before: kwb, after: kwa, summary: `CUS-01 keywords → [${kwa}]` }));
  if (out.length === 0 && before !== after) out.push(change({ kind: 'other', path: '', summary: 'text edits (comments / formatting)' }));
  return out;
}

export function mockSelftest(yaml: string): SelfTestResult[] {
  const ctl = new Map(parseControls(yaml).map((c) => [c.id, c]));
  const results: SelfTestResult[] = [];
  const add = (name: string, control: string, expect: SelfTestResult['expect'], got: SelfTestResult['expect']) =>
    results.push({ name, control, expect, got, got_control: got === 'allow' ? null : control, passed: expect === got, latency_ms: Math.round(2 + Math.random() * 18) / 10 });
  for (const c of ctl.values()) {
    if (!c.enabled || c.mode === 'off' || c.mode === 'monitor') continue; // skipped like the real gate
    const declared = (c.action ?? 'block') as SelfTestResult['expect'];
    const base = c.id.toLowerCase();
    add(`${base}-positive`, c.id, declared, declared);
    add(`${base}-negative`, c.id, 'allow', 'allow');
    if (c.id === 'DLP-02') add('generated-aws-key', 'DLP-02', 'block', declared === 'block' ? 'block' : declared);
    if (c.id === 'INJ-02') add('inj-classic-en', 'INJ-02', 'block', (c.threshold ?? 0.9) <= 0.97 ? 'block' : 'allow');
  }
  return results;
}

export function mockValidate(yaml: string, selftest = true, baseYaml?: string): ValidationReport {
  const issues = mockLint(yaml);
  const errors = issues.filter((i) => i.severity === 'error');
  const warnings = issues.filter((i) => i.severity === 'warning');
  const changes = errors.length ? [] : mockChanges(baseYaml ?? state.yaml, yaml);
  const st = selftest && errors.length === 0 ? mockSelftest(yaml) : [];
  const failed = st.filter((t) => !t.passed);
  for (const f of failed) {
    errors.push({ path: `controls[id=${f.control}].tests[name=${f.name}]`, line: parseControls(yaml).find((c) => c.id === f.control)?.line ?? null, col: 5, message: `self-test ${f.control}/${f.name}: expected ${f.expect}, got ${f.got} — update the test, or use mode: monitor / enabled: false to loosen this control`, severity: 'error' });
  }
  return { valid: errors.length === 0, errors, warnings, selftest: st, selftest_passed: failed.length === 0, changes, required_role: routeChanges(changes)?.level ?? null };
}

export function mockDiff(yaml: string, baseYaml?: string): PolicyDiffResponse {
  const base = baseYaml ?? state.yaml;
  const changes = mockLint(yaml).some((i) => i.severity === 'error') ? [] : mockChanges(base, yaml);
  return { changes, unified: unifiedDiff(base, yaml), required_role: routeChanges(changes)?.level ?? null };
}

// ---------------------------------------------------------------- apply / rollback
function commit(yaml: string, by: string | null, source: string, reason: string | null, changes: PolicyChange[]): number {
  syncVersion();
  state.version = govStore.bumpPolicyVersion();
  state.yaml = yaml;
  state.appliedAt = new Date().toISOString();
  state.appliedBy = by;
  state.source = source;
  state.versions.set(state.version, yaml);
  state.history.unshift({
    version: state.version,
    sha256: `${(0x9f3a1c00 + state.version * 7919).toString(16)}e1d0b7c4a5`,
    applied_at: state.appliedAt,
    applied_by: by,
    source,
    reason,
    changes_count: changes.length,
    summary: changes.slice(0, 2).map((c) => c.summary).join('; ') || 'edit',
  });
  return state.version;
}

export function mockApply(
  body: { yaml: string; base_version: number; reason?: string | null },
  viewer: { id: string | null; role: 'owner' | 'admin' | 'member' },
  source = 'api',
): ApplyResult {
  syncVersion();
  const t = performance.now();
  const base: ApplyResult = { status: 'noop', version: state.version, previous_version: state.version, approval: null, decision_id: null, errors: [], changes: [], latency_ms: 0, message: '' };
  if (body.base_version !== state.version) {
    return { ...base, status: 'conflict', message: `Policy moved to v${state.version} — your draft is based on v${body.base_version}` };
  }
  if (body.yaml === state.yaml) return { ...base, message: 'No changes against the active policy' };
  const report = mockValidate(body.yaml, true);
  if (!report.valid) {
    return { ...base, status: 'rejected', errors: report.errors, latency_ms: Math.round(performance.now() - t + 40), message: `Rejected — still on v${state.version}` };
  }
  const changes = report.changes;
  const route = routeChanges(changes);
  const level = route?.level ?? 'owner';
  if (!roleSatisfies(viewer.role, level)) {
    const approval = govStore.createApproval({
      kind: 'config_change',
      action_type: changes[0]?.kind ?? 'other',
      title: `Policy change: ${changes[0]?.summary ?? 'edit'}${changes.length > 1 ? ` (+${changes.length - 1} more)` : ''}`,
      summary: body.reason ?? null,
      requester_member_id: viewer.id,
      control_id: 'GOV-05',
      resource: changes[0]?.control_id ? `control:${changes[0].control_id}` : 'policy',
      changes,
      required_role: level,
      rule_id: route?.rule_id ?? null,
      payload: { unified: unifiedDiff(state.yaml, body.yaml), base_version: body.base_version, reason: body.reason ?? null, yaml: body.yaml },
    });
    return { ...base, status: 'pending_approval', approval, changes, latency_ms: Math.round(performance.now() - t + 12), message: `Routed to ${level} (${route?.rule_id ?? 'default'})` };
  }
  const prev = state.version;
  const v = commit(body.yaml, viewer.id, source, body.reason ?? null, changes);
  return { ...base, status: 'applied', version: v, previous_version: prev, changes, latency_ms: Math.round(140 + Math.random() * 70), message: `Applied as v${v}` };
}

export function mockRollback(body: { version: number; reason?: string | null }, viewer: { id: string | null; role: 'owner' | 'admin' | 'member' }): ApplyResult {
  const yaml = state.versions.get(body.version);
  if (!yaml) {
    return { status: 'rejected', version: state.version, previous_version: state.version, approval: null, decision_id: null, errors: [{ path: '', line: null, col: null, message: `unknown version v${body.version}`, severity: 'error' }], changes: [], latency_ms: 0, message: 'Unknown version' };
  }
  return mockApply({ yaml, base_version: state.version, reason: body.reason ?? `rollback to v${body.version}` }, viewer, 'rollback');
}

export function mockHistory(): { items: PolicyVersionInfo[] } {
  return { items: state.history };
}

export function mockVersion(v: number): { version: number; yaml: string } {
  return { version: v, yaml: state.versions.get(v) ?? state.yaml };
}

const FAMILY_SURFACES: Record<string, ControlView['surfaces']> = {
  DLP: ['prompt.user', 'model.request', 'tool.input', 'mcp.call', 'egress.request'],
  INJ: ['prompt.user', 'model.request', 'tool.output', 'mcp.result'],
  EXE: ['tool.input', 'mcp.call'],
  ACT: ['tool.input', 'mcp.call', 'egress.request'],
  GOV: ['model.request', 'tool.input', 'mcp.call'],
  MCP: ['mcp.init', 'mcp.list', 'mcp.call'],
  BUD: ['model.request', 'tool.input', 'mcp.call'],
  SIG: ['prompt.user', 'model.request', 'tool.input', 'mcp.call'],
  CUS: ['prompt.user', 'model.request', 'tool.input', 'mcp.call'],
};

export function mockControls(yaml: string = state.yaml): { items: ControlView[] } {
  const globalMode = getNestedScalar(yaml, 'defaults', 'mode') ?? 'enforce';
  return {
    items: parseControls(yaml).map((c, i) => {
      const family = c.id.split('-')[0];
      return {
        id: c.id,
        family,
        name: c.name ?? c.id,
        kind: family === 'INJ' && c.id !== 'INJ-01' ? 'semantic' : family === 'EXE' && c.id === 'EXE-04' ? 'stateful' : 'deterministic',
        owner: '—',
        enabled: c.enabled,
        mode: ((c.mode ?? globalMode) as ControlView['mode']) || 'enforce',
        action: (c.action ?? 'block') as ControlView['action'],
        threshold: c.threshold,
        severity: 'high',
        owasp: [],
        surfaces: FAMILY_SURFACES[family] ?? [],
        implemented: true,
        hits_24h: (i * 37) % 211,
        blocks_24h: (i * 13) % 47,
        p95_ms: 0.4 + ((i * 7) % 30) / 10,
      };
    }),
  };
}

// ---------------------------------------------------------------- executor (approvals → policy)
type PatchLike = { op?: string; path: string; value?: unknown };

/** Apply PatchOps (subset used by budgets/killswitch/control edits) to the mock YAML text. */
export function applyPatchText(yaml: string, patch: PatchLike[]): string {
  let y = yaml;
  for (const op of patch) {
    let m = /^budgets\.limits\[scope=([^,\]]+),window=([^\]]+)\]\.(\w+)$/.exec(op.path);
    if (m && typeof op.value === 'number') {
      y = setBudgetLimit(y, m[1], m[2], m[3], op.value)?.yaml ?? addBudgetLimit(y, m[1], m[2], m[3], op.value)?.yaml ?? y;
      continue;
    }
    m = /^controls\[id=([^\]]+)\]\.(\w+)$/.exec(op.path);
    if (m) {
      y = setControlField(y, m[1], m[2], op.value as string | number | boolean | null)?.yaml ?? y;
      continue;
    }
    m = /^budgets\.kill_switch\.(global|teams|members|agents|sessions)$/.exec(op.path);
    if (m) {
      const kind = m[1];
      if (kind === 'global') y = setKillSwitch(y, 'global', Boolean(op.value))?.yaml ?? y;
      else {
        const type = kind.slice(0, -1);
        y = setKillSwitch(y, `${type}:${String(op.value)}`, op.op !== 'remove')?.yaml ?? y;
      }
      continue;
    }
    if (op.path === 'profile' && typeof op.value === 'string') {
      y = setTopLevelScalar(y, 'profile', op.value).yaml;
      continue;
    }
    m = /^defaults\.(\w+)$/.exec(op.path);
    if (m && op.value !== undefined) y = setNestedScalar(y, 'defaults', m[1], op.value as string | number | boolean)?.yaml ?? y;
  }
  return y;
}

/** PolicyChange[] → PatchOps (for seeded approvals that carry only `changes`). */
function changesToPatch(changes: PolicyChange[]): PatchLike[] {
  const out: PatchLike[] = [];
  for (const c of changes) {
    if (c.path && c.after !== undefined && c.after !== null) out.push({ op: 'set', path: c.path, value: c.after });
    else if (c.kind === 'control.disable' && c.control_id) out.push({ op: 'set', path: `controls[id=${c.control_id}].enabled`, value: false });
  }
  return out;
}

govStore.registerExecutor((req) => {
  if (req.kind !== 'config_change' && req.kind !== 'budget_raise') return null;
  const p = req.payload as { yaml?: string; patch?: PatchLike[]; changes?: PolicyChange[]; reason?: string };
  syncVersion();
  const prev = state.version;
  let next = state.yaml;
  if (typeof p.yaml === 'string') next = p.yaml;
  else if (Array.isArray(p.patch) && p.patch.length) next = applyPatchText(state.yaml, p.patch);
  else if (Array.isArray(p.changes)) next = applyPatchText(state.yaml, changesToPatch(p.changes));
  const changes = mockChanges(state.yaml, next);
  const approver = req.votes.filter((v) => v.decision === 'approve').map((v) => v.member_id).pop() ?? null;
  const v = commit(next, approver, 'approval', p.reason ?? req.summary ?? req.title, changes.length ? changes : (p.changes ?? []));
  return { status: 'applied', policy_version: v, previous_version: prev, latency_ms: 140 + Math.round(Math.random() * 60), changes: changes.length };
});

/**
 * Governed proposal of a patch (budget raise, kill switch, quick lever): route → apply directly when the
 * viewer's role satisfies the route, else park it as a pending approval in the shared mock store.
 */
export function mockProposePatch(p: {
  patch: PatchLike[];
  changes: PolicyChange[];
  title: string;
  reason: string | null;
  viewer: { id: string | null; role: 'owner' | 'admin' | 'member' };
  resource?: string | null;
  labels?: Record<string, string>;
  source?: string;
}): ApplyResult {
  syncVersion();
  const prev = state.version;
  const base: ApplyResult = { status: 'noop', version: prev, previous_version: prev, approval: null, decision_id: null, errors: [], changes: p.changes, latency_ms: 0, message: '' };
  const next = applyPatchText(state.yaml, p.patch);
  if (next === state.yaml) return { ...base, message: 'No change — the policy already has this value' };
  const route = routeChanges(p.changes);
  const level = route?.level ?? 'owner';
  if (level === 'deny') return { ...base, status: 'rejected', message: 'Denied by rule' };
  if (!roleSatisfies(p.viewer.role, level)) {
    const approval = govStore.createApproval({
      kind: 'config_change',
      action_type: p.changes[0]?.kind ?? 'other',
      title: p.title,
      summary: p.reason,
      requester_member_id: p.viewer.id,
      control_id: 'GOV-05',
      resource: p.resource ?? null,
      labels: p.labels,
      changes: p.changes,
      required_role: level,
      rule_id: route?.rule_id ?? null,
      payload: { patch: p.patch, reason: p.reason, base_version: prev },
    });
    return { ...base, status: 'pending_approval', approval, message: `Routed to ${level} (${route?.rule_id ?? 'default'})`, latency_ms: 9 };
  }
  const v = commit(next, p.viewer.id, p.source ?? 'api', p.reason, p.changes);
  return { ...base, status: 'applied', version: v, previous_version: prev, latency_ms: Math.round(120 + Math.random() * 60), message: `Applied as v${v}` };
}
