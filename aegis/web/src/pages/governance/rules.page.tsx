// Approval rules — "who can approve what" + routing simulator. Owner: B18-dashboard-gov-approvals.
import { PageHeader } from '@/components/shell';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/governance/rules',
  title: 'Approval rules',
  icon: 'Scale',
  section: 'Governance',
  order: 35,
  minRole: 'member',
  shortcut: 'g r',
  description: 'Who can approve what — and a routing simulator',
};

export default function RulesPage() {
  return <PageHeader title="Approval rules" icon="Scale" subtitle="Who can approve what — and a routing simulator" />;
}
