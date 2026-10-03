// Mock verdicts for the dry-run probes (used when /v1/guard is unavailable or mocks are forced).
// Evaluates the probe set against a policy YAML with the same levers the real pipeline honours:
// control enabled/mode/threshold/action, defaults.mode, destination matrix and CUS-01 keywords.
// Owner: B19-dashboard-gov-policy.
import type { Action } from '@/api/types';
import type { ProbeResult } from '@/components/governance/lib/probe-defs';
import { PROBES } from '@/components/governance/lib/probe-defs';
import { getNestedScalar, parseControls } from '@/components/governance/lib/yaml-text';

const BORDERLINE_SCORE = 0.62;
const INJECTION_SCORE = 0.97;

function matrixCell(yaml: string, dataClass: string, dest: string): Action | null {
  const m = new RegExp(`${dataClass}:\\s*\\{[^}]*\\b${dest}:\\s*(\\w+)`).exec(yaml);
  return m ? (m[1] as Action) : null;
}

export function mockProbeResults(yaml: string): Record<string, ProbeResult> {
  const controls = new Map(parseControls(yaml).map((c) => [c.id, c]));
  const globalMode = getNestedScalar(yaml, 'defaults', 'mode') ?? 'enforce';
  const live = (id: string) => {
    const c = controls.get(id);
    if (!c || !c.enabled) return 'off' as const;
    const mode = c.mode ?? globalMode;
    return mode === 'off' ? ('off' as const) : mode === 'monitor' ? ('monitor' as const) : ('enforce' as const);
  };
  const actionOf = (id: string, fallback: Action): Action => (controls.get(id)?.action as Action | undefined) ?? fallback;
  const keywords = (/keywords:\s*\[([^\]]*)\]/.exec(yaml)?.[1] ?? '')
    .split(',')
    .map((s) => s.trim().replace(/^["']|["']$/g, '').toLowerCase())
    .filter(Boolean);

  const res = (id: string, action: Action, control: string | null, reason: string, extra: Partial<ProbeResult> = {}): ProbeResult => ({
    id,
    action,
    control,
    score: null,
    threshold: null,
    reason,
    degraded: false,
    monitor: false,
    latency_ms: Math.round((0.6 + Math.random() * 2.4) * 10) / 10,
    ...extra,
  });
  /** One deciding control with monitor/off semantics. */
  const decide = (id: string, probe: string, act: Action, reason: string, extra: Partial<ProbeResult> = {}): ProbeResult => {
    const st = live(id);
    if (st === 'enforce') return res(probe, act, id, reason, extra);
    if (st === 'monitor') return res(probe, 'allow', null, `would ${act} (${id}, monitor)`, { ...extra, monitor: true });
    return res(probe, 'allow', null, `${id} disabled — no control objected`, extra);
  };
  const cusHit = (probe: string, text: string): ProbeResult | null => {
    const hit = keywords.find((k) => text.toLowerCase().includes(k));
    return hit && live('CUS-01') !== 'off' ? decide('CUS-01', probe, 'block', `customer rule keyword "${hit}"`) : null;
  };

  const out: Record<string, ProbeResult> = {};
  // PII → remote: DLP-01 per destination matrix
  {
    const cell = matrixCell(yaml, 'CONFIDENTIAL', 'remote') ?? 'redact';
    out['pii-remote'] = cell === 'allow' ? res('pii-remote', 'allow', null, 'matrix CONFIDENTIAL→remote: allow') : decide('DLP-01', 'pii-remote', cell, `PESEL, IBAN → ${cell} (CONFIDENTIAL→remote)`);
  }
  {
    const cell = matrixCell(yaml, 'SECRET', 'remote') ?? 'block';
    const act = actionOf('DLP-02', 'block') === 'block' ? cell : actionOf('DLP-02', 'block');
    out['secret-remote'] = decide('DLP-02', 'secret-remote', act, 'AWS access key detected');
  }
  {
    const inj1 = live('INJ-01');
    if (inj1 === 'enforce') out.injection = res('injection', 'block', 'INJ-01', 'signature: ignore-previous-instructions', { score: INJECTION_SCORE, threshold: controls.get('INJ-02')?.threshold ?? 0.9 });
    else {
      const thr = controls.get('INJ-02')?.threshold ?? 0.9;
      out.injection =
        INJECTION_SCORE >= thr
          ? decide('INJ-02', 'injection', actionOf('INJ-02', 'block'), `injection score ${INJECTION_SCORE} ≥ ${thr}`, { score: INJECTION_SCORE, threshold: thr })
          : res('injection', 'allow', null, `score ${INJECTION_SCORE} < ${thr}`, { score: INJECTION_SCORE, threshold: thr });
    }
  }
  {
    const thr = controls.get('INJ-02')?.threshold ?? 0.9;
    out.borderline =
      BORDERLINE_SCORE >= thr
        ? decide('INJ-02', 'borderline', actionOf('INJ-02', 'block'), `injection score ${BORDERLINE_SCORE} ≥ threshold ${thr}`, { score: BORDERLINE_SCORE, threshold: thr })
        : res('borderline', 'allow', null, `injection score ${BORDERLINE_SCORE} < threshold ${thr}`, { score: BORDERLINE_SCORE, threshold: thr });
  }
  out['spend-50'] = decide('ACT-01', 'spend-50', actionOf('ACT-01', 'require_approval'), '$50.00 subscription → spend-admin');
  out['pii-table'] = decide('ACT-02', 'pii-table', actionOf('ACT-02', 'require_approval'), 'db:customers (CONFIDENTIAL) → db-pii-read');
  out['pipe-shell'] = decide('EXE-01', 'pipe-shell', 'block', 'pipe-to-shell: curl … | sh');
  out.benign = cusHit('benign', 'Summarise the Q3 earnings call for NVDA in 3 bullets.') ?? res('benign', 'allow', null, 'no control objected');
  // keep PROBES order / completeness
  for (const p of PROBES) if (!out[p.id]) out[p.id] = res(p.id, 'allow', null, 'not evaluated');
  return out;
}
