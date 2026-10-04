// Quick edits = judge levers (UIG-09). They ONLY modify the draft (never auto-apply) and jump the
// cursor to the edited line: profile switch, per-control enable / monitor toggles, INJ-02 threshold
// slider, "add a CUS-01 keyword", break YAML (to demo rejection) and revert.
// Text-level edits via lib/yaml-text (comment-preserving; flow-style items → "edit manually").
// Owner: B19-dashboard-gov-policy.
import { AlertTriangle, Eye, Plus, RotateCcw } from '@/components/icons';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { addCustomKeyword, breakYaml, getControlField, getTopLevelScalar, parseControls, setControlField, setTopLevelScalar, type TextEdit } from '@/components/governance/lib/yaml-text';
import { Segmented } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import type { PolicyDraft } from './use-policy-draft';

const PROFILES = ['permissive', 'balanced', 'strict', 'paranoid'] as const;
type Profile = (typeof PROFILES)[number];
const FEATURED = ['DLP-01', 'DLP-02', 'INJ-01', 'INJ-02', 'EXE-01', 'ACT-01', 'ACT-02', 'BUD-01', 'EXE-04', 'CUS-01'];

export function QuickEdits({ d }: { d: PolicyDraft }) {
  const text = d.draft ?? '';
  const controls = useMemo(() => {
    const all = parseControls(text);
    const featured = FEATURED.map((id) => all.find((c) => c.id === id)).filter((c): c is NonNullable<typeof c> => Boolean(c));
    return featured.length ? featured : all.slice(0, 10);
  }, [text]);
  const profile = (getTopLevelScalar(text, 'profile') ?? 'balanced').replace(/['"]/g, '') as Profile;
  const thrRaw = getControlField(text, 'INJ-02', 'threshold');
  const thr = thrRaw !== null && Number.isFinite(Number(thrRaw)) ? Number(thrRaw) : null;
  const [thrLocal, setThrLocal] = useState<number | null>(thr);
  useEffect(() => setThrLocal(thr), [thr]);
  const [kw, setKw] = useState('Goldman');

  const apply = (e: TextEdit | null, what: string) => {
    if (!e) {
      toast.warning(`Can't edit ${what} automatically`, { description: 'This entry uses flow style; edit it manually in the editor.' });
      return;
    }
    if (e.yaml === text) return;
    d.replaceDraft(e.yaml, { reveal: e.line, flash: true });
  };

  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1.5 text-xs font-medium text-text-2">Profile</div>
        <Segmented<Profile>
          value={PROFILES.includes(profile) ? profile : 'balanced'}
          options={PROFILES.map((p) => ({ value: p, label: p }))}
          onChange={(v) => apply(setTopLevelScalar(text, 'profile', v), 'profile')}
          ariaLabel="Profile"
        />
      </div>

      {thr !== null ? (
        <div>
          <div className="mb-1.5 flex items-center justify-between text-xs font-medium text-text-2">
            <span>INJ-02 injection threshold</span>
            <span className={cn('font-mono text-xs tabular', thrLocal !== thr ? 'text-accent-fg' : 'text-text-1')}>{(thrLocal ?? thr).toFixed(2)}</span>
          </div>
          <Slider
            min={0.3}
            max={0.98}
            step={0.01}
            value={[thrLocal ?? thr]}
            onValueChange={(v) => setThrLocal(v[0])}
            onValueCommit={(v) => apply(setControlField(text, 'INJ-02', 'threshold', Math.round(v[0] * 100) / 100), 'INJ-02 threshold')}
          />
          <div className="mt-1 flex justify-between text-2xs text-text-4">
            <span>stricter (more blocks)</span>
            <span>looser</span>
          </div>
        </div>
      ) : null}

      <div>
        <div className="mb-1.5 flex items-center justify-between text-xs font-medium text-text-2">
          <span>Controls</span>
          <span className="font-normal text-text-3">monitor · enabled</span>
        </div>
        <ul className="divide-y divide-border-subtle rounded-sm border border-border">
          {controls.map((c) => {
            const monitor = (c.mode ?? '').replace(/['"]/g, '') === 'monitor';
            return (
              <li key={c.id} className="flex items-center gap-2 px-2.5 py-1.5">
                <button type="button" onClick={() => d.handle.current?.revealLine(c.line)} className="min-h-9 min-w-0 flex-1 text-left md:min-h-0" title="Jump to this control">
                  <div className={cn('font-mono text-xs', c.enabled ? 'text-text-1' : 'text-text-3 line-through')}>{c.id}</div>
                  <div className="truncate text-2xs text-text-3">{c.name ?? ''}</div>
                </button>
                <button
                  type="button"
                  disabled={c.flow}
                  onClick={() => apply(setControlField(text, c.id, 'mode', monitor ? 'enforce' : 'monitor'), `${c.id} mode`)}
                  className={cn('grid size-8 place-items-center rounded-sm md:size-6', monitor ? 'bg-redact/15 text-redact' : 'text-text-4 hover:bg-surface-3 hover:text-text-2')}
                  title={monitor ? 'Monitor mode (logs, never blocks) — click to enforce' : 'Switch to monitor mode'}
                >
                  <Eye className="size-3.5" />
                </button>
                <label className="grid h-8 w-10 shrink-0 cursor-pointer place-items-center md:h-6 md:w-8">
                  <Switch
                    size="sm"
                    checked={c.enabled}
                    disabled={c.flow}
                    onCheckedChange={(on) => apply(setControlField(text, c.id, 'enabled', on), `${c.id} enabled`)}
                    aria-label={`${c.id} enabled`}
                  />
                </label>
              </li>
            );
          })}
        </ul>
      </div>

      <div>
        <div className="mb-1.5 text-xs font-medium text-text-2">Custom rule (CUS-01)</div>
        <div className="flex gap-1.5">
          <Input value={kw} onChange={(e) => setKw(e.target.value)} className="h-9 min-w-0 text-xs md:h-8" placeholder="keyword" aria-label="Keyword to block" />
          <Button size="sm" variant="secondary" className="max-md:h-9" disabled={!kw.trim()} onClick={() => apply(addCustomKeyword(text, kw.trim()), 'CUS-01')}>
            <Plus className="size-3.5" /> Block keyword
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" variant="danger-ghost" className="max-md:h-9" onClick={() => apply(breakYaml(text), 'YAML')} title="Insert a tab indent; the server rejects it with line:col">
          <AlertTriangle className="size-3.5" /> Insert YAML error
        </Button>
        <Button size="sm" variant="ghost" className="max-md:h-9" disabled={!d.dirty} onClick={d.discard}>
          <RotateCcw className="size-3.5" /> Revert draft
        </Button>
      </div>
      <div className="text-2xs text-text-3">Quick edits change the draft only. Review the diff, then apply.</div>
    </div>
  );
}
