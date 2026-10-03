// UIX-15 · node:test over the PURE security libs (web/src/components/security/lib/*.ts).
// Node >= 23.6 strips TypeScript types natively; the libs only use top-level `import type`.
// Run: node --test tests/unit/dashboard_security/
import assert from 'node:assert/strict';
import { test } from 'node:test';

const LIB = new URL('../../../web/src/components/security/lib/', import.meta.url);
const load = (f) => import(new URL(f, LIB).href);

const { buildOriginalParts, buildOutboundParts, changedSegmentIndexes, redactionStats } = await load('redactionDiff.ts');
const { EMPTY_FILTER, filterToParams, paramsToFilter, matchDecision, toApiQuery } = await load('filters.ts');
const { buildTrace, scoreScale } = await load('trace.ts');
const { deriveFeedSteps, failingStepIndex } = await load('feedSteps.ts');
const { stageSchedule, clampStageMs } = await load('schedule.ts');
const { lineDiff, parseUnified } = await load('lineDiff.ts');
const { PLACEHOLDER_RE, isIrreversible, dataClassOf, splitTokens } = await load('placeholders.ts');
const { FALLBACK_CONTROLS, phaseOf, fallbackKind } = await load('catalog.ts');

// ------------------------------------------------------------------ redaction diff
const ORIGINAL = 'Jan PESEL 44051401359 card 4111 1111 1111 1111 CVV 123 again 44051401359';
function red(start, end, entity, placeholder, extra = {}) {
  return { segment_index: 0, path: 'text', start, end, entity, data_class: dataClassOf(entity), placeholder, control_id: 'DLP-01', reversible: !placeholder.startsWith('[REDACTED') && !placeholder.includes('*'), ...extra };
}
const pesel1 = ORIGINAL.indexOf('44051401359');
const pan = ORIGINAL.indexOf('4111');
const cvv = ORIGINAL.indexOf('123');
const pesel2 = ORIGINAL.lastIndexOf('44051401359');
const REDS = [
  red(pesel1, pesel1 + 11, 'PESEL', '[PESEL_1]'),
  red(pan, pan + 19, 'PAN', '411111******1111'),
  red(cvv, cvv + 3, 'CVV', '[REDACTED:CVV]'),
  red(pesel2, pesel2 + 11, 'PESEL', '[PESEL_1]'), // repeated value → same placeholder
  red(pesel1 + 2, pesel1 + 6, 'PHONE', '[PHONE_1]'), // overlaps PESEL → dropped
];
const OUTBOUND = 'Jan PESEL [PESEL_1] card 411111******1111 CVV [REDACTED:CVV] again [PESEL_1]';

test('original/outbound parts pair by shared key (repeated placeholder, CVV, PCI mask, overlap)', () => {
  const orig = buildOriginalParts(ORIGINAL, REDS, 0);
  const out = buildOutboundParts(OUTBOUND, REDS, 0);
  const oEnt = orig.filter((p) => p.kind === 'entity');
  assert.equal(oEnt.length, 4, 'overlapping PHONE span dropped');
  assert.deepEqual(oEnt.map((p) => p.text), ['44051401359', '4111 1111 1111 1111', '123', '44051401359']);
  const keyed = out.filter((p) => p.key);
  assert.deepEqual(keyed.map((p) => p.key), oEnt.map((p) => p.key));
  assert.equal(keyed[1].kind, 'masked');
  assert.equal(keyed[2].kind, 'dropped');
  assert.equal(keyed[3].text, '[PESEL_1]');
  assert.equal(orig.map((p) => p.text).join(''), ORIGINAL);
  assert.equal(out.map((p) => p.text).join(''), OUTBOUND);
});

test('changed segments and stats', () => {
  const wire = { original: [{ path: 'a', text: 'same' }, { path: 'b', text: ORIGINAL }], outbound: [{ path: 'a', text: 'same' }, { path: 'b', text: OUTBOUND }] };
  const reds = REDS.map((r) => ({ ...r, segment_index: 1 }));
  assert.deepEqual(changedSegmentIndexes(wire, reds), [1]);
  const s = redactionStats(wire, reds);
  assert.ok(s);
});

test('placeholder helpers', () => {
  assert.ok(isIrreversible('[REDACTED:CVV]'));
  assert.ok(!isIrreversible('[PESEL_1]'));
  assert.equal(OUTBOUND.match(new RegExp(PLACEHOLDER_RE.source, 'g')).length, 3);
  assert.equal(splitTokens(OUTBOUND).filter((t) => t.token).length, 4);
});

// ------------------------------------------------------------------ filters
test('filter <-> URL round trip and matching', () => {
  const f = { ...EMPTY_FILTER, actions: ['block', 'redact'], surface: 'tool.input', agent: 'claude-code@platform', q: 'curl', nonAllow: true };
  const p = filterToParams(f, new URLSearchParams('mock=1&d=dec_1'));
  assert.equal(p.get('mock'), '1');
  assert.equal(p.get('d'), 'dec_1');
  assert.deepEqual(paramsToFilter(p), f);
  assert.deepEqual(paramsToFilter(filterToParams(EMPTY_FILTER)), EMPTY_FILTER);
  const d = { id: 'dec_1', action: 'block', surface: 'tool.input', kind: 'tool_call', identity: { agent_id: 'claude-code@platform' }, source: 'hook', destination: { dest_class: 'local' }, control_id: 'EXE-01', controls: [], preview: 'curl x | sh', reason: '', entities: [] };
  assert.ok(matchDecision(d, f));
  assert.ok(!matchDecision({ ...d, action: 'allow' }, f));
  assert.match(toApiQuery({ ...EMPTY_FILTER, actions: ['block'], control: 'SIG-01' }), /action=block&control_id=SIG-01/);
});

// ------------------------------------------------------------------ trace
const CATALOG = [
  { id: 'GOV-01', name: 'Identity', family: 'GOV', kind: 'deterministic', owner: 'x', surfaces: ['prompt.user', 'tool.input'] },
  { id: 'DLP-01', name: 'PII', family: 'DLP', kind: 'deterministic', owner: 'x', surfaces: ['prompt.user'] },
  { id: 'DLP-02', name: 'Secrets', family: 'DLP', kind: 'deterministic', owner: 'x', surfaces: ['prompt.user'], threshold: 4 },
  { id: 'EXE-01', name: 'Shell', family: 'EXE', kind: 'deterministic', owner: 'x', surfaces: ['tool.input'] },
  { id: 'DLP-07', name: 'NER', family: 'DLP', kind: 'semantic', owner: 'x', surfaces: ['prompt.user'], threshold: 0.6 },
  { id: 'INJ-02', name: 'Injection', family: 'INJ', kind: 'semantic', owner: 'x', surfaces: ['prompt.user', 'tool.input'], threshold: 0.9 },
];
const dec = (control_id, action, latency_ms, extra = {}) => ({ action, control_id, reason: '', score: null, threshold: null, approval_id: null, mode: 'enforce', severity: 'medium', findings: [], mutations: [], degraded: false, latency_ms, owasp: [], ...extra });

test('buildTrace: sequential deterministic offsets, concurrent semantic offsets', () => {
  const t = buildTrace(
    { surface: 'prompt.user', action: 'redact', control_id: 'DLP-01', latency_ms: 20, decisions: [dec('GOV-01', 'allow', 0.2), dec('DLP-01', 'redact', 0.5), dec('DLP-02', 'allow', 0.3, { score: 5.2, threshold: 4 }), dec('DLP-07', 'redact', 12, { score: 0.96, threshold: 0.6 }), dec('INJ-02', 'allow', 14, { score: 0.62, threshold: 0.9 })] },
    CATALOG,
  );
  const by = Object.fromEntries(t.stages.map((s) => [s.controlId, s]));
  assert.equal(by['GOV-01'].offsetMs, 0);
  assert.equal(by['DLP-01'].offsetMs, 0.2);
  assert.equal(by['DLP-02'].offsetMs, 0.7);
  assert.ok(Math.abs(t.detTotalMs - 1.0) < 1e-9);
  assert.equal(by['DLP-07'].offsetMs, t.detTotalMs);
  assert.equal(by['INJ-02'].offsetMs, t.detTotalMs);
  assert.equal(t.semTotalMs, 14);
  assert.equal(by['DLP-02'].scaleMax, 6, 'threshold > 1 scales to max(th*1.5, score*1.1)');
  assert.equal(by['INJ-02'].scaleMax, 1);
  assert.equal(by['DLP-01'].primary, true);
  assert.equal(t.shortCircuitAfter, null);
});

test('buildTrace: deterministic block short-circuits semantic rows', () => {
  const t = buildTrace({ surface: 'tool.input', action: 'block', control_id: 'EXE-01', latency_ms: 2, decisions: [dec('EXE-01', 'block', 0.1)] }, CATALOG);
  assert.equal(t.shortCircuitAfter, 'EXE-01');
  const inj = t.stages.find((s) => s.controlId === 'INJ-02');
  assert.equal(inj.status, 'skipped');
  assert.equal(t.stages.find((s) => s.controlId === 'GOV-01').status, 'quiet');
  assert.equal(scoreScale(0.5, 0.9), 1);
});

// ------------------------------------------------------------------ feed steps
test('deriveFeedSteps for bad_signature, rollback and unreachable', () => {
  const st = { status: 'rejected', last_error: null, serial: 2 };
  const sig = deriveFeedSteps(st, 'bad_signature: ed25519 verification failed');
  assert.equal(sig[1].state, 'fail');
  assert.equal(sig[0].state, 'ok');
  assert.ok(sig.slice(2).every((s) => s.state === 'skipped'));
  assert.equal(failingStepIndex('rollback: serial 1 <= 2'), 5);
  const rb = deriveFeedSteps(st, 'rollback: serial 1 <= 2');
  assert.equal(rb[5].state, 'fail');
  const un = deriveFeedSteps({ status: 'unreachable', last_error: 'unreachable: connect timeout', serial: 2 });
  assert.equal(un[0].state, 'fail');
  const ok = deriveFeedSteps({ status: 'ok', last_error: null, serial: 2 });
  assert.ok(ok.every((s) => s.state === 'ok'));
});

// ------------------------------------------------------------------ schedule
test('stageSchedule clamps and serializes deterministic stages; reduced motion → 0', () => {
  assert.equal(clampStageMs(0.1), 140);
  assert.equal(clampStageMs(100), 700);
  assert.equal(clampStageMs(10), 250);
  const stages = [
    { key: 'a', phase: 'deterministic', latencyMs: 0.2 },
    { key: 'b', phase: 'deterministic', latencyMs: 10 },
    { key: 'c', phase: 'semantic', latencyMs: 14 },
    { key: 'd', phase: 'semantic', latencyMs: 2, status: 'skipped' },
  ];
  const s = stageSchedule(stages);
  const by = Object.fromEntries(s.items.map((i) => [i.key, i]));
  assert.equal(by.a.startMs, 0);
  assert.equal(by.b.startMs, 140);
  assert.equal(by.c.startMs, 390);
  assert.equal(by.d.durMs, 0);
  assert.equal(s.totalMs, 390 + 350);
  const r = stageSchedule(stages, { reduced: true });
  assert.equal(r.totalMs, 0);
  assert.ok(r.items.every((i) => i.startMs === 0 && i.durMs === 0));
});

// ------------------------------------------------------------------ line diff + catalog
test('lineDiff and unified parsing', () => {
  const d = lineDiff('a\nb', 'a\nb\nc');
  assert.deepEqual(d.map((l) => l.op), [' ', ' ', '+']);
  assert.deepEqual(parseUnified(['@@ -1 +1,2 @@', ' a', '+b']).map((l) => l.op), [' ', '+']);
});

test('fallback catalog covers the contract controls', () => {
  assert.ok(FALLBACK_CONTROLS.length >= 36);
  assert.equal(new Set(FALLBACK_CONTROLS.map((c) => c.id)).size, FALLBACK_CONTROLS.length);
  assert.equal(phaseOf('semantic'), 'semantic');
  assert.equal(phaseOf('stateful'), 'deterministic');
  assert.ok(['deterministic', 'stateful', 'semantic', 'hybrid'].includes(fallbackKind('DLP-07')));
});
