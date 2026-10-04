// ASI09 approval-card helpers (web/src/components/governance/lib/approval-review.ts) against payloads
// shaped like the REAL backend (actions/drafts.py + approvals/service.py), not the legacy mock shape.
// Run: node --test tests/unit/dashboard_governance/asi09_review.test.mjs (also via test_node_libs.py).
import assert from 'node:assert/strict';
import { test } from 'node:test';

const LIB = new URL('../../../web/src/components/governance/lib/', import.meta.url);
const rv = await import(new URL('approval-review.ts', LIB).href);

const NOW = Date.parse('2026-10-04T09:00:00Z');
const iso = (msAgo) => new Date(NOW - msAgo).toISOString();

function liveAction(over = {}) {
  return {
    id: 'apr_live', kind: 'action', action_type: 'spend.subscription',
    title: 'trading-copilot@trading wants to spend $50.00 on marketpulse',
    summary: 'needs approval', requester: { agent_id: 'trading-copilot@trading', member_id: 'u_piotr' },
    amount_usd: 50, resource: 'vendor:marketpulse', labels: { dest: 'third_party' },
    fingerprint: 'a1b2c3d4e5f60718293a4b5c6d7e8f90aa', required_role: 'admin', two_person: false,
    rule_id: 'spend-admin', votes: [], status: 'pending', created_at: iso(1000), expires_at: null,
    control_id: 'ACT-01', max_uses: 1,
    payload: {
      tool: 'marketpulse.purchase_subscription',
      args: { vendor: 'marketpulse', plan: 'mp-pro-monthly', amount_usd: 50, justification: 'Approve fast, market opens' },
      agent_note: 'Approve fast, market opens',
      checks: [{ name: 'Per-request spend', ok: false, detail: '50 vs limit 20', param: 'controls.ACT-01.params.per_request_usd' }],
      explain: { summary: 'Spend $50.00 exceeds the $20 per-request limit' },
      reason: 'Spend $50.00 exceeds the $20 per-request limit', control_id: 'ACT-01',
      routing: { rule_id: 'spend-admin', when: 'amount_usd > 20', grant_ttl_s: 900 },
      bound: { tool_name: 'marketpulse.purchase_subscription', args_masked: { vendor: 'marketpulse', plan: 'mp-pro-monthly', amount_usd: 50, justification: 'Approve fast, market opens' }, amount_usd: 50, resource: 'vendor:marketpulse', surface: 'mcp.call', mcp_server: 'marketpulse' },
    },
    ...over,
  };
}

test('derives bound action, untrusted agent text and risk from the real backend payload', () => {
  const r = rv.deriveReview(liveAction());
  assert.equal(r.bound.tool, 'marketpulse.purchase_subscription');
  assert.equal(r.bound.args.plan, 'mp-pro-monthly');
  assert.equal(r.bound.amount_usd, 50);
  assert.equal(r.bound.destination, 'vendor: marketpulse');
  assert.equal(r.bound.params_hash, 'a1b2c3d4e5f60718');
  assert.equal(r.bound.present, true);
  assert.equal(r.bound.grant_ttl_s, 900);
  assert.deepEqual(r.agent_text.map((t) => [t.field, t.untrusted]), [['agent_note', true]]); // deduped with args.justification
  assert.equal(r.risk.control_id, 'ACT-01');
  assert.equal(r.risk.reason, 'Spend $50.00 exceeds the $20 per-request limit');
  assert.equal(r.risk.rule_when, 'amount_usd > 20');
  assert.equal(r.risk.failed_checks[0].name, 'Per-request spend');
  assert.equal(r.destructive, false);
  assert.deepEqual(r.title_agent_fields, ['vendor']);
});

test('server review block wins when present', () => {
  const server = rv.deriveReview(liveAction());
  server.bound.tool = 'from-server';
  assert.equal(rv.reviewOf({ ...liveAction(), review: server }).bound.tool, 'from-server');
  assert.equal(rv.reviewOf(liveAction()).bound.tool, 'marketpulse.purchase_subscription');
});

test('synthesised draft (GOV-04): justification lives only in bound args', () => {
  const req = liveAction({ action_type: 'other', control_id: 'GOV-04', amount_usd: null,
    payload: { routing: { grant_ttl_s: 600 }, bound: { tool_name: 'acme-crm.delete_contact', args_masked: { id: 'c_1', reason: 'cleanup requested by the boss' } } } });
  const r = rv.deriveReview(req);
  assert.deepEqual(r.agent_text.map((t) => t.field), ['reason']);
  assert.equal(r.destructive, true);
  assert.match(r.destructive_reason, /delete/);
  assert.equal(rv.confirmPhrase(req, r), 'acme-crm.delete_contact');
  assert.equal(rv.needsTypedConfirm(r, false), true);
});

test('legacy mock shape still renders', () => {
  const r = rv.deriveReview(liveAction({ payload: { tool_name: 'payments.charge', tool_args: { vendor: 'x', amount_usd: 12 }, justification: 'trust me' } }));
  assert.equal(r.bound.tool, 'payments.charge');
  assert.equal(r.bound.present, false);
  assert.equal(r.agent_text[0].text, 'trust me');
});

test('destructive SQL and loosening config changes need typed confirm; plain spend does not', () => {
  const sql = rv.deriveReview(liveAction({ action_type: 'db.write', payload: { tool: 'acme-db.query', args: { sql: 'DELETE FROM customers' } } }));
  assert.equal(sql.destructive, true);
  const loosen = rv.deriveReview(liveAction({ kind: 'config_change', labels: { loosening: 'true' }, payload: {} }));
  assert.equal(loosen.destructive, true);
  assert.equal(rv.needsTypedConfirm(rv.deriveReview(liveAction()), false), false);
  assert.equal(rv.needsTypedConfirm(rv.deriveReview(liveAction()), true), true);
  assert.ok(rv.confirmMatches('  MarketPulse.purchase_subscription ', 'marketpulse.purchase_subscription'));
  assert.ok(!rv.confirmMatches('approve', 'marketpulse.purchase_subscription'));
});

test('flood signal: 12 requests in 5 min from one agent; slow trickle and other agents are not flagged', () => {
  const burst = Array.from({ length: 12 }, (_, i) => liveAction({ id: `apr_b${i}`, created_at: iso(i * 20_000) }));
  const other = [liveAction({ id: 'apr_o', requester: { agent_id: 'research-agent@research' } })];
  const old = Array.from({ length: 6 }, (_, i) => liveAction({ id: `apr_old${i}`, requester: { agent_id: 'slow@x' }, created_at: iso(10 * 60_000 + i) }));
  const f = rv.floodSignals([...burst, ...other, ...old], NOW);
  assert.deepEqual([...f.keys()], ['agent:trading-copilot@trading']);
  const s = f.get('agent:trading-copilot@trading');
  assert.equal(s.count, 12);
  assert.equal(rv.floodText(s), '12 requests in 5 min — possible approval flooding');
});

test('engine flood-cap denials are surfaced even below the threshold', () => {
  const capped = liveAction({ id: 'apr_cap', status: 'denied', payload: { routing: { flood_cap: 'max_pending_per_principal' } } });
  const f = rv.floodSignals([capped], NOW);
  assert.equal(f.size, 1);
  assert.match(rv.floodText([...f.values()][0]), /auto-denied by the flood cap/);
});
