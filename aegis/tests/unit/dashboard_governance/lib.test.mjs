// node:test over the PURE governance libs (web/src/components/governance/lib/*.ts).
// Node >= 23.6 (or 22.18+) strips TypeScript types natively; the libs only use top-level `import type`.
// Run: node --test tests/unit/dashboard_governance/lib.test.mjs   (also run by `make test` through
// tests/unit/dashboard_security/test_node_libs.py).
// The eligibility block asserts tests/fixtures/eligibility_cases.json, the golden shared with the server
// (tests/unit/approvals_engine/test_eligibility_parity.py) and Pocket (entry/src/test/Eligibility.test.ets).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const LIB = new URL('../../../web/src/components/governance/lib/', import.meta.url);
const load = (f) => import(new URL(f, LIB).href);

const elig = await load('eligibility.ts');
const { lineDiff, diffText, hasChanges, changedLinesB, hunks, unifiedDiff, unifiedLineKind, splitLines } = await load('line-diff.ts');
const yt = await load('yaml-text.ts');
const fmt = await load('format-gov.ts');

const GOLDEN = JSON.parse(readFileSync(new URL('../../fixtures/eligibility_cases.json', import.meta.url), 'utf8'));
const POLICY = readFileSync(new URL('../../../config/policy.yaml', import.meta.url), 'utf8');

// ------------------------------------------------------------------ eligibility parity (golden)
const NOW = Date.parse('2026-01-01T12:00:00Z');
const MEMBERS = GOLDEN.members.map((m) => ({ ...m, name: m.id }));

function toRequest(c) {
  const r = c.request;
  return {
    id: `apr_${c.id}`,
    kind: 'action',
    action_type: 'test.eligibility',
    title: c.id,
    requester: { org_id: 'acme-capital', team_id: null, ...r.requester },
    required_role: r.required_role,
    two_person: r.two_person,
    rule_id: `golden.${c.id}`,
    status: r.status,
    votes: r.votes.map((v) => ({ comment: null, ts: '2026-01-01T11:59:00Z', ...v })),
    expires_at: null,
  };
}

/** How the dashboard derives the sponsor of an agent requester (agent list owner_member_id). */
function optsFor(req) {
  const agent = GOLDEN.agents.find((a) => a.id === req.requester.agent_id);
  return { sponsorId: agent?.owner_member_id ?? null };
}

for (const c of GOLDEN.cases) {
  test(`eligibility golden: ${c.id}`, () => {
    const req = toRequest(c);
    const opts = optsFor(req);
    const expected = [...c.eligible].sort();
    const got = MEMBERS.filter((m) => m.active && elig.canVote({ member_id: m.id, role: m.role }, req, NOW, opts).ok)
      .map((m) => m.id)
      .sort();
    assert.deepEqual(got, expected, `${c.id} (${c.why}): canVote set`);
    if (req.status === 'pending') {
      const listed = elig.eligibleApprovers(req, MEMBERS, opts).map((m) => m.id).sort();
      assert.deepEqual(listed, expected, `${c.id}: eligibleApprovers (drops inactive members)`);
    }
    for (const [mid, code] of Object.entries(c.codes)) {
      const m = MEMBERS.find((x) => x.id === mid);
      const v = elig.canVote({ member_id: m.id, role: m.role }, req, NOW, opts);
      assert.equal(v.ok, false, `${c.id}: ${mid} should be blocked`);
      assert.equal(v.code, code, `${c.id}: ${mid} code`);
      assert.ok(v.reason && v.reason.length > 0, `${c.id}: ${mid} blocked without a reason`);
    }
    // agents never vote, whatever the request
    const a = elig.canVote({ member_id: null, role: 'agent' }, req, NOW, opts);
    assert.equal(a.ok, false);
    assert.equal(a.code, 'agent');
  });
}

test('eligibility: expires_at in the past locks the card (client-side expiry)', () => {
  const req = { ...toRequest(GOLDEN.cases.find((c) => c.id === 'admin-member-requester')), expires_at: '2026-01-01T11:00:00Z' };
  const v = elig.canVote({ member_id: 'u_marek', role: 'admin' }, req, NOW);
  assert.equal(v.ok, false);
  assert.equal(v.code, 'expired');
  // eligible-approver lists ignore expiry so a locked card still names who could have acted
  assert.ok(elig.eligibleApprovers(req, MEMBERS).some((m) => m.id === 'u_marek'));
});

test('eligibility helpers: approvals needed / labels', () => {
  assert.equal(elig.approvalsNeeded({ two_person: true }), 2);
  assert.equal(elig.approvalsNeeded({ two_person: false }), 1);
  const tp = toRequest(GOLDEN.cases.find((c) => c.id === 'two-person-admin-one-vote'));
  assert.equal(elig.approveCount(tp), 1);
  assert.match(elig.approveLabel(tp), /2 of 2/);
  assert.equal(elig.roleSatisfies('admin', 'owner'), false);
  assert.equal(elig.roleSatisfies('owner', 'admin'), true);
  assert.equal(elig.roleSatisfies('owner', 'deny'), false);
  for (const level of ['self', 'admin', 'owner', 'auto', 'deny']) {
    assert.ok(elig.explainLevel({ ...tp, required_role: level }).length > 0, level);
  }
});

// ------------------------------------------------------------------ line diff
test('lineDiff: identical input has no changes; edits are minimal and indexed', () => {
  const a = ['a', 'b', 'c', 'd'];
  assert.equal(hasChanges(lineDiff(a, a)), false);
  const ops = lineDiff(a, ['a', 'B', 'c', 'd', 'e']);
  assert.deepEqual(ops.filter((o) => o.t === 'del').map((o) => o.s), ['b']);
  assert.deepEqual(ops.filter((o) => o.t === 'add').map((o) => o.s), ['B', 'e']);
  assert.deepEqual(changedLinesB(ops), [1, 4]);
  // ops replay a → b
  assert.deepEqual(ops.filter((o) => o.t !== 'del').map((o) => o.s), ['a', 'B', 'c', 'd', 'e']);
  assert.deepEqual(ops.filter((o) => o.t !== 'add').map((o) => o.s), a);
});

test('unifiedDiff: hunk headers are consistent with their bodies', () => {
  const a = Array.from({ length: 30 }, (_, i) => `line ${i}`).join('\n');
  const b = a.replace('line 3\n', 'line three\n').replace('line 25', 'line 25 changed');
  const ops = diffText(a, b);
  const hs = hunks(ops, 3);
  assert.equal(hs.length, 2, 'two distant edits => two hunks');
  for (const h of hs) {
    assert.equal(h.aLen, h.ops.filter((o) => o.t !== 'add').length);
    assert.equal(h.bLen, h.ops.filter((o) => o.t !== 'del').length);
  }
  const u = unifiedDiff(a, b);
  const kinds = u.split('\n').map(unifiedLineKind);
  assert.equal(kinds[0], 'meta');
  assert.equal(kinds.filter((k) => k === 'hunk').length, 2);
  assert.equal(kinds.filter((k) => k === 'add').length, 2);
  assert.equal(kinds.filter((k) => k === 'del').length, 2);
  assert.equal(unifiedDiff(a, a), '');
  assert.deepEqual(splitLines('x\r\ny\rz'), ['x', 'y', 'z']);
});

// ------------------------------------------------------------------ yaml-text quick edits (real policy)
/** Lines that differ between two texts (quick edits must be one-line, comment-preserving). */
function changedLines(a, b) {
  return diffText(a, b).filter((o) => o.t !== 'ctx');
}

test('yaml-text: parses the shipped policy controls', () => {
  const controls = yt.parseControls(POLICY);
  assert.ok(controls.length >= 10, `only ${controls.length} controls parsed`);
  const ids = controls.map((c) => c.id);
  assert.equal(new Set(ids).size, ids.length, 'duplicate control ids');
  for (const c of controls) assert.match(c.id, /^[A-Z0-9]{2,4}-\d{2}$/);
});

test('yaml-text: setControlField round-trips on every block control and touches one line', () => {
  const all = yt.listControlBlocks(POLICY);
  const ALL_IDS = all.map((x) => x.id);
  const blocks = all.filter((b) => !b.flow);
  assert.ok(blocks.length > 0);
  for (const b of blocks) {
    const edit = yt.setControlField(POLICY, b.id, 'enabled', false);
    assert.ok(edit, b.id);
    assert.equal(yt.getControlField(edit.yaml, b.id, 'enabled'), 'false', b.id);
    const delta = changedLines(POLICY, edit.yaml);
    assert.ok(delta.length <= 2, `${b.id}: ${delta.length} changed lines`);
    // the item list (ids, order) is unchanged
    assert.deepEqual(yt.listControlBlocks(edit.yaml).map((x) => x.id), ALL_IDS, b.id);
  }
});

test('yaml-text: top-level scalar edit keeps the trailing comment', () => {
  const before = yt.getTopLevelScalar(POLICY, 'profile');
  assert.ok(before);
  const edit = yt.setTopLevelScalar(POLICY, 'profile', 'strict');
  assert.equal(yt.getTopLevelScalar(edit.yaml, 'profile'), 'strict');
  const line = edit.yaml.split('\n')[edit.line - 1];
  const orig = POLICY.split('\n')[edit.line - 1];
  if (orig.includes('#')) assert.ok(line.includes(orig.slice(orig.indexOf('#'))), 'comment dropped');
  assert.equal(changedLines(POLICY, edit.yaml).length, 2); // one del + one add
});

test('yaml-text: kill switch on/off round-trips', () => {
  const ks = yt.getKillSwitch(POLICY);
  assert.equal(typeof ks.global, 'boolean');
  const on = yt.setKillSwitch(POLICY, 'agent:golden-agent@test', true);
  assert.ok(on);
  assert.ok(yt.getKillSwitch(on.yaml).agents.includes('golden-agent@test'));
  const off = yt.setKillSwitch(on.yaml, 'agent:golden-agent@test', false);
  assert.deepEqual(yt.getKillSwitch(off.yaml), ks);
  const g = yt.setKillSwitch(POLICY, 'global', !ks.global);
  assert.equal(yt.getKillSwitch(g.yaml).global, !ks.global);
  assert.equal(yt.setKillSwitch(POLICY, 'bogus:x', true), null);
});

test('yaml-text: addCustomKeyword is idempotent; breakYaml injects a tab', () => {
  const once = yt.addCustomKeyword(POLICY, 'golden-codename');
  if (once) {
    assert.ok(once.yaml.includes('"golden-codename"'));
    const twice = yt.addCustomKeyword(once.yaml, 'golden-codename');
    assert.equal(twice.yaml, once.yaml);
  }
  const broken = yt.breakYaml(POLICY);
  assert.ok(broken.yaml.split('\n')[broken.line - 1].startsWith('\t'));
});

test('yaml-text: scalar rendering quotes YAML-ambiguous strings', () => {
  assert.equal(yt.yamlScalar(true), 'true');
  assert.equal(yt.yamlScalar(3), '3');
  assert.equal(yt.yamlScalar(0.12345678), '0.1235');
  assert.equal(yt.yamlScalar('monitor'), 'monitor');
  for (const s of ['yes', 'off', 'null', '1.5', 'a b', '']) assert.match(yt.yamlScalar(s), /^".*"$/, s);
  assert.deepEqual(yt.splitComment('value  # note'), ['value', '  # note']);
  assert.deepEqual(yt.splitComment('"a # b"'), ['"a # b"', '']);
});

// ------------------------------------------------------------------ formatting (shape, not wording)
test('format-gov: durations, money and scopes', () => {
  assert.equal(fmt.fmtSeconds(59), '59s');
  assert.equal(fmt.fmtSeconds(90), '1m 30s');
  assert.equal(fmt.fmtSeconds(5400), '1h 30m');
  assert.equal(fmt.fmtCountdown(0), 'expired');
  assert.equal(fmt.fmtCountdown(299_000), '04:59');
  assert.equal(fmt.fmtCountdown(3_723_000), '1:02:03');
  assert.equal(fmt.fmtMoney(null), '—');
  assert.match(fmt.fmtMoney(12.5), /^\$12\.50$/);
  assert.match(fmt.fmtMoney(1200), /^\$1,200$/);
  assert.deepEqual(fmt.scopeParts('team:trading'), { type: 'team', id: 'trading' });
  assert.deepEqual(fmt.scopeParts('global'), { type: 'global', id: '' });
  assert.match(fmt.scopeLabel('agent:x@y'), /x@y/);
  for (const s of ['pending', 'approved', 'denied', 'expired']) assert.ok(fmt.statusMeta(s).label, s);
});
