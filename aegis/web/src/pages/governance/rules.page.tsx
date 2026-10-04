// Approval rules (UIG-06 + UIG-07) — "who can approve what": the live first-match rule tables from
// policy (`rules` + `config_rules` + defaults) and the "Who would approve this?" route simulator,
// whose matched rule is highlighted in the tables. Owner: B18-dashboard-gov-approvals.
import { Info } from '@/components/icons';
import { useState } from 'react';
import type { ApprovalRoute } from '@/api/types';
import { ApproverBadge } from '@/components/governance/ApproverBadge';
import { useApprovalRules, useDirectory, useViewer } from '@/components/governance/hooks';
import { fmtTtl } from '@/components/governance/lib/format-gov';
import { PersonaSwitcher } from '@/components/governance/PersonaSwitcher';
import { RouteSimulator } from '@/components/governance/rules/RouteSimulator';
import { RulesTable } from '@/components/governance/rules/RulesTable';
import { EmptyState, MockBadge, PageHeader, Panel } from '@/components/shell';
import { Button } from '@/components/ui/button';
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
  const rules = useApprovalRules();
  const dir = useDirectory();
  const { viewer } = useViewer();
  const [route, setRoute] = useState<ApprovalRoute | null>(null);
  const d = rules.data?.defaults;
  const hi = route?.rule_id ?? null;
  const hiInConfig = Boolean(hi && rules.data?.config_rules.some((r) => r.id === hi));

  return (
    <div>
      <PageHeader
        title="Approval rules"
        icon="Scale"
        badge={rules.isMock ? <MockBadge /> : undefined}
        subtitle="Who can approve what, live from the active policy. Edit the approvals block in the policy editor to change it."
        actions={<PersonaSwitcher />}
      />

      <Panel
        className="mb-4"
        title="Who would approve this?"
        description="Simulate a request against the router the gateway uses (POST /api/approvals/simulate). The matched rule is highlighted below."
        bordered
      >
        <RouteSimulator dir={dir} viewer={viewer} onRoute={setRoute} />
      </Panel>

      <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface-1 px-3 py-2.5 text-[12.5px] text-text-2 sm:px-4">
        <Info className="size-4 shrink-0 text-text-3" />
        <span>
          <span className="text-text-1">First match wins</span>, top to bottom; a multi-change proposal takes the highest level. No match →
        </span>
        {d ? (
          <>
            <span className="inline-flex items-center gap-1">
              actions <ApproverBadge level={d.default_approver} size="sm" />
            </span>
            <span className="inline-flex items-center gap-1">
              config <ApproverBadge level={d.default_config_approver} size="sm" />
            </span>
            <span className="whitespace-nowrap text-text-3">· requests expire after {fmtTtl(d.ttl_s)}</span>
          </>
        ) : null}
      </div>

      {rules.error && !rules.data ? (
        <Panel>
          <EmptyState icon="CloudOff" title="Could not load approval rules" hint={rules.error.message} action={<Button size="sm" variant="outline" onClick={() => rules.refresh()}>Retry</Button>} />
        </Panel>
      ) : (
        <div className="grid min-w-0 gap-4 2xl:grid-cols-2">
          <Panel
            flush
            title="Agent actions and budget overrides"
            description={`${rules.data?.rules.length ?? 0} rules · approvals.rules`}
            isMock={rules.isMock}
            className={hi && !hiInConfig ? 'ring-1 ring-approval/30' : undefined}
          >
            <RulesTable rules={rules.data?.rules ?? []} highlightId={hiInConfig ? null : hi} defaultTtl={d?.ttl_s ?? 900} />
          </Panel>
          <Panel
            flush
            title="Config changes"
            description={`${rules.data?.config_rules.length ?? 0} rules · approvals.config_rules · policy edits, budget raises, kill switch`}
            isMock={rules.isMock}
            className={hiInConfig ? 'ring-1 ring-approval/30' : undefined}
          >
            <RulesTable rules={rules.data?.config_rules ?? []} highlightId={hiInConfig ? hi : null} defaultTtl={d?.ttl_s ?? 900} />
          </Panel>
        </div>
      )}
    </div>
  );
}
