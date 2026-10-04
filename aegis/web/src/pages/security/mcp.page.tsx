// /security/mcp — MCP server/tool inventory with hash pins: poisoned tools hidden from the model, rug pulls
// (definition changed after pin) blocked until an admin re-pins. Deep link ?server=&tool=.
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { api, isApiRequestError } from '@/api/client';
import { useApi, useEvents } from '@/api/hooks';
import type { ApprovalsResponse, McpServerView, McpToolView } from '@/api/types';
import { EmptyState, KpiTile, PageHeader, Panel } from '@/components/shell';
import { CloudOff, Server as ServerIcon } from '@/components/icons';
import { Skeleton } from '@/components/ui/skeleton';
import { McpServerCard, McpToolTable, type ToolStatus } from '@/components/security/mcp';
import type { McpToolDiff, McpToolViewX } from '@/components/security/types';
import { isMockForced } from '@/components/security/env';
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

  const clearOverride = (key: string) =>
    setOverrides((o) => {
      if (!(key in o)) return o;
      const n = { ...o };
      delete n[key];
      return n;
    });

  const act = async (srv: string, tool: string, kind: 'approve' | 'quarantine') => {
    const key = `${srv}.${tool}`;
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
      if (r.isMock && !isMockForced()) {
        // Mock fallback outside demo mode means the gateway never received the change.
        clearOverride(key);
        toast.error('Not applied · gateway offline', { description: `${key} keeps its current pin status.` });
        return;
      }
      toast.success(kind === 'approve' ? `${key} re-pinned · calls allowed again` : `${key} quarantined · hidden from the model`, { description: r.isMock ? 'Demo data' : undefined });
      if (!r.isMock) {
        // Reconcile with the server even if the mcp.tool SSE event is missed.
        await servers.refresh();
        clearOverride(key);
      }
    } catch (e) {
      clearOverride(key);
      toast.error(isApiRequestError(e) ? e.message : 'Not applied · gateway offline', { description: isApiRequestError(e) ? undefined : `${key} keeps its current pin status.` });
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="MCP tools"
        icon="Plug"
        subtitle="Each tool definition is hashed and pinned on first use. Poisoned tools are hidden from the model; a tool whose definition changes after approval is blocked until an admin re-pins it."
      />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <KpiTile label="Servers" value={items.length} icon="Server" loading={!servers.data} />
        <KpiTile label="Tools pinned" value={count('approved')} icon="Pin" loading={!servers.data} />
        <KpiTile label="Pending review" value={count('pending')} icon="Clock" tone={count('pending') ? 'warn' : 'neutral'} loading={!servers.data} />
        <KpiTile label="Changed since pin" value={count('changed')} icon="GitCompareArrows" tone={count('changed') ? 'bad' : 'neutral'} loading={!servers.data} />
        <KpiTile label="Quarantined" value={count('quarantined')} icon="ShieldBan" tone={count('quarantined') ? 'bad' : 'neutral'} loading={!servers.data} className="col-span-2 sm:col-span-1" />
      </div>
      {servers.data && !items.length ? (
        <Panel>
          <EmptyState icon={ServerIcon} title="No MCP servers registered" hint="Servers appear here after their first tools/list passes through the gateway." />
        </Panel>
      ) : servers.data ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 lg:grid-cols-4 2xl:grid-cols-5">
          {items.map((s) => (
            <McpServerCard
              key={s.name}
              server={s}
              active={s.name === selected}
              onClick={() => {
                setParams(
                  (p) => {
                    const n = new URLSearchParams(p);
                    n.set('server', s.name);
                    n.delete('tool');
                    return n;
                  },
                  { replace: true },
                );
                // Below md the tool table sits under the card list: bring it into view so the tap has a visible result.
                if (window.matchMedia('(max-width: 767px)').matches)
                  setTimeout(() => document.getElementById('mcp-server-detail')?.scrollIntoView({ block: 'start', behavior: 'smooth' }), 50);
              }}
            />
          ))}
        </div>
      ) : servers.error ? (
        <Panel>
          <EmptyState icon={CloudOff} title="MCP inventory unavailable" hint={servers.error.message} />
        </Panel>
      ) : (
        <Skeleton className="h-28 w-full" />
      )}
      {server ? (
        <div id="mcp-server-detail" className="scroll-mt-4">
          <Panel
            title={<span className="font-mono">{server.name}</span>}
            description={`${server.tools.length} ${server.tools.length === 1 ? 'tool' : 'tools'} · ${server.transport}${server.url ? ` · ${server.url}` : ''}`}
            flush
            isMock={servers.isMock}
          >
            {!server.tools.length ? (
              <EmptyState
                icon={ServerIcon}
                title={server.status === 'blocked' ? 'Server blocked' : 'No tools listed'}
                hint={server.status === 'blocked' ? 'Calls to this server are refused by policy, so its tools are never offered to the model.' : 'This server has not returned a tools/list response through the gateway yet.'}
                className="border-t border-border-subtle"
              />
            ) : (
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
            )}
          </Panel>
        </div>
      ) : null}
    </div>
  );
}
