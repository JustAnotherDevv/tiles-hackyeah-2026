// Verdict probes panel (UIG-05): the fixed dry-run interactions with their current verdict and the
// deciding control; rows that flipped on the last reload pulse for 3 s and show before → after.
// Owner: B19-dashboard-gov-policy.
import { ArrowRight, FlaskConical, Loader2, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { PROBES } from '@/components/governance/lib/probe-defs';
import { ActionBadge } from '@/components/shell';
import { fmtMs } from '@/lib/format';
import { resolveIcon } from '@/lib/icons';
import { cn } from '@/lib/utils';
import { ensureEditorStyles } from './editor-types';
import { useProbeRunner } from './probe-runner';

export function ProbePanel({ version, isMock }: { version: number | null; isMock: boolean }) {
  const p = useProbeRunner(version, isMock);
  const [pulse, setPulse] = useState(false);
  useEffect(() => ensureEditorStyles(), []);
  useEffect(() => {
    if (!p.flippedAt) return;
    setPulse(true);
    const t = window.setTimeout(() => setPulse(false), 3200);
    return () => window.clearTimeout(t);
  }, [p.flippedAt]);
  const flipped = new Map(p.flips.map((f) => [f.id, f]));

  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-2xs text-text-3">
        <FlaskConical className="size-3" />
        {p.status === 'unavailable' ? (
          <span className="text-redact" title={p.error ?? undefined}>
            /v1/guard unavailable — probes paused
          </span>
        ) : p.status === 'running' ? (
          <span className="inline-flex items-center gap-1">
            <Loader2 className="size-3 animate-spin" /> running dry-run probes…
          </span>
        ) : p.ranAt ? (
          <span>
            dry-run on v{p.version ?? '?'}
            {p.durationMs !== null ? ` · ${fmtMs(p.durationMs)}` : ''} · no audit, no side effects{p.isMock ? ' · mock' : ''}
          </span>
        ) : (
          <span>waiting for baseline…</span>
        )}
        <button type="button" onClick={p.rerun} className="ml-auto rounded p-0.5 hover:bg-surface-3 hover:text-text-1" title="Re-run probes">
          <RefreshCw className="size-3" />
        </button>
      </div>
      <ul className="space-y-1">
        {PROBES.map((def) => {
          const r = p.results?.[def.id];
          const f = flipped.get(def.id);
          const Icon = resolveIcon(def.icon);
          return (
            <li
              key={def.id}
              className={cn(
                'flex items-center gap-2 rounded-md border border-transparent px-2 py-1.5',
                f && 'border-approval/30 bg-approval/[0.05]',
                f && pulse && 'aegis-probe-pulse',
              )}
              title={r?.reason || def.detail}
            >
              <Icon className="size-3.5 shrink-0 text-text-3" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs text-text-1">{def.label}</div>
                <div className="truncate text-2xs text-text-4">{def.detail}</div>
              </div>
              {f ? (
                <span className="inline-flex items-center gap-1">
                  <ActionBadge action={f.before} size="sm" />
                  <ArrowRight className="size-3 text-approval" />
                </span>
              ) : null}
              {r ? <ActionBadge action={r.action} size="sm" monitor={r.monitor} /> : <span className="h-5 w-12 animate-pulse rounded bg-surface-3" />}
              <span className="w-12 shrink-0 text-right font-mono text-2xs text-text-3">{r?.control ?? (r ? '—' : '')}</span>
            </li>
          );
        })}
      </ul>
      {p.flips.length > 0 && p.flipVersion ? (
        <div className="mt-2 text-2xs text-approval">
          {p.flips.length} verdict{p.flips.length > 1 ? 's' : ''} flipped on v{p.flipVersion}
        </div>
      ) : null}
    </div>
  );
}
