// /security/mcp — MCP server/tool inventory with hash pins: poisoned tools hidden from the model, rug pulls
// (definition changed after pin) blocked until an admin re-pins. Deep link ?server=&tool=.
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { api, isApiRequestError } from '@/api/client';
import { useApi, useEvents } from '@/api/hooks';
import type { ApprovalsResponse, McpServerView, McpToolView } from '@/api/types';
import { KpiTile, PageHeader, Panel } from '@/components/shell';
import { Skeleton } from '@/components/ui/skeleton';
import { McpServerCard, McpToolTable, type ToolStatus } from '@/components/security/mcp';
import type { McpToolDiff, McpToolViewX } from '@/components/security/types';
import { mockMcpServers } from '@/mocks/security';
import type { PageMeta } from '@/lib/page';

export const meta: PageMeta = {
  path: '/security/mcp',
  title: 'MCP tools',
  icon: 'Plug',
  section: 'Security',
  order: 40,
  description: 'MCP servers and tool pins — poisoned tools hidden, rug pulls blocked',
};

const EMPTY_APPROVALS = (): ApprovalsResponse => ({ items: [], counts: { pending: 0, approved: 0, denied: 0, expired: 0, cancelled: 0 } });

export default function McpPage() {
  const [params, setParams] = useSearchParams();
  const servers = useApi<{ items: McpServerView[] }>('/api/mcp/servers', { mock: mockMcpServers, refreshOn: ['mcp.tool'], refreshMs: 15_000 });
  const approvals = useApi<ApprovalsResponse>('/api/approvals?kind=mcp_pin&status=pending', { mock: EMPTY_APPROVALS, refreshOn: ['approval.created', 'approval.updated'] });
  const [overrides, setOverrides] = useState<Record<string, ToolStatus>>({});
  const [flashKey, setFlashKey] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  useEvents(['mcp.tool'], (_n, data) => {
    const key = `${data.server}.${data.tool}`;
    setFlashKey(key);
    setOverrides((o) => {
      const n = { ...o };
      delete n[key];
      return n;
    });
    setTimeout(() => setFlashKey((k) => (k === key ? null : k)), 1800);
  });

  const items = useMemo(
    () =>
      (servers.data?.items ?? []).map((s) => ({
        ...s,
        tools: s.tools.map((t) => {
          const o = overrides[`${s.name}.${t.name}`];
          return (o ? { ...t, status: o } : t) as McpToolViewX;
        }),
      })),
    [servers.data, overrides],
  );
  const alarmServer = (items.find((s) => s.tools.some((t) => t.status === 'changed')) ?? items.find((s) => s.tools.some((t) => t.status === 'quarantined')))?.name;
  const selected = params.get('server') ?? alarmServer ?? items[0]?.name ?? null;
  const focusTool = params.get('tool');
  const server = items.find((s) => s.name === selected) ?? null;
  const allTools = items.flatMap((s) => s.tools);
  const count = (st: ToolStatus) => allTools.filter((t) => t.status === st).length;

  const approvalFor = (srv: string) => (tool: string) => {
    const a = (approvals.data?.items ?? []).find((x) => x.payload?.server === srv && x.payload?.tool === tool);
    if (!a) return null;
    const d = (a.payload?.diff ?? null) as (McpToolDiff & { old_text?: string; new_text?: string }) | null;
    return { id: a.id, diff: d };
  };

  const act = async (srv: string, tool: string, kind: 'approve' | 'quarantine') => {
    const key = `${srv}.${tool}`;
    const prevStatus = items.find((s) => s.name === srv)?.tools.find((t) => t.name === tool)?.status;
    let reason: string | null = null;
    if (kind === 'quarantine') {
      reason = window.prompt(`Quarantine ${key}? Optional reason:`, 'hidden instructions in description');
      if (reason === null) return;
    }
    setBusyKey(key);
    setOverrides((o) => ({ ...o, [key]: kind === 'approve' ? 'approved' : 'quarantined' }));
    try {
      const path = `/api/mcp/servers/${encodeURIComponent(srv)}/tools/${encodeURIComponent(tool)}/${kind}`;
      const body = kind === 'approve' ? { comment: 'Reviewed in dashboard' } : { reason };
      const mockTool = (): McpToolView => {
        const t = items.find((s) => s.name === srv)?.tools.find((x) => x.name === tool);
        return { ...(t as McpToolView), status: kind === 'approve' ? 'approved' : 'quarantined' };
      };
      const r = await api.post<McpToolView>(path, body, mockTool);
      toast.success(kind === 'approve' ? `${key} re-pinned · calls allowed again` : `${key} quarantined · hidden from the model`, { description: r.isMock ? 'demo data' : undefined });
      if (!r.isMock) void servers.refresh();
    } catch (e) {
      setOverrides((o) => {
        const n = { ...o };
        if (prevStatus) n[key] = prevStatus;
        else delete n[key];
        return n;
      });
      toast.error(isApiRequestError(e) ? e.message : `${kind} failed`);
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="MCP tools"
        icon="Plug"
        subtitle="Every tools/list is hashed and pinned. Poisoned descriptions are stripped before the model sees them; a tool whose definition changes after approval (rug pull) is blocked until an admin re-pins it."
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <KpiTile label="Servers" value={items.length} icon="Server" />
        <KpiTile label="Tools pinned" value={count('approved')} icon="Pin" tone="good" />
        <KpiTile label="Pending review" value={count('pending')} icon="Clock" tone={count('pending') ? 'warn' : 'neutral'} />
        <KpiTile label="Changed (rug pull)" value={count('changed')} icon="GitCompareArrows" tone={count('changed') ? 'bad' : 'neutral'} />
        <KpiTile label="Quarantined" value={count('quarantined')} icon="ShieldBan" tone={count('quarantined') ? 'bad' : 'neutral'} />
      </div>
      {servers.data ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
          {items.map((s) => (
            <McpServerCard
              key={s.name}
              server={s}
              active={s.name === selected}
              onClick={() =>
                setParams(
                  (p) => {
                    const n = new URLSearchParams(p);
                    n.set('server', s.name);
                    n.delete('tool');
                    return n;
                  },
                  { replace: true },
                )
              }
            />
          ))}
        </div>
      ) : (
        <Skeleton className="h-28 w-full" />
      )}
      {server ? (
        <Panel title={<span className="font-mono">{server.name}</span>} description={`${server.tools.length} tools · ${server.transport} · ${server.url ?? 'stdio'}`} flush isMock={servers.isMock}>
          <div className="overflow-x-auto">
            <McpToolTable
              key={server.name}
              server={server.name}
              tools={server.tools as McpToolViewX[]}
              flashKey={flashKey}
              focusTool={server.name === params.get('server') ? focusTool : null}
              busyKey={busyKey}
              onApprove={(t) => void act(server.name, t, 'approve')}
              onQuarantine={(t) => void act(server.name, t, 'quarantine')}
              approvalFor={approvalFor(server.name)}
            />
          </div>
        </Panel>
      ) : null}
    </div>
  );
}
