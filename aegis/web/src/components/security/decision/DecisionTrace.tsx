// Decision trace (tabs Trace | Wire | Findings | Raw) — the explainability view behind every live-feed row.
import {
  ArrowDownRight,
  Ban,
  CircleDot,
  Database,
  EyeOff,
  Fingerprint,
  GitMerge,
  Hash,
  LogIn,
  Send,
  ShieldCheck,
  Sparkles,
  UserCheck,
  Wand2,
  type LucideIcon,
} from 'lucide-react';
import { useMemo, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { Action, DecisionDetail, Finding } from '@/api/types';
import { ActionBadge, DestBadge, IdentityChip, JsonView } from '@/components/shell';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ACTION_COLORS } from '@/lib/colors';
import { fmtMs, fmtNum, fmtUsd } from '@/lib/format';
import { cn } from '@/lib/utils';
import { ControlChip, CopyButton, EntityChip, HashText, KeyValue, SectionLabel, SeverityBadge } from '../common/atoms';
import { VersionStamp } from '../common/VersionStamp';
import { buildTrace, serverTiming } from '../lib/trace';
import { RedactionDiff } from '../redaction/RedactionDiff';
import type { CatalogControl, TraceModel } from '../types';
import { InjectionExplain } from './InjectionExplain';
import { PipelineWaterfall, type RevealState } from './PipelineWaterfall';

export type TraceTab = 'trace' | 'wire' | 'findings' | 'raw';

const REASON_ICON: Record<Action, LucideIcon> = { allow: ShieldCheck, log: ShieldCheck, redact: EyeOff, require_approval: UserCheck, block: Ban };

export function ReasonCard({ detail, className }: { detail: Pick<DecisionDetail, 'action' | 'reason' | 'control_id' | 'policy_version' | 'feed_serial' | 'score' | 'threshold'>; className?: string }) {
  const c = ACTION_COLORS[detail.action];
  const Icon = REASON_ICON[detail.action];
  return (
    <div className={cn('flex gap-2.5 rounded-[10px] border px-3.5 py-3 text-[13px] leading-[19px]', className)} style={{ borderColor: c.border, background: `linear-gradient(0deg, ${c.bg}, ${c.bg}), var(--surface-2)` }}>
      <Icon className="mt-0.5 size-4 shrink-0" style={{ color: c.fg }} />
      <div className="min-w-0">
        <div className="text-text-1">{detail.reason || (detail.action === 'allow' ? 'No control fired — request allowed.' : '—')}</div>
        <div className="mt-1 font-mono text-[11.5px] text-text-3">
          {detail.control_id ?? 'no control fired'}
          {detail.score !== null && detail.score !== undefined ? ` · score ${detail.score.toFixed(2)}${detail.threshold !== null && detail.threshold !== undefined ? ` vs ${detail.threshold}` : ''}` : ''} · policy v{detail.policy_version} · feed #{detail.feed_serial ?? '—'}
        </div>
      </div>
    </div>
  );
}

export function MiniKpis({ items }: { items: [string, ReactNode][] }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {items.map(([l, v]) => (
        <div key={l} className="rounded-lg border border-border bg-surface-1 px-3 py-2">
          <div className="text-2xs text-text-3">{l}</div>
          <div className="mt-0.5 text-[15px] font-semibold tabular text-text-1">{v}</div>
        </div>
      ))}
    </div>
  );
}

function Milestone({ icon: Icon, title, children, tone }: { icon: LucideIcon; title: string; children: ReactNode; tone?: string }) {
  return (
    <div className="grid grid-cols-[22px_1fr] items-start gap-3 border-b border-border-subtle py-2 last:border-0">
      <span className="grid size-[22px] place-items-center rounded-[7px] border border-border bg-surface-2 text-text-3" style={tone ? { color: tone } : undefined}>
        <Icon className="size-3" />
      </span>
      <div className="min-w-0">
        <div className="text-[12.5px] font-medium leading-4">{title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-text-2">{children}</div>
      </div>
    </div>
  );
}

function SliverBar({ aegisMs, upstreamMs }: { aegisMs: number; upstreamMs: number }) {
  const total = aegisMs + upstreamMs;
  const pct = total > 0 ? (aegisMs / total) * 100 : 0;
  return (
    <div className="w-full">
      <div className="flex h-2 overflow-hidden rounded-full bg-surface-3">
        <div className="h-full bg-accent-fg" style={{ width: `${Math.max(0.6, pct)}%` }} />
        <div className="h-full flex-1 bg-sky-500/30" />
      </div>
      <div className="mt-1 font-mono text-2xs text-text-3">
        Aegis {fmtMs(aegisMs)} of {fmtMs(total)} = {pct.toFixed(pct < 1 ? 2 : 1)} %
      </div>
    </div>
  );
}

function allFindings(detail: DecisionDetail): Finding[] {
  return (detail.decisions ?? []).flatMap((d) => d.findings ?? []);
}

export function FindingsTable({ findings }: { findings: Finding[] }) {
  if (!findings.length) return <div className="py-8 text-center text-xs text-text-3">No findings were recorded for this decision.</div>;
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border bg-surface-2/50 text-left text-2xs uppercase tracking-wider text-text-3">
            <th className="px-3 py-2 font-medium">Control</th>
            <th className="px-2 py-2 font-medium">Detector / signature</th>
            <th className="px-2 py-2 font-medium">Category</th>
            <th className="px-2 py-2 font-medium">Entity</th>
            <th className="px-2 py-2 font-medium">Severity</th>
            <th className="px-2 py-2 text-right font-medium">Score</th>
            <th className="px-3 py-2 font-medium">Excerpt (masked)</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((f, i) => {
            const sig = (f.meta?.signature_id as string | undefined) ?? (f.control_id.startsWith('SIG-') ? f.detector : null);
            return (
              <tr key={i} className="border-b border-border-subtle last:border-0">
                <td className="px-3 py-1.5">
                  <ControlChip id={f.control_id} />
                </td>
                <td className="px-2 py-1.5 font-mono">
                  {sig ? (
                    <Link className="text-accent-fg hover:underline" to={`/security/threats?sig=${encodeURIComponent(sig)}`}>
                      {sig}
                    </Link>
                  ) : (
                    f.detector
                  )}
                </td>
                <td className="px-2 py-1.5 text-text-2">{f.category}</td>
                <td className="px-2 py-1.5">{f.entity ? <EntityChip entity={f.entity} dataClass={f.data_class} /> : <span className="text-text-4">—</span>}</td>
                <td className="px-2 py-1.5">
                  <SeverityBadge severity={f.severity} />
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular">{f.score?.toFixed(2)}</td>
                <td className="max-w-[220px] truncate px-3 py-1.5 font-mono text-text-3" title={f.excerpt ?? ''}>
                  {f.excerpt ?? '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ServerTimingBox({ trace, detail }: { trace: TraceModel; detail: DecisionDetail }) {
  const text = [
    `X-Aegis-Decision: ${detail.action}`,
    `X-Aegis-Decision-Id: ${detail.id}`,
    `X-Aegis-Policy-Version: ${detail.policy_version}`,
    `X-Aegis-Feed-Serial: ${detail.feed_serial ?? '-'}`,
    serverTiming(trace, detail.latency_ms ?? 0, detail.upstream_ms),
  ].join('\n');
  return (
    <div className="relative whitespace-pre-wrap break-all rounded-[10px] border border-border bg-background px-3 py-2.5 font-mono text-[11.5px] leading-[18px] text-text-2">
      <span className="absolute right-1.5 top-1.5">
        <CopyButton value={text} label="headers" />
      </span>
      {text}
    </div>
  );
}

function stripWire(detail: DecisionDetail): Omit<DecisionDetail, 'wire'> {
  const { wire: _w, ...rest } = detail;
  return rest;
}

function TraceBody({ detail, trace, current, reveal, animate }: { detail: DecisionDetail; trace: TraceModel; current?: { policyVersion: number | null; feedSerial: number | null }; reveal?: Record<string, RevealState>; animate: boolean }) {
  const routeMut = (detail.mutations ?? []).find((m) => m.target === 'route');
  const strips = (detail.mutations ?? []).filter((m) => m.target !== 'route');
  const entities = detail.entities ?? [];
  return (
    <div>
      <SectionLabel right={`${trace.ranCount} of ${trace.stages.length} controls ran${trace.shortCircuitAfter ? ` · short-circuit at ${trace.shortCircuitAfter}` : ''}`}>Decision trace</SectionLabel>
      <Milestone icon={LogIn} title="Ingress · identity & attribution">
        <IdentityChip identity={detail.identity} showTeam />
        <span className="text-text-4">·</span>
        <span className="font-mono text-text-3">{detail.source}</span>
        <span className="text-text-4">·</span>
        <span className="font-mono text-text-3">{detail.session_id}</span>
        <DestBadge dest={detail.destination} />
      </Milestone>
      {detail.action_type || detail.amount_usd !== null || detail.tool_name ? (
        <Milestone icon={Sparkles} title="Enrich · governed action">
          {detail.tool_name ? <span className="rounded-[5px] border border-border bg-surface-2 px-1.5 font-mono text-2xs">{detail.tool_name}</span> : null}
          {detail.action_type ? <span className="rounded-[5px] border border-border bg-surface-2 px-1.5 font-mono text-2xs">{detail.action_type}</span> : null}
          {detail.amount_usd !== null && detail.amount_usd !== undefined ? <span className="font-mono text-text-1">{fmtUsd(detail.amount_usd)}</span> : null}
        </Milestone>
      ) : null}
      <div className="mt-1">
        <PipelineWaterfall trace={trace} reveal={reveal} animate={animate} />
      </div>
      <div className="mt-2">
        <InjectionExplain decisions={detail.decisions} />
      </div>
      <div className="mt-2">
        <Milestone icon={GitMerge} title="Combine · block > approval > redact > log > allow">
          {trace.enforceRanked.filter((s) => s.action !== 'allow').length === 0 ? <span className="text-text-3">no enforce-mode hits → allow</span> : null}
          {trace.enforceRanked
            .filter((s) => s.action && s.action !== 'allow')
            .map((s) => (
              <span key={s.key} className={cn('inline-flex items-center gap-1', s.primary && 'rounded-md bg-surface-3 px-1 py-0.5')}>
                <ActionBadge action={s.action as Action} size="sm" />
                <span className="font-mono text-2xs">{s.controlId}</span>
                {s.primary ? <span className="text-2xs text-accent-fg">primary</span> : null}
              </span>
            ))}
          {trace.monitorHits.map((s) => (
            <span key={`m-${s.key}`} className="inline-flex items-center gap-1 opacity-80">
              <ActionBadge action={(s.action ?? 'block') as Action} size="sm" monitor />
              <span className="font-mono text-2xs">{s.controlId}</span>
            </span>
          ))}
        </Milestone>
        {detail.approval_id ? (
          <Milestone icon={UserCheck} title="Approval" tone={ACTION_COLORS.require_approval.fg}>
            <Link to={`/governance/approvals?id=${encodeURIComponent(detail.approval_id)}`} className="font-mono text-approval hover:underline">
              {detail.approval_id} →
            </Link>
            <span className="text-text-3">routed by approval rules; the agent retries after a decision</span>
          </Milestone>
        ) : null}
        <Milestone icon={Wand2} title="Transform">
          {detail.redaction_count ? (
            <>
              <span>{detail.redaction_count} redactions</span>
              {entities.slice(0, 8).map((e) => (
                <EntityChip key={e} entity={e} />
              ))}
            </>
          ) : (
            <span className="text-text-3">no redactions</span>
          )}
          {routeMut ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-downgrade/40 bg-downgrade/10 px-2 text-2xs text-downgrade">
              <ArrowDownRight className="size-3" />
              downgraded → {String(routeMut.value ?? '')}
            </span>
          ) : null}
          {strips.slice(0, 6).map((m, i) => (
            <span key={i} className="rounded-[5px] border border-border bg-surface-2 px-1.5 font-mono text-2xs text-text-3" title={m.reason ?? ''}>
              {m.op === 'remove' ? '−' : '='} {m.target}:{m.path}
            </span>
          ))}
        </Milestone>
        <Milestone icon={Hash} title="Record · hash-chained audit">
          {detail.audit_seq !== null && detail.audit_seq !== undefined ? (
            <Link className="font-mono text-accent-fg hover:underline" to={`/security/audit?seq=${detail.audit_seq}`}>
              seq {detail.audit_seq}
            </Link>
          ) : (
            <span className="text-text-3">{detail.dry_run ? 'dry run — not recorded' : 'pending'}</span>
          )}
          <HashText hash={detail.audit_hash} />
          <VersionStamp policyVersion={detail.policy_version} feedSerial={detail.feed_serial} current={current} />
        </Milestone>
        <Milestone icon={Send} title="Upstream">
          {detail.upstream_ms !== null && detail.upstream_ms !== undefined ? (
            <div className="flex w-full flex-col gap-1.5">
              <div className="flex flex-wrap gap-2 font-mono text-2xs text-text-3">
                <span>{detail.model ?? detail.destination?.name}</span>
                <span>· {fmtMs(detail.upstream_ms)}</span>
                {detail.tokens !== null ? <span>· {fmtNum(detail.tokens)} tok</span> : null}
                {detail.cost_usd !== null ? <span>· {fmtUsd(detail.cost_usd)}</span> : null}
              </div>
              <SliverBar aegisMs={detail.latency_ms ?? 0} upstreamMs={detail.upstream_ms} />
            </div>
          ) : (
            <span className="text-text-3">{detail.action === 'block' ? 'not called — blocked in-line' : detail.action === 'require_approval' ? 'held for approval' : 'no upstream timing (local tool / dry run)'}</span>
          )}
        </Milestone>
      </div>
    </div>
  );
}

export function DecisionTrace({
  detail,
  catalog,
  current,
  tab,
  onTabChange,
  reveal,
  animate = true,
  timings,
}: {
  detail: DecisionDetail;
  catalog: CatalogControl[];
  current?: { policyVersion: number | null; feedSerial: number | null };
  tab: TraceTab;
  onTabChange: (t: TraceTab) => void;
  reveal?: Record<string, RevealState>;
  animate?: boolean;
  timings?: { control_id: string; ms: number }[];
}) {
  const trace = useMemo(() => buildTrace(detail, catalog, { timings }), [detail, catalog, timings]);
  const findings = useMemo(() => allFindings(detail), [detail]);
  return (
    <div className="space-y-3">
      <ReasonCard detail={detail} />
      <MiniKpis
        items={[
          ['Aegis overhead', fmtMs(detail.latency_ms)],
          ['Upstream', detail.upstream_ms !== null ? fmtMs(detail.upstream_ms) : '—'],
          ['Cost', detail.cost_usd !== null ? fmtUsd(detail.cost_usd) : '$0'],
          ['Tokens', detail.tokens !== null ? fmtNum(detail.tokens) : '—'],
        ]}
      />
      <Tabs value={tab} onValueChange={(v) => onTabChange(v as TraceTab)} className="gap-3">
        <TabsList>
          <TabsTrigger value="trace">
            <CircleDot className="size-3.5" /> Trace
          </TabsTrigger>
          <TabsTrigger value="wire">
            <Fingerprint className="size-3.5" /> Wire{detail.redaction_count ? ` · ${detail.redaction_count}` : ''}
          </TabsTrigger>
          <TabsTrigger value="findings">
            <Database className="size-3.5" /> Findings{findings.length ? ` · ${findings.length}` : ''}
          </TabsTrigger>
          <TabsTrigger value="raw">Raw</TabsTrigger>
        </TabsList>
        <TabsContent value="trace">
          <TraceBody detail={detail} trace={trace} current={current} reveal={reveal} animate={animate} />
          <SectionLabel>Identifiers</SectionLabel>
          <KeyValue
            items={[
              ['Decision', <span key="d" className="inline-flex items-center gap-1">{detail.id}<CopyButton value={detail.id} label="decision id" /></span>],
              ['Request', <span key="r" className="inline-flex items-center gap-1">{detail.request_id}<CopyButton value={detail.request_id} label="request id" /></span>],
              ['Session', detail.session_id],
              ['Source · surface', `${detail.source} · ${detail.surface} (${detail.direction})`],
              ['Destination', `${detail.destination?.name ?? '—'} (${detail.destination?.dest_class ?? '—'})`],
              ['Model / tool', detail.tool_name ?? detail.model ?? '—'],
              ['Versions', <VersionStamp key="v" policyVersion={detail.policy_version} feedSerial={detail.feed_serial} current={current} />],
            ]}
          />
          <SectionLabel>Response headers</SectionLabel>
          <ServerTimingBox trace={trace} detail={detail} />
        </TabsContent>
        <TabsContent value="wire">
          <RedactionDiff wire={detail.wire} redactions={detail.redactions ?? []} destination={detail.destination} latencyMs={detail.latency_ms} preview={detail.preview} />
        </TabsContent>
        <TabsContent value="findings">
          <FindingsTable findings={findings} />
        </TabsContent>
        <TabsContent value="raw">
          <div className="mb-2 text-2xs text-text-3">Decision record without the in-memory wire view (raw text never leaves the gateway's memory).</div>
          <JsonView value={stripWire(detail)} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
