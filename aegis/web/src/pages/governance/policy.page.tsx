// Policy (UIG-04/05/08/09/12), flows F7/F5: bundled Monaco YAML editor with live server validation
// markers, semantic change list, role-aware Apply (owner applies, admin/member → approval), verdict
// probes that show WHICH VERDICTS FLIPPED on every reload, quick-edit judge levers, diff + impact
// preview, history + rollback. Reloads from elsewhere (a judge editing config/policy.yaml) refresh a
// clean editor and flash the changed lines; a dirty editor gets a rebase banner.
// Owner: B19-dashboard-gov-policy.
import { AlertOctagon, Columns2, Download, FileCode, GitCompare, History, Info, ParkingSquare, RefreshCw, Rows2, Trash2, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ApproverBadge } from '@/components/governance/ApproverBadge';
import { GovernanceToaster } from '@/components/governance/GovernanceToaster';
import { PersonaSwitcher } from '@/components/governance/PersonaSwitcher';
import { ApplyPanel } from '@/components/governance/policy/ApplyPanel';
import { ChangeList } from '@/components/governance/policy/ChangeList';
import { DiffHost, EditorHost } from '@/components/governance/policy/EditorHost';
import { toMarkers } from '@/components/governance/policy/editor-types';
import { HistoryList, SourceBadge } from '@/components/governance/policy/HistoryList';
import { ImpactPreview } from '@/components/governance/policy/ImpactPreview';
import { govNavigate } from '@/components/governance/policy/policy-toast';
import { ProbePanel } from '@/components/governance/policy/ProbePanel';
import { QuickEdits } from '@/components/governance/policy/QuickEdits';
import { usePolicyDraft } from '@/components/governance/policy/use-policy-draft';
import { ValidationStatus } from '@/components/governance/policy/ValidationStatus';
import { MockBadge, PageHeader, Panel, TimeAgo } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import type { PageMeta } from '@/lib/page';
import { cn } from '@/lib/utils';

export const meta: PageMeta = {
  path: '/governance/policy',
  title: 'Policy',
  icon: 'FileCode',
  section: 'Governance',
  order: 40,
  minRole: 'member',
  shortcut: 'g p',
  description: 'Live YAML policy: validate, diff, apply, history',
};

type Tab = 'editor' | 'diff' | 'history';
const TABS: { id: Tab; label: string; icon: typeof FileCode }[] = [
  { id: 'editor', label: 'Editor', icon: FileCode },
  { id: 'diff', label: 'Diff', icon: GitCompare },
  { id: 'history', label: 'History', icon: History },
];

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/yaml' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Banner({ tone, icon: Icon, children, actions, onClose }: { tone: 'approval' | 'warn' | 'block' | 'info'; icon: typeof Info; children: React.ReactNode; actions?: React.ReactNode; onClose?: () => void }) {
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-3 rounded-lg border px-3.5 py-2.5 text-sm',
        tone === 'approval' && 'border-approval/35 bg-approval/[0.08] text-text-1',
        tone === 'warn' && 'border-redact/35 bg-redact/[0.08] text-text-1',
        tone === 'block' && 'border-block/40 bg-block/[0.08] text-text-1',
        tone === 'info' && 'border-[var(--accent-border)] bg-[var(--accent-subtle)] text-text-1',
      )}
    >
      <Icon className={cn('size-4 shrink-0', tone === 'approval' ? 'text-approval' : tone === 'warn' ? 'text-redact' : tone === 'block' ? 'text-block' : 'text-accent-fg')} />
      <div className="min-w-0 flex-1">{children}</div>
      {actions}
      {onClose ? (
        <button type="button" onClick={onClose} className="rounded p-1 text-text-3 hover:bg-surface-3 hover:text-text-1" aria-label="Dismiss">
          <X className="size-3.5" />
        </button>
      ) : null}
    </div>
  );
}

export default function PolicyPage() {
  const d = usePolicyDraft();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.some((t) => t.id === params.get('tab')) ? params.get('tab') : 'editor') as Tab;
  const setTab = (t: Tab) => {
    const p = new URLSearchParams(params);
    if (t === 'editor') p.delete('tab');
    else p.set('tab', t);
    setParams(p, { replace: true });
  };
  const [sideBySide, setSideBySide] = useState(true);
  const a = d.active.data;
  const markers = useMemo(() => toMarkers(d.issues), [d.issues]);
  const lines = useMemo(() => (d.draft ?? '').split('\n').length, [d.draft]);
  const [flashNote, setFlashNote] = useState<{ version: number; lines: number } | null>(null);

  useEffect(() => {
    if (!d.externalFlash) return;
    setFlashNote(d.externalFlash);
    const t = window.setTimeout(() => setFlashNote(null), 6000);
    return () => window.clearTimeout(t);
  }, [d.externalFlash]);

  return (
    <div className="space-y-4">
      <GovernanceToaster />
      <PageHeader
        title="Policy"
        icon={FileCode}
        subtitle={
          a ? (
            <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="rounded-md border border-allow/30 bg-allow/10 px-1.5 py-px font-mono text-xs font-semibold text-allow">v{a.version}</span>
              <span>{a.profile}</span>
              <span className="text-text-4">·</span>
              <span>{a.controls_count} controls</span>
              <span className="text-text-4">·</span>
              <span>
                applied <TimeAgo ts={a.applied_at} /> by
              </span>
              <SourceBadge source={a.source} />
              {a.applied_by ? <span className="text-text-3">({a.applied_by})</span> : null}
              <span className="font-mono text-2xs text-text-4">sha {a.sha256.slice(0, 10)}</span>
            </span>
          ) : (
            'One YAML file, hot-reloaded: validate → self-test → atomic swap.'
          )
        }
        badge={d.active.isMock ? <MockBadge /> : null}
        actions={
          <div className="flex items-center gap-2">
            <PersonaSwitcher />
            <Button size="sm" variant="secondary" disabled={!a} onClick={() => a && download(`policy-v${a.version}.yaml`, a.yaml)}>
              <Download className="size-3.5" /> YAML
            </Button>
          </div>
        }
      />

      {d.pending ? (
        <Banner
          tone="approval"
          icon={ParkingSquare}
          onClose={d.dismissPending}
          actions={
            <Button size="xs" variant="secondary" onClick={() => govNavigate(`/governance/approvals?id=${encodeURIComponent(d.pending?.id ?? '')}`)}>
              Open approval
            </Button>
          }
        >
          Draft parked — waiting for <ApproverBadge level={d.pending.required_role} size="sm" className="mx-1 align-middle" /> approval{' '}
          <span className="font-mono text-approval">{d.pending.id}</span>
          {d.pending.rule_id ? <span className="text-text-3"> · rule {d.pending.rule_id}</span> : null}. Your draft is kept.
        </Banner>
      ) : null}

      {d.rebase ? (
        <Banner
          tone="warn"
          icon={RefreshCw}
          actions={
            <div className="flex gap-1.5">
              <Button size="xs" variant="secondary" onClick={d.doRebase}>
                <RefreshCw className="size-3" /> Rebase
              </Button>
              <Button size="xs" variant="danger-ghost" onClick={d.discard}>
                <Trash2 className="size-3" /> Discard draft
              </Button>
            </div>
          }
        >
          Policy moved to <span className="font-mono">v{d.rebase.to}</span> (by {d.rebase.source}) — your draft is based on <span className="font-mono">v{d.rebase.from}</span>.
        </Banner>
      ) : null}

      {d.rejected ? (
        <Banner tone="block" icon={AlertOctagon} onClose={d.dismissRejected}>
          <div>
            Policy rejected ({d.rejected.source}) — still on <span className="font-mono">v{d.rejected.kept_version}</span>
          </div>
          <ul className="mt-1 space-y-0.5 font-mono text-2xs text-block">
            {d.rejected.errors.slice(0, 3).map((e, i) => (
              <li key={i}>
                {e.line ? `line ${e.line}${e.col ? `:${e.col}` : ''} — ` : ''}
                {e.message}
              </li>
            ))}
          </ul>
        </Banner>
      ) : null}

      {flashNote ? (
        <Banner tone="info" icon={Info} onClose={() => setFlashNote(null)}>
          Reloaded <span className="font-mono">v{flashNote.version}</span> into the editor — {flashNote.lines} changed line{flashNote.lines === 1 ? '' : 's'} highlighted.
        </Banner>
      ) : null}

      <div className="flex items-center gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={cn(
              '-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors',
              tab === t.id ? 'border-accent-fg text-text-1' : 'border-transparent text-text-3 hover:text-text-1',
            )}
          >
            <t.icon className="size-3.5" />
            {t.label}
            {t.id === 'diff' && d.changes.length ? <span className="rounded-full bg-[var(--accent-subtle)] px-1.5 text-2xs text-accent-fg">{d.changes.length}</span> : null}
          </button>
        ))}
        {d.dirty ? <span className="ml-auto pr-1 text-2xs text-accent-fg">draft · base v{d.base?.version}</span> : null}
      </div>

      {/* Editor tab stays mounted (hidden) so the Monaco model keeps undo history across tab switches. */}
      <div className={cn('grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]', tab !== 'editor' && 'hidden')}>
        <Panel flush className="overflow-hidden" bodyClassName="flex flex-col">
          {d.draft !== null ? (
            <>
              <EditorHost
                initialValue={d.draft}
                onChange={d.setDraft}
                markers={markers}
                changedLines={d.changedLines}
                onSave={() => void d.apply('')}
                onReady={d.attachHandle}
                onEngine={d.setEngine}
                className="h-[calc(100vh-300px)] min-h-[520px]"
              />
              <ValidationStatus
                checking={d.checking}
                dirty={d.dirty}
                issues={d.issues}
                report={d.report}
                baseVersion={d.base?.version ?? null}
                lines={lines}
                engine={d.engine}
                isMock={d.checkMock}
                onJump={(l) => d.handle.current?.revealLine(l)}
              />
            </>
          ) : (
            <div className="space-y-2 p-4">
              {Array.from({ length: 14 }).map((_, i) => (
                <Skeleton key={i} className="h-4" style={{ width: `${30 + ((i * 37) % 60)}%` }} />
              ))}
            </div>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel title="Changes" description={d.dirty ? `${d.changes.length} semantic change${d.changes.length === 1 ? '' : 's'} vs v${d.base?.version}` : 'Draft is in sync'}>
            <ChangeList changes={d.changes} compact />
          </Panel>
          <Panel title="Apply">
            <ApplyPanel d={d} />
          </Panel>
          <Panel title="Verdict probes" description="Fixed dry-run interactions re-evaluated on every reload">
            <ProbePanel version={a?.version ?? null} isMock={d.active.isMock} />
          </Panel>
          <Panel title="Quick edits" description="Judge levers — they edit the draft only">
            <QuickEdits d={d} />
          </Panel>
        </div>
      </div>

      {tab === 'diff' ? (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel
              title="Semantic changes"
              actions={
                d.requiredRole ? (
                  <span className="inline-flex items-center gap-1.5 text-xs text-text-3">
                    required <ApproverBadge level={d.requiredRole} size="sm" />
                    {d.ruleId ? <span className="font-mono text-2xs">{d.ruleId}</span> : null}
                  </span>
                ) : null
              }
            >
              <ChangeList changes={d.changes} empty="The draft matches the active policy." />
            </Panel>
            <Panel title="Impact">
              <ImpactPreview d={d} />
            </Panel>
          </div>
          <Panel
            flush
            title={
              <span className="text-sm">
                Active <span className="font-mono">v{d.base?.version ?? '?'}</span> → draft
              </span>
            }
            actions={
              <div className="flex items-center gap-1">
                <Button size="xs" variant={sideBySide ? 'secondary' : 'ghost'} onClick={() => setSideBySide(true)}>
                  <Columns2 className="size-3" /> Side by side
                </Button>
                <Button size="xs" variant={!sideBySide ? 'secondary' : 'ghost'} onClick={() => setSideBySide(false)}>
                  <Rows2 className="size-3" /> Inline
                </Button>
              </div>
            }
          >
            {d.base && d.draft !== null ? (
              <DiffHost original={d.base.yaml} modified={d.draft} sideBySide={sideBySide} className="h-[560px]" originalLabel={`v${d.base.version}`} modifiedLabel="draft" />
            ) : null}
          </Panel>
        </div>
      ) : null}

      {tab === 'history' ? (
        <Panel flush title="Version history" description="Every reload is a version — from the editor, the file, an approval or a rollback" isMock={d.active.isMock}>
          <HistoryList d={d} onLoaded={() => setTab('editor')} />
        </Panel>
      ) : null}
    </div>
  );
}
