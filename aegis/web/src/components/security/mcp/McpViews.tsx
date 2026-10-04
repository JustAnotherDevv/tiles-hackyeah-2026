// MCP inventory: server cards, tool table with pin status, pinned-vs-current diff (rug pulls), admin actions.
import { AnimatePresence, motion } from 'framer-motion';
import { Check, ChevronRight, EyeOff, GitCompareArrows, Server, ShieldBan } from 'lucide-react';
import { Fragment, useState } from 'react';
import { Link } from 'react-router-dom';
import type { McpServerView } from '@/api/types';
import { DestBadge, RoleGate, TimeAgo } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { HashText, LockedAction } from '../common/atoms';
import { lineDiff, parseUnified, type DiffLine } from '../lib/lineDiff';
import type { McpToolDiff, McpToolViewX } from '../types';

export type ToolStatus = McpToolViewX['status'];

export const TOOL_STATUS: Record<ToolStatus, { label: string; cls: string }> = {
  approved: { label: 'pinned', cls: 'text-allow border-allow/30 bg-allow/10' },
  pending: { label: 'pending review', cls: 'text-redact border-redact/30 bg-redact/10' },
  changed: { label: 'rug pull · changed', cls: 'text-block border-block/40 bg-block/15' },
  quarantined: { label: 'hidden from model', cls: 'text-block border-block/30 bg-block/10' },
};

export function ToolStatusBadge({ status }: { status: ToolStatus }) {
  const s = TOOL_STATUS[status] ?? TOOL_STATUS.pending;
  return <span className={cn('inline-flex h-5 items-center whitespace-nowrap rounded-full border px-2 text-2xs font-medium', s.cls)}>{s.label}</span>;
}

export function McpServerCard({ server, active, onClick }: { server: McpServerView; active: boolean; onClick: () => void }) {
  const counts = server.tools.reduce<Record<string, number>>((m, t) => ({ ...m, [t.status]: (m[t.status] ?? 0) + 1 }), {});
  const alarm = (counts.changed ?? 0) + (counts.quarantined ?? 0) > 0;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex min-w-0 flex-col gap-2 rounded-xl border bg-card p-3 text-left shadow-card transition-all hover:-translate-y-px hover:border-border-strong',
        active ? 'border-accent-fg/60 ring-1 ring-accent-fg/30' : alarm ? 'border-block/40' : 'border-border',
      )}
    >
      <div className="flex items-center gap-2">
        <span className={cn('grid size-7 place-items-center rounded-lg border', alarm ? 'border-block/40 bg-block/10 text-block' : 'border-border bg-surface-2 text-text-2')}>
          <Server className="size-3.5" />
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-sm font-medium text-text-1" title={server.name}>
          {server.name}
        </span>
        <span className={cn('size-1.5 shrink-0 rounded-full', server.status === 'registered' ? 'bg-allow' : 'bg-block')} title={server.status} />
      </div>
      <div className="flex min-w-0 items-center gap-1.5">
        <DestBadge dest={server.destination} />
        <span className="truncate font-mono text-2xs text-text-3" title={server.url ?? 'stdio'}>
          {server.transport} · {server.status}
        </span>
      </div>
      <div className="flex flex-wrap gap-1 text-2xs">
        <span className="text-text-2">{server.tools.length} tools</span>
        {(['changed', 'quarantined', 'pending'] as ToolStatus[]).map((s) =>
          counts[s] ? (
            <span key={s} className={cn('rounded-full border px-1.5', TOOL_STATUS[s].cls)}>
              {counts[s]} {s}
            </span>
          ) : null,
        )}
      </div>
    </button>
  );
}

function DiffLines({ lines }: { lines: DiffLine[] }) {
  return (
    <pre className="overflow-x-auto rounded-lg border border-border bg-background py-1.5 font-mono text-[11.5px] leading-[18px]">
      {lines.map((l, i) => (
        <div key={i} className={cn('px-3', l.op === '+' ? 'bg-allow/10 text-allow' : l.op === '-' ? 'bg-block/10 text-block' : 'text-text-3')}>
          {l.op === '+' ? '+ ' : l.op === '-' ? '− ' : '  '}
          {l.text}
        </div>
      ))}
    </pre>
  );
}

export function ToolDiff({ tool, payloadDiff }: { tool: McpToolViewX; payloadDiff?: (McpToolDiff & { old_text?: string; new_text?: string }) | null }) {
  const diff = tool.diff ?? payloadDiff ?? null;
  const ext = payloadDiff ?? null;
  const lines = diff?.description_diff?.length ? parseUnified(diff.description_diff) : ext?.old_text !== undefined && ext?.new_text !== undefined ? lineDiff(ext.old_text, ext.new_text) : [];
  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-text-3">pinned</span>
        <HashText hash={tool.pinned_hash ?? null} />
        <ChevronRight className="size-3 text-text-4" />
        <span className="text-text-3">current</span>
        <HashText hash={tool.hash} className={tool.pinned_hash && tool.pinned_hash !== tool.hash ? 'text-block' : undefined} />
        {diff?.changed_fields?.length ? (
          <span className="ml-2 flex flex-wrap gap-1">
            {diff.changed_fields.map((f) => (
              <span key={f} className="rounded-[4px] border border-block/30 bg-block/10 px-1.5 font-mono text-2xs text-block">
                {f}
              </span>
            ))}
          </span>
        ) : null}
      </div>
      {lines.length ? <DiffLines lines={lines} /> : <div className="text-xs text-text-3">{diff ? 'Definition hash changed (no description diff available).' : 'Hash changed since the pin.'}</div>}
      {diff?.params_added?.length || diff?.params_removed?.length ? (
        <div className="flex flex-wrap gap-1.5 text-2xs">
          {(diff.params_added ?? []).map((p) => (
            <span key={`a${p}`} className="rounded-[4px] bg-allow/10 px-1.5 font-mono text-allow">
              + param {p}
            </span>
          ))}
          {(diff.params_removed ?? []).map((p) => (
            <span key={`r${p}`} className="rounded-[4px] bg-block/10 px-1.5 font-mono text-block">
              − param {p}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function McpToolTable({
  server,
  tools,
  flashKey,
  focusTool,
  busyKey,
  onApprove,
  onQuarantine,
  approvalFor,
}: {
  server: string;
  tools: McpToolViewX[];
  flashKey: string | null;
  focusTool: string | null;
  busyKey: string | null;
  onApprove: (tool: string) => void;
  onQuarantine: (tool: string) => void;
  approvalFor: (tool: string) => { id: string; diff: (McpToolDiff & { old_text?: string; new_text?: string }) | null } | null;
}) {
  const [open, setOpen] = useState<string | null>(() => focusTool ?? tools.find((t) => t.status === 'changed')?.name ?? null);
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b border-border text-left text-2xs uppercase tracking-[0.08em] text-text-3">
          <th className="px-4 py-2 font-medium">Tool</th>
          <th className="px-2 py-2 font-medium">Status</th>
          <th className="px-2 py-2 font-medium">Hash</th>
          <th className="px-2 py-2 font-medium">Description</th>
          <th className="px-2 py-2 font-medium">Seen</th>
          <th className="px-4 py-2 text-right font-medium">Actions</th>
        </tr>
      </thead>
      <tbody>
        {tools.map((t) => {
          const key = `${server}.${t.name}`;
          const changed = t.status === 'changed' || (t.pinned_hash && t.pinned_hash !== t.hash);
          const appr = approvalFor(t.name);
          const expanded = open === t.name;
          return (
            <Fragment key={t.name}>
              <tr
                id={`tool-${key}`}
                className={cn(
                  'border-b border-border-subtle align-top transition-colors',
                  flashKey === key && 'animate-row-in-block',
                  focusTool === t.name && 'bg-brand/10',
                  t.status === 'changed' && 'bg-block/[.04]',
                )}
              >
                <td className="px-4 py-2">
                  <button type="button" className="inline-flex items-center gap-1 font-mono text-[12px] font-medium text-text-1" onClick={() => setOpen(expanded ? null : t.name)}>
                    <ChevronRight className={cn('size-3 text-text-4 transition-transform', expanded && 'rotate-90')} />
                    {t.name}
                  </button>
                  {t.reasons.length ? (
                    <ul className="ml-4 mt-1 space-y-0.5">
                      {t.reasons.map((r) => (
                        <li key={r} className="text-2xs text-text-3">
                          · {r}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </td>
                <td className="px-2 py-2">
                  <ToolStatusBadge status={t.status} />
                  {appr ? (
                    <Link to={`/governance/approvals?id=${encodeURIComponent(appr.id)}`} className="mt-1 block text-2xs text-approval hover:underline">
                      Pending re-pin approval →
                    </Link>
                  ) : null}
                </td>
                <td className="px-2 py-2">
                  <HashText hash={t.hash} copy={false} />
                </td>
                <td className="max-w-[320px] px-2 py-2 text-text-2">
                  <span className="line-clamp-2" title={t.description_preview}>
                    {t.description_preview}
                  </span>
                </td>
                <td className="px-2 py-2 text-text-3">
                  <TimeAgo ts={t.last_seen} short />
                </td>
                <td className="px-4 py-2">
                  <div className="flex justify-end gap-1.5">
                    {changed ? (
                      <Button variant="ghost" size="xs" onClick={() => setOpen(expanded ? null : t.name)}>
                        <GitCompareArrows /> Diff
                      </Button>
                    ) : null}
                    <RoleGate min="admin" fallback={t.status !== 'approved' ? <LockedAction label="Approve" compact /> : null}>
                      {t.status !== 'approved' ? (
                        <Button variant="success" size="xs" disabled={busyKey === key} onClick={() => onApprove(t.name)}>
                          <Check /> Approve & re-pin
                        </Button>
                      ) : null}
                      {t.status !== 'quarantined' ? (
                        <Button variant="danger-ghost" size="xs" disabled={busyKey === key} onClick={() => onQuarantine(t.name)}>
                          <ShieldBan /> Quarantine
                        </Button>
                      ) : null}
                    </RoleGate>
                  </div>
                </td>
              </tr>
              <AnimatePresence initial={false}>
                {expanded ? (
                  <tr className="border-b border-border-subtle bg-background/40">
                    <td colSpan={6} className="px-4 py-3">
                      <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }}>
                        {changed || t.diff ? (
                          <ToolDiff tool={t} payloadDiff={appr?.diff ?? null} />
                        ) : (
                          <div className="flex items-start gap-2 text-xs text-text-2">
                            {t.status === 'quarantined' ? <EyeOff className="mt-0.5 size-3.5 text-block" /> : null}
                            <span className="whitespace-pre-wrap font-mono">{t.description_preview}</span>
                          </div>
                        )}
                      </motion.div>
                    </td>
                  </tr>
                ) : null}
              </AnimatePresence>
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
