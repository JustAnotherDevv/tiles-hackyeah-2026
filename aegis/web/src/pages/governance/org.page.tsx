// Organization (UIG-06 + UIG-10): org hero, Teams / Members / Agents / Roles & permissions tabs.
// Role changes, member active toggle and agent deactivate are gated on the viewer's role
// (whoami.permissions / capabilities); admin-initiated role changes become owner approvals.
// Owner: B18-dashboard-gov-approvals.
import { Bot, Building, Scale, Users } from '@/components/icons';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { Agent, Member } from '@/api/types';
import { govApi } from '@/components/governance/gov-api';
import { hasCapability, useApprovalRules, useDirectory, useOrg, useViewer, useWhoAmI } from '@/components/governance/hooks';
import { AgentsTable } from '@/components/governance/org/AgentsTable';
import { MembersTable } from '@/components/governance/org/MembersTable';
import { canManage, runOrgMutation } from '@/components/governance/org/org-actions';
import { RolesMatrix } from '@/components/governance/org/RolesMatrix';
import { TeamCards } from '@/components/governance/org/TeamCards';
import { PersonaSwitcher } from '@/components/governance/PersonaSwitcher';
import { EmptyState, KpiTile, MockBadge, PageHeader, Panel, Segmented } from '@/components/shell';
import { Button } from '@/components/ui/button';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/governance/org',
  title: 'Organization',
  icon: 'Building',
  section: 'Governance',
  order: 30,
  minRole: 'member',
  shortcut: 'g g',
  description: 'Teams, members, roles and agents with their sponsors',
};

type OrgTab = 'teams' | 'members' | 'agents' | 'roles';
const TABS: OrgTab[] = ['teams', 'members', 'agents', 'roles'];

export default function OrgPage() {
  const { viewerId, role } = useViewer();
  const org = useOrg();
  const dir = useDirectory();
  const rules = useApprovalRules();
  const who = useWhoAmI();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const raw = params.get('tab') as OrgTab | null;
  const tab: OrgTab = raw && TABS.includes(raw) ? raw : 'teams';
  const [busyId, setBusyId] = useState<string | null>(null);

  const setTab = (t: OrgTab) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        n.set('tab', t);
        return n;
      },
      { replace: true },
    );

  const manageGate = canManage(role, hasCapability(who.data, 'members.manage', role));
  const openApproval = (id: string) => navigate(`/governance/approvals?id=${encodeURIComponent(id)}`);
  const isMock = org.isMock || dir.isMock;
  const orgName = org.data?.org.name ?? 'Acme Capital';
  const counts = org.data?.counts ?? {
    members: dir.members.length,
    agents: dir.agents.length,
    teams: org.data?.teams.length ?? 0,
  };
  const sponsored = dir.agents.filter((a) => a.owner_member_id).length;

  const changeRole = async (m: Member, r: Member['role']) => {
    setBusyId(m.id);
    await runOrgMutation(() => govApi.patchMember(m.id, { role: r }, viewerId), {
      pendingId: `org-${m.id}`,
      success: `${m.name} is now ${r === 'admin' ? 'an' : 'a'} ${r}`,
      description: 'Audited as org.changed.',
      openApproval,
    });
    setBusyId(null);
    dir.refresh();
    org.refresh();
  };

  const setMemberActive = async (m: Member, active: boolean) => {
    setBusyId(m.id);
    await runOrgMutation(() => govApi.patchMember(m.id, { active }, viewerId), {
      pendingId: `org-${m.id}`,
      success: `${m.name} ${active ? 'reactivated' : 'deactivated'}`,
      description: active ? undefined : 'Their sessions stop at the next request. Audited as org.changed.',
      openApproval,
    });
    setBusyId(null);
    dir.refresh();
  };

  const setAgentActive = async (a: Agent, active: boolean) => {
    setBusyId(a.id);
    await runOrgMutation(() => govApi.patchAgent(a.id, { active }, viewerId), {
      pendingId: `org-${a.id}`,
      success: `${a.id} ${active ? 'reactivated' : 'deactivated'}`,
      description: active ? 'The agent can call models and tools again.' : 'Every further call from this agent is refused. Audited as org.changed.',
      openApproval,
    });
    setBusyId(null);
    dir.refresh();
  };

  return (
    <div>
      <PageHeader
        title="Organization"
        icon="Building"
        badge={isMock ? <MockBadge /> : undefined}
        subtitle={`${orgName}: people, the agents they sponsor, and who may approve what. Roles drive every approval route.`}
        actions={<PersonaSwitcher />}
      />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile
          label="Members"
          icon={Users}
          value={counts.members}
          loading={dir.loading && !dir.members.length}
          hint={`${dir.members.filter((m) => m.role !== 'member').length} admins & owners`}
        />
        <KpiTile label="Agents" icon={Bot} value={counts.agents} loading={dir.loading && !dir.agents.length} hint={`${sponsored} with a human sponsor`} />
        <KpiTile label="Teams" icon={Building} value={counts.teams} loading={org.loading && !org.data} hint="trading · research · platform" />
        <KpiTile label="Approval rules" icon={Scale} value={rules.all.length} loading={rules.loading && !rules.data} hint="first match wins" href="/governance/rules" />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div className="max-w-full overflow-x-auto">
        <Segmented<OrgTab>
          value={tab}
          onChange={setTab}
          ariaLabel="Organization view"
          options={[
            { value: 'teams', label: 'Teams' },
            { value: 'members', label: `Members · ${dir.members.length}` },
            { value: 'agents', label: `Agents · ${dir.agents.length}` },
            { value: 'roles', label: 'Roles and permissions' },
          ]}
        />
        </div>
        {!manageGate.ok && (tab === 'members' || tab === 'agents') ? (
          <span className="text-xs text-text-3">Read-only for your role. Locked actions show the reason on hover.</span>
        ) : null}
      </div>

      {org.error && !org.data && dir.members.length === 0 ? (
        <Panel>
          <EmptyState icon="CloudOff" title="Could not load the organization" hint={org.error.message} action={<Button size="sm" variant="outline" onClick={() => { org.refresh(); dir.refresh(); }}>Retry</Button>} />
        </Panel>
      ) : tab === 'teams' ? (
        <TeamCards teams={org.data?.teams ?? []} members={dir.members} agents={dir.agents} viewerId={viewerId} />
      ) : tab === 'members' ? (
        <Panel flush title="Members" description="Role changes to or from owner need an owner; admins' promotions are sent for owner approval." isMock={dir.isMock}>
          <MembersTable
            members={dir.members}
            viewerId={viewerId}
            viewerRole={role}
            manageGate={manageGate}
            busyId={busyId}
            onRole={(m, r) => void changeRole(m, r)}
            onActive={(m, v) => void setMemberActive(m, v)}
          />
        </Panel>
      ) : tab === 'agents' ? (
        <Panel
          flush
          title="Agents"
          description="Service identities. The sponsor approves the agent's self-level items and is excluded from its admin/owner approvals."
          isMock={dir.isMock}
        >
          <AgentsTable agents={dir.agents} memberById={dir.memberById} viewerId={viewerId} manageGate={manageGate} busyId={busyId} onActive={(a, v) => void setAgentActive(a, v)} />
        </Panel>
      ) : (
        <Panel flush title="Roles and permissions" description="From the contract semantics; the last row is computed from the live approval rules." isMock={rules.isMock}>
          <RolesMatrix viewerRole={role} rules={rules.all} />
        </Panel>
      )}
    </div>
  );
}
