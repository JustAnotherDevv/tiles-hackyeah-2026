// MCP inventory: server cards, tool table with pin status, pinned-vs-current diff (rug pulls), admin actions.
import { motion } from 'framer-motion';
import { Fragment, useState } from 'react';
import { Link } from 'react-router-dom';
import type { McpServerView } from '@/api/types';
import { Check, ChevronRight, EyeOff, GitCompareArrows, Server, ShieldBan } from '@/components/icons';
import { DestBadge, RoleGate, TimeAgo } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { HashText, LockedAction } from '../common/atoms';
import { lineDiff, parseUnified, type DiffLine } from '../lib/lineDiff';
import type { McpToolDiff, McpToolViewX } from '../types';

export type ToolStatus = McpToolViewX['status'];

export const TOOL_STATUS: Record<ToolStatus, { label: string; cls: string }> = {
  approved: { label: 'Pinned', cls: 'text-allow border-allow/30 bg-allow/10' },
  pending: { label: 'Pending review', cls: 'text-redact border-redact/30 bg-redact/10' },
  changed: { label: 'Changed since pin', cls: 'text-block border-block/40 bg-block/10' },
  quarantined: { label: 'Quarantined', cls: 'text-block border-block/30 bg-block/10' },
};

const COUNT_LABEL: Partial<Record<ToolStatus, string>> = { changed: 'changed', quarantined: 'quarantined', pending: 'pending' };

export function ToolStatusBadge({ status }: { status: ToolStatus }) {
  const s = TOOL_STATUS[status] ?? TOOL_STATUS.pending;
  return <span className={cn('inline-flex h-5 items-center whitespace-nowrap rounded-sm border px-1.5 text-2xs font-medium', s.cls)}>{s.label}</span>;
}

export function McpServerCard({ server, active, onClick }: { server: McpServerView; active: boolean; onClick: () => void }) {
  const counts = server.tools.reduce<Record<string, number>>((m, t) => ({ ...m, [t.status]: (m[t.status] ?? 0) + 1 }), {});
  const blocked = server.status === 'blocked';
  const alarm = (counts.changed ?? 0) + (counts.quarantined ?? 0) > 0 || blocked;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-3 text-left shadow-card transition-colors hover:border-border-strong',
        active ? 'border-accent-fg/60 ring-1 ring-accent-fg/30' : alarm ? 'border-block/40' : 'border-border',
      )}
    >
      <div className="flex min-w-0 items-center gap-2">
        <Server className={cn('size-3.5 shrink-0', alarm ? 'text-block' : 'text-text-3')} />
        <span className="min-w-0 flex-1 truncate font-mono text-[13px] font-medium text-text-1" title={server.name}>
          {server.name}
        </span>
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <DestBadge dest={server.destination} />
        <span className="truncate font-mono text-2xs text-text-3" title={server.url ?? 'stdio'}>
          {server.transport}
        </span>
        {server.status !== 'registered' ? <span className={cn('text-2xs font-medium', blocked ? 'text-block' : 'text-redact')}>{server.status}</span> : null}
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs">
        <span className="tabular text-text-2">{server.tools.length ? `${server.tools.length} ${server.tools.length === 1 ? 'tool' : 'tools'}` : 'No tools listed'}</span>
        {(['changed', 'quarantined', 'pending'] as ToolStatus[]).map((s) =>
          counts[s] ? (
            <span key={s} className={cn('tabular font-medium', s === 'pending' ? 'text-redact' : 'text-block')}>
              {counts[s]} {COUNT_LABEL[s]}
            </span>
          ) : null,
        )}
      </div>
    </button>
  );
}

function DiffLines({ lines }: { lines: DiffLine[] }) {
  return (
    <pre className="max-w-full overflow-x-auto rounded-md border border-border bg-background py-1.5 font-mono text-[11.5px] leading-[18px]">
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
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <span className="text-text-3">Pinned</span>
        <HashText hash={tool.pinned_hash ?? null} />
        <ChevronRight className="size-3 text-text-4" />
        <span className="text-text-3">Current</span>
        <HashText hash={tool.hash} className={tool.pinned_hash && tool.pinned_hash !== tool.hash ? 'text-block' : undefined} />
        {diff?.changed_fields?.length ? (
          <span className="flex flex-wrap items-center gap-1 sm:ml-2">
            <span className="text-text-3">Changed:</span>
            {diff.changed_fields.map((f) => (
              <span key={f} className="rounded-sm border border-block/30 bg-block/10 px-1.5 font-mono text-2xs text-block">
                {f}
              </span>
            ))}
          </span>
        ) : null}
      </div>
      {lines.length ? <DiffLines lines={lines} /> : <div className="text-xs text-text-3">{diff ? 'Definition hash changed; no description diff available.' : 'Definition hash changed since the pin.'}</div>}
      {diff?.params_added?.length || diff?.params_removed?.length ? (
        <div className="flex flex-wrap gap-1.5 text-2xs">
          {(diff.params_added ?? []).map((p) => (
            <span key={`a${p}`} className="rounded-sm bg-allow/10 px-1.5 font-mono text-allow">
              + param {p}
            </span>
          ))}
          {(diff.params_removed ?? []).map((p) => (
            <span key={`r${p}`} className="rounded-sm bg-block/10 px-1.5 font-mono text-block">
              − param {p}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** "tool poisoning indicators: AEGIS-TI-012, mcp.inj.hidden_tag" → label + id chips (feed signatures link to /security/threats). */
function Reason({ text }: { text: string }) {
  const m = /^([^:]{3,60}):\s+(.+)$/.exec(text);
  const ids = m ? m[2].split(/,\s*/).filter(Boolean) : [];
  if (!m || ids.length < 2 || !ids.every((x) => /^[\w.:-]+$/.test(x))) return <li className="break-words text-2xs text-text-3">{text}</li>;
  return (
    <li className="text-2xs text-text-3">
      <span>{m[1][0].toUpperCase() + m[1].slice(1)}</span>
      <span className="mt-1 flex flex-wrap gap-1">
        {ids.map((id) =>
          /^AEGIS-TI-\d+$/.test(id) ? (
            <Link key={id} to={`/security/threats?sig=${id}`} className="inline-flex items-center rounded-sm border border-border bg-surface-2 px-1 font-mono text-[10.5px] text-text-2 hover:border-border-strong hover:text-text-1 max-md:h-7 max-md:px-2" title="Open signature">
              {id}
            </Link>
          ) : (
            <span key={id} className="rounded-sm border border-border-subtle bg-surface-1 px-1 font-mono text-[10.5px] text-text-3">
              {id}
            </span>
          ),
        )}
      </span>
    </li>
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
    <table className="w-full table-fixed text-xs sm:table-auto">
      <thead>
        <tr className="border-y border-border text-left text-2xs text-text-3">
          <th className="px-4 py-2 font-medium">Tool</th>
          <th className="w-[118px] px-2 py-2 font-medium sm:w-auto">Status</th>
          <th className="hidden px-2 py-2 font-medium md:table-cell">Hash</th>
          <th className="hidden px-2 py-2 font-medium lg:table-cell">Description</th>
          <th className="hidden px-2 py-2 font-medium md:table-cell">Last seen</th>
          <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">Actions</th>
        </tr>
      </thead>
      <tbody>
        {tools.map((t) => {
          const key = `${server}.${t.name}`;
          const changed = t.status === 'changed' || Boolean(t.pinned_hash && t.pinned_hash !== t.hash);
          const appr = approvalFor(t.name);
          const expanded = open === t.name;
          const actions = (
            <div className="flex flex-wrap justify-start gap-1.5 sm:justify-end">
              {changed ? (
                <Button variant="ghost" size="xs" className="max-md:h-9" onClick={() => setOpen(expanded ? null : t.name)} aria-expanded={expanded}>
                  <GitCompareArrows /> Diff
                </Button>
              ) : null}
              <RoleGate min="admin" fallback={t.status !== 'approved' ? <LockedAction label="Approve" compact /> : null}>
                {t.status !== 'approved' ? (
                  <Button variant="success" size="xs" className="max-md:h-9" disabled={busyKey === key} onClick={() => onApprove(t.name)}>
                    <Check /> Approve and re-pin
                  </Button>
                ) : null}
                {t.status !== 'quarantined' ? (
                  <Button variant="danger-ghost" size="xs" className="max-md:h-9" disabled={busyKey === key} onClick={() => onQuarantine(t.name)}>
                    <ShieldBan /> Quarantine
                  </Button>
                ) : null}
              </RoleGate>
            </div>
          );
          return (
            <Fragment key={t.name}>
              <tr
                id={`tool-${key}`}
                className={cn(
                  'border-b border-border-subtle align-top',
                  flashKey === key && 'animate-row-in-block',
                  focusTool === t.name && 'bg-brand/10',
                  t.status === 'changed' && 'bg-block/[.04]',
                )}
              >
                <td className="min-w-0 px-4 py-2.5">
                  <button
                    type="button"
                    className="-my-1 inline-flex min-h-8 max-w-full items-center gap-1 text-left font-mono text-[12px] font-medium text-text-1 hover:text-accent-fg"
                    onClick={() => setOpen(expanded ? null : t.name)}
                    aria-expanded={expanded}
                  >
                    <ChevronRight className={cn('size-3 shrink-0 text-text-4 transition-transform duration-150', expanded && 'rotate-90')} />
                    <span className="truncate">{t.name}</span>
                  </button>
                  <div className="ml-4 mt-0.5 line-clamp-2 break-words text-text-3 lg:hidden">{t.description_preview}</div>
                  {t.reasons.length ? (
                    <ul className="ml-4 mt-1 space-y-1">
                      {t.reasons.map((r) => (
                        <Reason key={r} text={r} />
                      ))}
                    </ul>
                  ) : null}
                  <div className="ml-4 mt-2 sm:hidden">{actions}</div>
                </td>
                <td className="px-2 py-2.5">
                  <ToolStatusBadge status={t.status} />
                  {appr ? (
                    <Link to={`/governance/approvals?id=${encodeURIComponent(appr.id)}`} className="mt-1 block text-2xs text-approval hover:underline">
                      Re-pin approval pending
                    </Link>
                  ) : null}
                </td>
                <td className="hidden px-2 py-2.5 md:table-cell">
                  <HashText hash={t.hash} copy={false} />
                </td>
                <td className="hidden max-w-[360px] px-2 py-2.5 text-text-2 lg:table-cell">
                  <span className="line-clamp-2 break-words" title={t.description_preview}>
                    {t.description_preview}
                  </span>
                </td>
                <td className="hidden whitespace-nowrap px-2 py-2.5 text-text-3 md:table-cell">
                  <TimeAgo ts={t.last_seen} short />
                </td>
                <td className="hidden px-4 py-2.5 sm:table-cell">{actions}</td>
              </tr>
              {expanded ? (
                <tr className="border-b border-border-subtle bg-background/40">
                  <td colSpan={6} className="max-w-0 px-4 py-3">
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.15 }}>
                      {changed || t.diff ? (
                        <ToolDiff tool={t} payloadDiff={appr?.diff ?? null} />
                      ) : (
                        <div className="space-y-1.5">
                          {t.status === 'quarantined' ? (
                            <div className="flex items-center gap-1.5 text-2xs font-medium text-block">
                              <EyeOff className="size-3.5" /> Hidden from the model · original description shown for review
                            </div>
                          ) : (
                            <div className="text-2xs text-text-3">Description as pinned</div>
                          )}
                          <pre className="max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded-md border border-border bg-background px-3 py-2 font-mono text-[11.5px] leading-[18px] text-text-2">
                            {t.description_preview}
                          </pre>
                        </div>
                      )}
                    </motion.div>
                  </td>
                </tr>
              ) : null}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
