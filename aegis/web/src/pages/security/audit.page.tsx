// /security/audit — hash-chained audit log: Verify chain (animated walk), chain blocks, table, admin-only export.
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '@/api/client';
import { useApi } from '@/api/hooks';
import type { AuditEvent, AuditVerifyResult, Page } from '@/api/types';
import { PageHeader, Panel } from '@/components/shell';
import { Skeleton } from '@/components/ui/skeleton';
import { AuditTable, ChainBlocks, ChainVerifyCard, ExportButton } from '@/components/security/audit';
import { DecisionDrawer } from '@/components/security/decision';
import { useAgentsIndex, useControlsCatalog } from '@/components/security/hooks';
import { mockAuditPage, mockAuditVerify } from '@/mocks/security';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/security/audit',
  title: 'Audit log',
  icon: 'ScrollText',
  section: 'Security',
  order: 60,
  minRole: 'member',
  shortcut: 'g u',
  description: 'Hash-chained, tamper-evident record of every decision and change',
};

export default function AuditPage() {
  const [params] = useSearchParams();
  const seqParam = params.get('seq');
  const highlightSeq = seqParam && /^\d+$/.test(seqParam) ? Number(seqParam) : null;
  const path = highlightSeq !== null ? `/api/audit?limit=200&seq_from=${Math.max(0, highlightSeq - 20)}` : '/api/audit?limit=200';
  const audit = useApi<Page<AuditEvent>>(path, {
    mock: () => mockAuditPage(80),
    refreshOn: ['approval.updated', 'policy.applied', 'feed.updated', 'mcp.tool'],
    refreshMs: 5000,
  });
  const lastVerify = useApi<AuditVerifyResult>('/api/audit/verify', { mock: mockAuditVerify, refreshMs: 60_000 });
  const { catalog } = useControlsCatalog();
  const { agents } = useAgentsIndex();
  const [openDecision, setOpenDecision] = useState<string | null>(null);
  const events = useMemo(() => audit.data?.items ?? [], [audit.data]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Audit log"
        icon="ScrollText"
        subtitle="Every decision, policy change, feed update and approval — append-only and hash-chained (aegis.audit/1). Export to OCSF, then verify the chain."
        actions={<ExportButton controls={catalog.map((c) => c.id)} agents={agents.map((a) => a.id)} />}
      />
      <ChainVerifyCard verify={() => api.get<AuditVerifyResult>('/api/audit/verify', mockAuditVerify)} isMock={lastVerify.isMock} />
      <Panel title="Chain head" description="The last 8 records, each linked to its predecessor by prev_hash" isMock={audit.isMock}>
        {events.length ? <ChainBlocks events={events} brokenAt={lastVerify.data && !lastVerify.data.ok ? lastVerify.data.broken_at_seq : null} /> : <Skeleton className="h-20 w-full" />}
      </Panel>
      <Panel title="Events" description="Click a row for the full record · decision ids open the trace" flush isMock={audit.isMock}>
        {audit.data ? <AuditTable events={events} highlightSeq={highlightSeq} onOpenDecision={setOpenDecision} /> : <Skeleton className="m-4 h-64" />}
      </Panel>
      <DecisionDrawer decisionId={openDecision} open={Boolean(openDecision)} onOpenChange={(o) => (o ? undefined : setOpenDecision(null))} />
    </div>
  );
}
