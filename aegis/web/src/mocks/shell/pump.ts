// Synthetic SSE pump — attached by api/sse.ts ONLY when mocks are forced (?mock=1 / VITE_AEGIS_MOCK=1),
// never silently (CONTRACTS §5.4). decision every 0.9–2.4 s (or ?mockRate=N per second), stats every 2 s,
// heartbeat every 15 s, approval.created every ~45 s, budget.updated every ~6 s. Owner: dashboard-shell (B16).
import type { SseEventMap, SseEventName } from '@/api/types';
import { mockRate } from '@/lib/mockMode';
import { mockBudgets } from './budgets';
import { makeMockDecision } from './decisions';
import { identityForAgent, ORG_ID } from './org';
import { liveRand, mockId } from './rng';
import { mockStatsTick } from './stats';

type Emit = <K extends SseEventName>(name: K, data: SseEventMap[K]) => void;

const APPROVAL_TITLES: { title: string; agent: string; action_type: string; amount: number | null; role: 'admin' | 'owner' | 'self'; control: string }[] = [
  { title: 'MarketPulse Pro subscription · $50.00 / month', agent: 'trading-copilot@trading', action_type: 'spend.subscription', amount: 50, role: 'admin', control: 'ACT-01' },
  { title: 'Read customers table (CONFIDENTIAL) · acme-db', agent: 'claude-code@platform', action_type: 'db.read', amount: null, role: 'admin', control: 'ACT-02' },
  { title: 'BurstGPU Cloud · 8× H100 for 2 h · $480.00', agent: 'claude-code@platform', action_type: 'spend.charge', amount: 480, role: 'owner', control: 'ACT-01' },
  { title: "OpenData Shop 'EU equities 2025' dataset · $12.00", agent: 'research-agent@research', action_type: 'spend.charge', amount: 12, role: 'self', control: 'ACT-01' },
];

export function startMockPump(emit: Emit): () => void {
  const timers: ReturnType<typeof setTimeout>[] = [];
  const intervals: ReturnType<typeof setInterval>[] = [];
  let stopped = false;
  const rate = mockRate();

  const nextDecision = () => {
    if (stopped) return;
    emit('decision', makeMockDecision());
    const delay = rate ? 1000 / rate : 900 + liveRand() * 1500;
    timers.push(setTimeout(nextDecision, delay));
  };
  timers.push(setTimeout(nextDecision, 600));

  intervals.push(setInterval(() => emit('stats', mockStatsTick()), 2000));
  intervals.push(setInterval(() => emit('heartbeat', { ts: new Date().toISOString() }), 15_000));
  intervals.push(
    setInterval(() => {
      const b = mockBudgets();
      emit('budget.updated', { statuses: b.scopes.flatMap((s) => s.limits).map((l) => ({ ...l, used: +(l.used * (1 + liveRand() * 0.01)).toFixed(2) })) });
    }, 6000),
  );

  let ai = 0;
  const nextApproval = () => {
    if (stopped) return;
    const t = APPROVAL_TITLES[ai++ % APPROVAL_TITLES.length];
    const now = Date.now();
    emit('approval.created', {
      id: mockId('apr'),
      org_id: ORG_ID,
      team_id: identityForAgent(t.agent).team_id,
      kind: 'action',
      action_type: t.action_type,
      title: t.title,
      summary: `${t.agent} requested ${t.action_type}`,
      requester: identityForAgent(t.agent),
      amount_usd: t.amount,
      resource: null,
      labels: {},
      payload: {},
      fingerprint: 'fp_mock',
      required_role: t.role,
      two_person: false,
      rule_id: null,
      votes: [],
      status: 'pending',
      created_at: new Date(now).toISOString(),
      expires_at: new Date(now + 3600_000).toISOString(),
      decided_at: null,
      decided_by: [],
      request_id: null,
      decision_id: null,
      control_id: t.control,
      uses: 0,
      max_uses: 1,
      execution: null,
      can_vote: true,
      why_not: null,
    });
    timers.push(setTimeout(nextApproval, 40_000 + liveRand() * 10_000));
  };
  timers.push(setTimeout(nextApproval, 20_000));

  return () => {
    stopped = true;
    timers.forEach(clearTimeout);
    intervals.forEach(clearInterval);
  };
}
