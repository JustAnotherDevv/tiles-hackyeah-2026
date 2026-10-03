// Mock audit log: hash-chained events (fake hex, NOT cryptographic) + verify result.
// Owner: dashboard-security.
import type { Action, AuditEvent, AuditVerifyResult, Page } from '@/api/types';
import { mockScenario } from '@/components/security/env';
import { agentIdentity, memberIdentity } from './cast';
import { mockDecisionPage } from './decisions';
import { fakeHex } from './rng';

const HEAD_SEQ = 4812;
const GENESIS = '0'.repeat(64);

function chain(events: AuditEvent[]): AuditEvent[] {
  const first = events[0];
  let prev = first ? fakeHex(`seq-${first.seq - 1}`, 64) : GENESIS;
  return events.map((e) => {
    const hash = fakeHex(`${prev}|${e.seq}|${e.event_type}|${e.event_id}`, 64);
    const out: AuditEvent = { ...e, prev_hash: prev, hash };
    prev = hash;
    return out;
  });
}

export function mockAuditPage(limit = 60): Page<AuditEvent> {
  const decisions = mockDecisionPage(40).items.slice().reverse();
  const n = Math.min(limit, 80);
  const startSeq = HEAD_SEQ - n + 1;
  const now = Date.now();
  const extra: Record<number, Partial<AuditEvent>> = {
    6: { event_type: 'policy.applied', actor: memberIdentity('u_marek'), reason: 'INJ-02 threshold 0.90 → 0.85', data: { version: 15, previous_version: 14, changes: 1 } },
    14: { event_type: 'feed.updated', reason: 'serial #2 verified (ed25519 a91f3c07)', data: { serial: 2, added: 1, removed: 0, modified: 2 } },
    21: { event_type: 'approval.created', actor: agentIdentity('trading-copilot@trading'), reason: '$50.00 subscription → admin', data: { approval_id: 'apr_7c1e9a2b40d1' } },
    29: { event_type: 'mcp.tool_changed', reason: 'rugpull.get_exchange_rate changed since pin', data: { server: 'rugpull', tool: 'get_exchange_rate' } },
  };
  const raw: AuditEvent[] = [];
  for (let i = 0; i < n; i++) {
    const seq = startSeq + i;
    const d = decisions[i % decisions.length];
    const ts = new Date(now - (n - i) * 47_000).toISOString();
    const base: AuditEvent = {
      schema: 'aegis.audit/1',
      event_id: `evt_${fakeHex(`evt${seq}`, 20)}`,
      seq,
      ts,
      event_type: 'decision',
      actor: d?.identity ?? null,
      request_id: d?.request_id ?? null,
      decision_id: d?.id ?? null,
      action: (d?.action ?? 'allow') as Action,
      control_id: d?.control_id ?? null,
      reason: d?.reason ?? null,
      policy_version: d?.policy_version ?? 15,
      feed_serial: d?.feed_serial ?? 2,
      data: { surface: d?.surface, destination: d?.destination?.dest_class, latency_ms: d?.latency_ms },
      prev_hash: '',
      hash: '',
    };
    const x = extra[i % 31];
    raw.push(x ? { ...base, ...x, decision_id: null, request_id: null, action: null, control_id: null } : base);
  }
  return { items: chain(raw).reverse(), next_cursor: null };
}

export function mockAuditVerify(): AuditVerifyResult {
  const broken = mockScenario() === 'broken';
  return {
    ok: !broken,
    records: HEAD_SEQ,
    head_hash: fakeHex(`head-${HEAD_SEQ}`, 64).replace(/^.{4}/, '41d9').replace(/.{4}$/, 'c07e'),
    broken_at_seq: broken ? 1234 : null,
    files: 3,
    checked_at: new Date().toISOString(),
    message: broken ? 'hash mismatch at seq 1234: prev_hash does not match the hash of seq 1233 (record edited after write)' : 'chain intact',
  };
}
