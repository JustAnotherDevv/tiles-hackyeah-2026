// Demo cast (CONTRACTS §4.5 ids are binding). Mock fallback for /api/members.
// Owner: dashboard-shell (scaffold seed).
import type { Member } from '@/api/types';

const ORG = 'acme-capital';
const at = '2026-10-03T08:00:00Z';

function m(id: string, name: string, role: Member['role'], team_id: string, title: string): Member {
  return { id, org_id: ORG, team_id, name, email: `${id.slice(2)}@acme-capital.example`, role, title, avatar_url: null, active: true, created_at: at, meta: {} };
}

export const MOCK_MEMBERS: Member[] = [
  m('u_katarzyna', 'Katarzyna Nowak', 'owner', 'platform', 'CISO'),
  m('u_marek', 'Marek Zielinski', 'admin', 'platform', 'Platform lead'),
  m('u_emily', 'Emily Carter', 'admin', 'trading', 'Head of trading tech'),
  m('u_piotr', 'Piotr Kowalski', 'member', 'trading', 'Quant developer'),
  m('u_olivia', 'Olivia Brown', 'member', 'trading', 'Trader'),
  m('u_james', 'James Wilson', 'member', 'research', 'Analyst'),
  m('u_agnieszka', 'Agnieszka Wisniewska', 'member', 'research', 'Research engineer'),
  m('u_tomasz', 'Tomasz Lewandowski', 'member', 'platform', 'DevOps engineer'),
];

export function mockMembers(): { items: Member[] } {
  return { items: MOCK_MEMBERS };
}
