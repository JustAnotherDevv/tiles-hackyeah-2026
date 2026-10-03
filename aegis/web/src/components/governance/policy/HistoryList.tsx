// Policy history (UIG-08): versions with source badge, actor and summary; selecting one shows a diff
// vN → active, with "Load into editor" (as a draft) and "Roll back to vN" (reason dialog → POST
// /api/policy/rollback, governed like apply). Owner: B19-dashboard-gov-policy.
import { FileInput, History, Loader2, Undo2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useApi } from '@/api/hooks';
import type { PolicyVersionInfo } from '@/api/types';
import { useDirectory } from '@/components/governance/hooks';
import { EmptyState, TimeAgo } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { DiffHost } from './EditorHost';
import { policyApi, policyMocks, policyPaths, useMockStoreRefresh } from './policy-api';
import type { PolicyDraft } from './use-policy-draft';

const SOURCE_TONE: Record<string, string> = {
  file: 'border-sky-500/30 bg-sky-500/10 text-sky-300',
  api: 'border-[var(--accent-border)] bg-[var(--accent-subtle)] text-accent-fg',
  approval: 'border-approval/30 bg-approval/10 text-approval',
  rollback: 'border-redact/30 bg-redact/10 text-redact',
  startup: 'border-border bg-surface-2 text-text-3',
};

export function SourceBadge({ source }: { source: string }) {
  return <span className={cn('rounded border px-1.5 py-px text-[10px] font-medium uppercase tracking-wide', SOURCE_TONE[source] ?? SOURCE_TONE.startup)}>{source}</span>;
}

export function HistoryList({ d, onLoaded }: { d: PolicyDraft; onLoaded: () => void }) {
  const dir = useDirectory();
  const res = useApi<{ items: PolicyVersionInfo[] }>(policyPaths.history, { mock: policyMocks.history, refreshOn: ['policy.applied'], refreshMs: 30000 });
  useMockStoreRefresh(res.refresh, res.isMock);
  const items = [...(res.data?.items ?? [])].sort((a, b) => b.version - a.version);
  const activeV = d.active.data?.version ?? null;
  const [sel, setSel] = useState<number | null>(null);
  const [yaml, setYaml] = useState<{ v: number; yaml: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [rb, setRb] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (sel === null && items.length > 1) setSel(items[1].version);
  }, [items, sel]);

  useEffect(() => {
    if (sel === null) return;
    let live = true;
    setLoading(true);
    policyApi
      .version(sel)
      .then((r) => live && setYaml({ v: sel, yaml: r.data.yaml }))
      .catch(() => live && setYaml(null))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [sel]);

  if (!res.data) return <div className="p-6 text-xs text-text-3">{res.error ? res.error.message : 'Loading history…'}</div>;
  if (items.length === 0) return <EmptyState icon="History" title="No versions yet" />;
  const selInfo = items.find((i) => i.version === sel) ?? null;
  const isActive = sel !== null && sel === activeV;

  return (
    <div className="grid min-h-[520px] gap-0 lg:grid-cols-[340px_1fr]">
      <ul className="max-h-[640px] overflow-y-auto border-b border-border lg:border-b-0 lg:border-r">
        {items.map((v) => (
          <li key={v.version}>
            <button
              type="button"
              onClick={() => setSel(v.version)}
              className={cn('flex w-full flex-col gap-1 border-b border-border-subtle px-3 py-2.5 text-left transition-colors hover:bg-surface-2/60', sel === v.version && 'bg-[var(--accent-subtle)] hover:bg-[var(--accent-subtle)]')}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold text-text-1">v{v.version}</span>
                <SourceBadge source={v.source} />
                {v.version === activeV ? <span className="rounded bg-allow/15 px-1.5 py-px text-[10px] font-medium text-allow">ACTIVE</span> : null}
                <TimeAgo ts={v.applied_at} short className="ml-auto text-2xs text-text-3" />
              </div>
              <div className="line-clamp-2 text-xs text-text-2">{v.summary || '—'}</div>
              <div className="text-2xs text-text-3">
                {v.applied_by ? dir.nameOf(v.applied_by) : 'system'} · {v.changes_count} change{v.changes_count === 1 ? '' : 's'}
                {v.reason ? <span className="italic"> · “{v.reason}”</span> : null}
              </div>
            </button>
          </li>
        ))}
      </ul>
      <div className="flex min-w-0 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
          <History className="size-3.5 text-text-3" />
          <span className="text-xs text-text-2">
            {selInfo ? (
              <>
                <span className="font-mono text-text-1">v{selInfo.version}</span> → active <span className="font-mono text-text-1">v{activeV ?? '?'}</span>
              </>
            ) : (
              'Select a version'
            )}
          </span>
          {loading ? <Loader2 className="size-3.5 animate-spin text-text-3" /> : null}
          <div className="ml-auto flex gap-1.5">
            <Button
              size="sm"
              variant="secondary"
              disabled={!yaml || isActive}
              onClick={() => {
                if (!yaml) return;
                d.replaceDraft(yaml.yaml);
                onLoaded();
              }}
            >
              <FileInput className="size-3.5" /> Load into editor
            </Button>
            <Button size="sm" variant="danger-ghost" disabled={sel === null || isActive} onClick={() => setRb(true)}>
              <Undo2 className="size-3.5" /> Roll back to v{sel ?? '…'}
            </Button>
          </div>
        </div>
        <div className="min-h-[460px] flex-1">
          {yaml && d.active.data ? (
            isActive ? (
              <div className="p-6 text-xs text-text-3">This is the active version.</div>
            ) : (
              <DiffHost original={yaml.yaml} modified={d.active.data.yaml} sideBySide={false} className="h-[520px]" originalLabel={`v${yaml.v}`} modifiedLabel={`v${activeV}`} />
            )
          ) : null}
        </div>
      </div>

      <Dialog open={rb} onOpenChange={(o) => !busy && setRb(o)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Undo2 className="size-4" /> Roll back to v{sel}
            </DialogTitle>
            <DialogDescription className="text-text-2">Re-applies v{sel} as a new version. Governed like any edit: loosening rollbacks need the same approver.</DialogDescription>
          </DialogHeader>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="Reason" autoFocus className="text-sm" />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRb(false)} disabled={busy}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={busy || sel === null}
              onClick={async () => {
                if (sel === null) return;
                setBusy(true);
                await d.rollback(sel, reason.trim());
                setBusy(false);
                setRb(false);
                setReason('');
                res.refresh();
              }}
            >
              {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Undo2 className="size-3.5" />} Roll back
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
