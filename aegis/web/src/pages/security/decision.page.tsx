// /security/decisions/:id — the decision trace as a full page (deep links from audit, approvals, toasts).
import { ArrowLeft } from '@/components/icons';
import { Link, useParams } from 'react-router-dom';
import { PageHeader, Panel } from '@/components/shell';
import { DecisionView } from '@/components/security/decision';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/security/decisions/:id',
  title: 'Decision trace',
  icon: 'ScanSearch',
  section: 'Security',
  nav: false,
  description: 'Why Aegis decided what it did for one request',
};

export default function DecisionPage() {
  const { id } = useParams();
  return (
    <div className="mx-auto max-w-[1100px]">
      <Link to="/security/live" className="mb-3 inline-flex min-h-8 items-center gap-1 text-xs text-text-3 hover:text-text-1">
        <ArrowLeft className="size-3.5" /> Live decisions
      </Link>
      <PageHeader title="Decision trace" subtitle={<span className="font-mono [overflow-wrap:anywhere]">{id}</span>} icon="ScanSearch" />
      <Panel bodyClassName="p-4 sm:p-5">{id ? <DecisionView key={id} decisionId={id} layout="page" /> : null}</Panel>
    </div>
  );
}
