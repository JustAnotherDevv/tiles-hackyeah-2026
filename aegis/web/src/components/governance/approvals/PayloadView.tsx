// "What will execute" — rendered from the BOUND payload (`payload.bound`, the exact parameters the
// grant's HMAC fingerprint covers), never from agent prose. ASI09: agent-written text (agent_note,
// justification/reason args) is shown separately, labelled "Written by the agent — untrusted" and
// styled unlike any system text; risk signals (control, Aegis reason, rule matched, failed checks)
// come from Aegis. Config/budget → changes, patch ops, unified diff; unknown shapes → JsonView.
// Field mapping: server `review` block (aegis/approvals/serialize_review.py) via lib/approval-review.
// Owner: B18 (+ ASI-TRUST-UI).
import { ArrowRight, Bot, Fingerprint, ShieldAlert, ShieldOff, TriangleAlert } from '@/components/icons';
import type { ReactNode } from 'react';
import type { ApprovalRequest, PolicyChange } from '@/api/types';
import { JsonView } from '@/components/shell';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';
import { isAgentTextKey, reviewOf, type ApprovalReview } from '../lib/approval-review';
import { changeKindMeta, displayTitle, fmtMoney } from '../lib/format-gov';
import { unifiedLineKind } from '../lib/line-diff';

// Payload keys rendered by a dedicated block (everything else falls into "Other payload fields").
const KNOWN = new Set([
  'tool_name', 'tool_args', 'justification', 'changes', 'patch', 'unified', 'base_version', 'reason', 'before', 'after', 'description_before', 'description_after',
  // real backend action shape (actions/drafts.py + approvals/service.py)
  'tool', 'args', 'agent_note', 'bound', 'explain', 'checks', 'facts', 'control_id', 'routing', 'replay_of',
]);

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
          <span className="font-mono text-text-3">
            {k}
            {isAgentTextKey(k) ? (
              <span className="ml-1.5 rounded-sm border border-dashed border-redact/50 px-1 align-middle font-sans text-[10px] text-redact" title="Free text written by the agent — untrusted">
                agent-written
              </span>
            ) : null}
          </span>
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

const AGENT_HATCH = { backgroundImage: 'repeating-linear-gradient(135deg, transparent 0 8px, var(--redact-subtle) 8px 16px)' };

/** Agent-written text: dashed amber frame, hatched background, robot icon, quoted pre-wrapped plain text. */
export function AgentTextBlock({ review }: { review: ApprovalReview }) {
  if (review.agent_text.length === 0) return null;
  return (
    <div data-testid="agent-text" role="note" aria-label="Written by the agent — untrusted" className="rounded-lg border-2 border-dashed border-redact/50 p-3" style={AGENT_HATCH}>
      <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[12px] font-semibold text-redact">
        <Bot className="size-3.5" />
        Written by the agent — untrusted
        <span className="font-normal text-text-3">· not verified by Aegis; decide on the bound action, not on this text</span>
      </div>
      <ul className="space-y-1.5">
        {review.agent_text.map((t) => (
          <li key={`${t.field}:${t.text}`} className="rounded-md bg-background/80 px-2.5 py-1.5">
            <div className="mb-0.5 font-mono text-[10.5px] text-text-3">{t.field}</div>
            <div className="whitespace-pre-wrap break-words font-mono text-[12.5px] italic text-text-2">“{t.text}”</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function fmtTtl(s: number | null): string | null {
  if (s === null || s <= 0) return null;
  return s >= 3600 ? `${Math.round(s / 360) / 10} h` : s >= 60 ? `${Math.round(s / 60)} min` : `${s} s`;
}

/** The exact bound action the grant authorizes (system text, from Aegis). */
export function BoundActionBox({ req, review, compact = false }: { req: ApprovalRequest; review: ApprovalReview; compact?: boolean }) {
  const b = review.bound;
  const ttl = fmtTtl(b.grant_ttl_s);
  const rows: [string, ReactNode][] = [];
  if (b.amount_usd !== null) rows.push(['amount', <span className="tabular text-approval">{fmtMoney(b.amount_usd)}</span>]);
  if (b.destination) rows.push(['destination', <Placeholderized text={b.destination} />]);
  if (b.url && !b.destination?.startsWith('url:')) rows.push(['url', <Placeholderized text={`${b.method ? `${b.method.toUpperCase()} ` : ''}${b.url}`} />]);
  if (b.mcp_server) rows.push(['server', b.mcp_server]);
  if (b.surface) rows.push(['surface', b.surface]);
  if (b.resource && !b.destination?.includes(b.resource)) rows.push(['resource', b.resource]);
  return (
    <div data-testid="bound-action" className="rounded-lg border border-border-strong bg-background p-3">
      <div className="mb-2.5 flex flex-wrap items-center gap-2 border-b border-border-subtle pb-2.5 font-mono text-[12.5px]">
        <span className="text-text-3">tool</span>
        <span className="font-medium text-text-1">{b.tool ?? req.action_type}</span>
        {review.destructive ? (
          <span className="inline-flex items-center gap-1 rounded-sm border border-block/40 bg-block/10 px-1.5 font-sans text-2xs font-medium text-block" title={review.destructive_reason ?? undefined}>
            <TriangleAlert className="size-3" /> destructive
          </span>
        ) : null}
        {b.amount_usd !== null ? <span className="ml-auto rounded-sm bg-approval/10 px-1.5 text-approval tabular">{fmtMoney(b.amount_usd)}</span> : null}
      </div>
      {rows.length ? (
        <div className="mb-2.5 grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-1.5 border-b border-border-subtle pb-2.5 text-[12.5px]">
          {rows.map(([k, v]) => (
            <div key={k} className="contents">
              <span className="text-text-3">{k}</span>
              <span className="break-all font-mono text-text-1">{v}</span>
            </div>
          ))}
        </div>
      ) : null}
      {compact ? null : b.args ? <ArgsTable args={b.args} /> : <div className="text-xs text-text-3">No arguments bound</div>}
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border-subtle pt-2 text-2xs text-text-3">
        <span className="inline-flex items-center gap-1" title={b.fingerprint ?? 'no fingerprint'}>
          <Fingerprint className="size-3" />
          {b.params_hash ? (
            <>
              params hash <span className="font-mono text-text-2">{b.params_hash}</span>
            </>
          ) : (
            'no parameter fingerprint'
          )}
        </span>
        <span>{b.present ? 'grant bound to these exact parameters' : 'parameters as requested'}</span>
        {b.max_uses !== null ? <span>{b.max_uses === 1 ? 'single use' : `${b.max_uses} uses`}</span> : null}
        {ttl ? <span>grant valid {ttl}</span> : null}
      </div>
    </div>
  );
}

/** Why Aegis held the call — control, Aegis's own reason, routing rule matched, failed checks. */
export function RiskSignals({ review, facts }: { review: ApprovalReview; facts?: Record<string, unknown> | null }) {
  const r = review.risk;
  const factRows = Object.entries(facts ?? {}).filter(([, v]) => v !== null && v !== undefined && typeof v !== 'object').slice(0, 12);
  if (!r.control_id && !r.reason && !r.rule_id && r.failed_checks.length === 0 && !r.flood_cap && !review.destructive && factRows.length === 0) return null;
  return (
    <div data-testid="risk-signals" className="space-y-2 rounded-lg border border-border bg-surface-1 p-3 text-[12.5px]">
      <div className="flex flex-wrap items-center gap-1.5">
        <ShieldAlert className="size-3.5 text-approval" />
        {r.control_id ? <span className="rounded-sm border border-border bg-surface-2 px-1.5 font-mono text-2xs text-text-1">{r.control_id}</span> : null}
        {r.rule_id ? (
          <span className="rounded-sm border border-border bg-surface-2 px-1.5 font-mono text-2xs text-text-2" title={r.rule_description ?? undefined}>
            rule {r.rule_id}
          </span>
        ) : null}
        {r.flood_cap ? <span className="rounded-sm border border-block/30 bg-block/10 px-1.5 text-2xs text-block">flood cap: {r.flood_cap}</span> : null}
        {r.replay_of ? <span className="rounded-sm border border-block/30 bg-block/10 px-1.5 text-2xs text-block">replay of another grant</span> : null}
      </div>
      {r.reason ? <div className="text-text-1">{r.reason}</div> : null}
      {r.rule_when ? (
        <div className="text-xs text-text-3">
          matched when <span className="font-mono text-text-2">{r.rule_when}</span>
        </div>
      ) : null}
      {review.destructive_reason ? <div className="text-xs text-block">Destructive: {review.destructive_reason} — approving needs a typed confirmation.</div> : null}
      {r.failed_checks.length ? (
        <ul className="space-y-0.5 text-xs">
          {r.failed_checks.map((c, i) => (
            <li key={`${c.name}-${i}`} className="flex flex-wrap gap-1.5">
              <span className="text-block">✕</span>
              <span className="text-text-1">{c.name ?? 'check'}</span>
              {c.detail ? <span className="text-text-3">{c.detail}</span> : null}
              {c.param ? <span className="font-mono text-text-4">{c.param}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {factRows.length ? (
        <div className="grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-0.5 border-t border-border-subtle pt-2 text-xs">
          {factRows.map(([k, v]) => (
            <div key={k} className="contents">
              <span className="font-mono text-text-3">{k}</span>
              <span className="break-all font-mono text-text-2">{fmtVal(v)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function PayloadView({ req, hideActionLabel = false }: { req: ApprovalRequest; hideActionLabel?: boolean }) {
  const p = req.payload ?? {};
  const review = reviewOf(req);
  const isActionShape = Boolean(review.bound.tool || review.bound.args || review.bound.present);
  const changes = Array.isArray(p.changes) ? (p.changes as PolicyChange[]) : null;
  const patch = Array.isArray(p.patch) ? (p.patch as { op?: string; path?: string; value?: unknown }[]) : null;
  const unified = typeof p.unified === 'string' && p.unified.trim() ? p.unified : null;
  // Action payloads: `reason` is Aegis's own (shown under risk signals). Other kinds: the human proposer's.
  const proposerReason = req.kind !== 'action' && typeof p.reason === 'string' ? p.reason : null;
  const before = typeof p.description_before === 'string' ? p.description_before : null;
  const after = typeof p.description_after === 'string' ? p.description_after : null;
  const rest = Object.fromEntries(Object.entries(p).filter(([k]) => !KNOWN.has(k)));
  const nothing = !isActionShape && !changes && !patch && !unified && !before && !after;

  return (
    <div className="space-y-4">
      {isActionShape ? (
        <div>
          {hideActionLabel ? null : <Label>What will execute</Label>}
          <BoundActionBox req={req} review={review} />
        </div>
      ) : null}

      {isActionShape || review.risk.control_id ? (
        <div>
          <Label>Why Aegis held this</Label>
          <RiskSignals review={review} facts={isRecord(p.facts) ? p.facts : null} />
        </div>
      ) : null}

      <AgentTextBlock review={review} />

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

      {proposerReason ? (
        <div>
          <Label>Proposer's reason</Label>
          <div className="border-l-2 border-border-strong pl-3 text-[13px] text-text-2">“{proposerReason}”</div>
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
