// Organization — teams, members, roles and agents with their sponsors. Owner: B18-dashboard-gov-approvals.
import { PageHeader } from '@/components/shell';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/governance/org',
  title: 'Organization',
  icon: 'Building',
  section: 'Governance',
  order: 30,
  minRole: 'member',
  shortcut: 'g m',
  description: 'Teams, members, roles and agents with their sponsors',
};

export default function OrgPage() {
  return <PageHeader title="Organization" icon="Building" subtitle="Teams, members, roles and agents with their sponsors" />;
}
