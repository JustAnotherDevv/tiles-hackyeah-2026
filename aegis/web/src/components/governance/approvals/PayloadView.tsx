// "Requested action" — rendered from the BOUND payload, never from agent prose (approvals.yaml
// `display` rules). Tool calls → args table; config/budget → changes, patch ops, unified diff;
// agent justification labelled untrusted; unknown shapes → JsonView. Owner: B18.
import { ArrowRight, ShieldOff, TriangleAlert } from '@/components/icons';
import type { ReactNode } from 'react';
import type { ApprovalRequest, PolicyChange } from '@/api/types';
import { JsonView } from '@/components/shell';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';
import { changeKindMeta, displayTitle, fmtMoney } from '../lib/format-gov';
import { unifiedLineKind } from '../lib/line-diff';

const KNOWN = new Set(['tool_name', 'tool_args', 'justification', 'changes', 'patch', 'unified', 'base_version', 'reason', 'before', 'after', 'description_before', 'description_after']);

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return JSON.stringify(v);
}

function Placeholderized({ text }: { text: string }) {
  // highlight reversible placeholders like [EMAIL_1] so approvers see redaction happened
  const parts = text.split(/(\[[A-Z_]+(?:_\d+)?\]|\[REDACTED:[A-Z_]+\])/g);
  return (
    <>
      {parts.map((p, i) =>
        /^\[(?:[A-Z_]+(?:_\d+)?|REDACTED:[A-Z_]+)\]$/.test(p) ? (
          <span key={i} className="rounded-xs bg-redact/10 px-0.5 text-redact">
            {p}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

function ArgsTable({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args);
  if (entries.length === 0) return <div className="text-xs text-text-3">No arguments</div>;
  return (
    <div className="grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-1.5 text-[12.5px]">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <span className="font-mono text-text-3">{k}</span>
          {isRecord(v) || Array.isArray(v) ? (
            <JsonView value={v} />
          ) : (
            <span className={cn('break-all font-mono text-text-1', k.includes('amount') && 'text-approval')}>
              {k.includes('amount') && typeof v === 'number' ? fmtMoney(v) : <Placeholderized text={fmtVal(v)} />}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

export function ChangeRows({ changes }: { changes: PolicyChange[] }) {
  return (
    <ul className="space-y-1.5">
      {changes.map((c, i) => {
        const meta = changeKindMeta(c.kind, c.loosening);
        const Icon = meta.loosening ? ShieldOff : resolveIcon(meta.icon);
        return (
          <li
            key={`${c.path}-${i}`}
            className={cn(
              'flex items-start gap-2.5 rounded-md border px-3 py-2',
              meta.loosening ? 'border-block/30 bg-block/5' : meta.tone === 'tighten' ? 'border-allow/25 bg-allow/5' : 'border-border bg-surface-2',
            )}
          >
            <Icon className={cn('mt-0.5 size-3.5 shrink-0', meta.loosening ? 'text-block' : meta.tone === 'tighten' ? 'text-allow' : 'text-text-3')} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 text-[12.5px]">
                <span className="font-medium text-text-1">{c.summary ? displayTitle(c.summary) : meta.label}</span>
                {meta.loosening ? <span className="rounded-sm border border-block/30 px-1.5 text-2xs text-block">loosening</span> : null}
                {c.increase_pct !== null && c.increase_pct !== undefined ? <span className="tabular text-2xs text-text-3">+{Math.round(c.increase_pct)}%</span> : null}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 font-mono text-2xs text-text-3">
                <span className="truncate">{c.path}</span>
                <span className="text-text-4">·</span>
                <span className="text-block/90 line-through decoration-block/40">{fmtVal(c.before)}</span>
                <ArrowRight className="size-3" />
                <span className="text-allow">{fmtVal(c.after)}</span>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function UnifiedDiff({ text, className }: { text: string; className?: string }) {
  return (
    <pre className={cn('overflow-auto rounded-lg border border-border bg-background p-3 font-mono text-[12px] leading-[19px]', className)}>
      {text.split('\n').map((line, i) => {
        const k = unifiedLineKind(line);
        return (
          <div
            key={i}
            className={cn(
              '-mx-3 px-3',
              k === 'add' && 'bg-allow/10 text-allow',
              k === 'del' && 'bg-block/10 text-block',
              k === 'hunk' && 'text-accent-fg',
              k === 'meta' && 'text-text-3',
              k === 'ctx' && 'text-text-2',
            )}
          >
            {line || ' '}
          </div>
        );
      })}
    </pre>
  );
}

function Label({ children }: { children: ReactNode }) {
  return <div className="mb-2 text-2xs font-medium uppercase tracking-wider text-text-3">{children}</div>;
}

export function PayloadView({ req, hideActionLabel = false }: { req: ApprovalRequest; hideActionLabel?: boolean }) {
  const p = req.payload ?? {};
  const toolName = typeof p.tool_name === 'string' ? p.tool_name : null;
  const toolArgs = isRecord(p.tool_args) ? p.tool_args : null;
  const changes = Array.isArray(p.changes) ? (p.changes as PolicyChange[]) : null;
  const patch = Array.isArray(p.patch) ? (p.patch as { op?: string; path?: string; value?: unknown }[]) : null;
  const unified = typeof p.unified === 'string' && p.unified.trim() ? p.unified : null;
  const justification = typeof p.justification === 'string' ? p.justification : null;
  const reason = typeof p.reason === 'string' ? p.reason : null;
  const before = typeof p.description_before === 'string' ? p.description_before : null;
  const after = typeof p.description_after === 'string' ? p.description_after : null;
  const rest = Object.fromEntries(Object.entries(p).filter(([k]) => !KNOWN.has(k)));
  const nothing = !toolName && !toolArgs && !changes && !patch && !unified && !before && !after;

  return (
    <div className="space-y-4">
      {toolName || toolArgs ? (
        <div>
          {hideActionLabel ? null : <Label>Requested action</Label>}
          <div className="rounded-lg border border-border bg-background p-3">
            {toolName ? (
              <div className="mb-2.5 flex items-center gap-2 border-b border-border-subtle pb-2.5 font-mono text-[12.5px]">
                <span className="text-text-3">tool</span>
                <span className="font-medium text-text-1">{toolName}</span>
                {req.amount_usd !== null ? <span className="ml-auto rounded-sm bg-approval/10 px-1.5 text-approval tabular">{fmtMoney(req.amount_usd)}</span> : null}
              </div>
            ) : null}
            {toolArgs ? <ArgsTable args={toolArgs} /> : null}
          </div>
        </div>
      ) : null}

      {changes && changes.length > 0 ? (
        <div>
          <Label>Proposed changes</Label>
          <ChangeRows changes={changes} />
        </div>
      ) : null}

      {patch && patch.length > 0 ? (
        <div>
          <Label>Patch operations</Label>
          <div className="space-y-1 rounded-lg border border-border bg-background p-3 font-mono text-[12px]">
            {patch.map((op, i) => (
              <div key={i} className="flex flex-wrap gap-2">
                <span className="text-accent-fg">{op.op ?? 'set'}</span>
                <span className="text-text-2">{op.path}</span>
                {op.value !== undefined ? (
                  <>
                    <span className="text-text-4">=</span>
                    <span className="text-allow">{fmtVal(op.value)}</span>
                  </>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {unified ? (
        <div>
          <Label>Policy diff</Label>
          <UnifiedDiff text={unified} />
        </div>
      ) : null}

      {before || after ? (
        <div>
          <Label>Tool description changed</Label>
          <div className="grid gap-2 md:grid-cols-2">
            <div className="rounded-lg border border-block/25 bg-block/5 p-3 text-xs text-text-2">
              <div className="mb-1 text-2xs uppercase tracking-wider text-block">pinned</div>
              {before ?? '—'}
            </div>
            <div className="rounded-lg border border-allow/25 bg-allow/5 p-3 text-xs text-text-2">
              <div className="mb-1 text-2xs uppercase tracking-wider text-allow">now</div>
              {after ?? '—'}
            </div>
          </div>
        </div>
      ) : null}

      {reason ? (
        <div>
          <Label>Proposer's reason</Label>
          <div className="border-l-2 border-border-strong pl-3 text-[13px] text-text-2">“{reason}”</div>
        </div>
      ) : null}

      {justification ? (
        <div>
          <Label>
            <span className="inline-flex items-center gap-1.5">
              <TriangleAlert className="size-3 text-redact" />
              Agent-supplied justification (untrusted)
            </span>
          </Label>
          <div className="rounded-md border border-dashed border-redact/30 bg-redact/5 px-3 py-2 text-[13px] italic text-text-2">“{justification}”</div>
        </div>
      ) : null}

      {Object.keys(rest).length > 0 ? (
        <div>
          <Label>{nothing ? 'Payload' : 'Other payload fields'}</Label>
          <JsonView value={rest} />
        </div>
      ) : nothing ? (
        <div className="text-xs text-text-3">No payload bound to this request.</div>
      ) : null}
    </div>
  );
}
