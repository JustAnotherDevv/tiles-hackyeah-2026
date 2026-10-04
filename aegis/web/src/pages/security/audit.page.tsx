// /security/audit — hash-chained audit log: chain integrity (verify), chain head, record table, admin-only export.
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '@/api/client';
import { useApi } from '@/api/hooks';
import type { AuditEvent, AuditVerifyResult, Page } from '@/api/types';
import { EmptyState, PageHeader, Panel } from '@/components/shell';
import { Button } from '@/components/ui/button';
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

  const brokenAt = lastVerify.data && !lastVerify.data.ok ? lastVerify.data.broken_at_seq : null;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Audit log"
        icon="ScrollText"
        subtitle="Append-only, hash-chained record (aegis.audit/1) of every decision, policy change, feed update and approval. Export as JSONL, CSV or OCSF."
        actions={<ExportButton controls={catalog.map((c) => c.id)} agents={agents.map((a) => a.id)} />}
      />
      <ChainVerifyCard verify={() => api.get<AuditVerifyResult>('/api/audit/verify', mockAuditVerify)} last={lastVerify.data} isMock={lastVerify.isMock} />
      {audit.error && !audit.data ? (
        <Panel>
          <EmptyState
            icon="CircleAlert"
            title="Audit log unavailable"
            hint={audit.error.message}
            action={
              <Button size="sm" variant="secondary" onClick={() => void audit.refresh()}>
                Retry
              </Button>
            }
          />
        </Panel>
      ) : (
        <>
          <Panel title="Chain head" description="Latest 8 records, each linked to its predecessor by prev_hash" isMock={audit.isMock}>
            {audit.data ? (
              events.length ? (
                <ChainBlocks events={events} brokenAt={brokenAt} />
              ) : (
                <p className="text-xs text-text-3">The chain is empty.</p>
              )
            ) : (
              <Skeleton className="h-[86px] w-full" />
            )}
          </Panel>
          <Panel title="Records" description="Select a row for the full record; decision ids open the trace" flush isMock={audit.isMock}>
            {audit.data ? <AuditTable events={events} highlightSeq={highlightSeq} onOpenDecision={setOpenDecision} /> : <Skeleton className="m-4 h-64" />}
          </Panel>
        </>
      )}
      <DecisionDrawer decisionId={openDecision} open={Boolean(openDecision)} onOpenChange={(o) => (o ? undefined : setOpenDecision(null))} />
    </div>
  );
}
