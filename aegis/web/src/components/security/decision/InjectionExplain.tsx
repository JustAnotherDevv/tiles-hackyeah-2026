// Renders `Decision.meta.inj` (injection-defense explainability, A-45 / plan 05 Appendix B):
// score vs threshold (+ review band), cascade stages (signature → classifier → guard …),
// normalization flags/layers and segment trust. Plain JSON in, nothing raw (excerpts are masked server-side).
import { ScanSearch } from '@/components/icons';
import type { Decision } from '@/api/types';
import { cn } from '@/lib/utils';
import { ControlChip, SectionLabel } from '../common/atoms';

interface InjSignal {
  stage?: string;
  id?: string;
  family?: string;
  weight?: number;
  view?: string | null;
  carrier?: string | null;
  model?: string;
  score?: number;
  threshold?: number;
  band?: string;
  degraded?: boolean;
  skipped?: string;
  fallback?: string;
  label?: string;
  error?: string;
  form?: string;
  ms?: number;
  excerpt?: string;
  segment?: number;
}

export interface InjMeta {
  v?: number;
  trust?: string;
  outcome?: string;
  score?: number;
  threshold?: number | null;
  review_threshold?: number | null;
  segments?: { index: number; role: string; trusted: boolean; chars: number; latest_turn?: boolean }[];
  normalization?: { flags?: string[]; layers?: { kind: string; depth: number; len: number }[]; hidden?: { kind: string; len: number }[] };
  signals?: InjSignal[];
  quarantined_spans?: number;
  mention_discount?: boolean;
  model?: string;
  degraded?: boolean;
}

export function injEntries(decisions: Decision[] | undefined): { controlId: string; action: string; inj: InjMeta }[] {
  return (decisions ?? [])
    .map((d) => ({ controlId: d.control_id, action: d.action as string, inj: d.meta?.inj as InjMeta | undefined }))
    .filter((e): e is { controlId: string; action: string; inj: InjMeta } => !!e.inj && typeof e.inj === 'object');
}

const n2 = (x: number | null | undefined) => (typeof x === 'number' ? x.toFixed(2) : '—');

function ScoreBar({ score, threshold, review }: { score: number; threshold: number | null | undefined; review: number | null | undefined }) {
  const pct = (x: number) => `${Math.max(0, Math.min(1, x)) * 100}%`;
  const over = typeof threshold === 'number' && score >= threshold;
  const inReview = !over && typeof review === 'number' && score >= review;
  return (
    <div className="relative h-2 w-full rounded-full bg-surface-3">
      {typeof review === 'number' && typeof threshold === 'number' && threshold > review ? (
        <div className="absolute inset-y-0 rounded-full bg-amber-500/20" style={{ left: pct(review), width: `${(threshold - review) * 100}%` }} title="review band" />
      ) : null}
      <div className={cn('absolute inset-y-0 left-0 rounded-full', over ? 'bg-rose-500/80' : inReview ? 'bg-amber-400/80' : 'bg-emerald-500/70')} style={{ width: pct(score) }} />
      {typeof threshold === 'number' ? <div className="absolute -inset-y-1 w-0.5 rounded bg-text-1" style={{ left: pct(threshold) }} title={`threshold ${threshold}`} /> : null}
    </div>
  );
}

function stageText(s: InjSignal): string {
  switch (s.stage) {
    case 'signature':
      return [s.id, s.family, s.weight !== undefined ? `w ${n2(s.weight)}` : null, s.view && s.view !== 'raw' ? `view ${s.view}` : null, s.carrier ? `carrier ${s.carrier}` : null].filter(Boolean).join(' · ');
    case 'classifier':
      return [s.model, s.score !== undefined ? `score ${n2(s.score)}` : null, s.band ? `band ${s.band}` : null, s.error ? `error ${s.error}` : null].filter(Boolean).join(' · ');
    case 'guard':
      return s.skipped ? `skipped (${s.skipped}) → fallback ${s.fallback ?? '—'}` : [s.model, s.label, s.score !== undefined ? `score ${n2(s.score)}` : null, s.fallback ? `fallback ${s.fallback}` : null].filter(Boolean).join(' · ');
    default:
      return [s.id, s.family, s.form, s.model, s.score !== undefined ? `score ${n2(s.score)}` : null].filter(Boolean).join(' · ');
  }
}

export function InjectionExplain({ decisions }: { decisions: Decision[] | undefined }) {
  const entries = injEntries(decisions);
  if (!entries.length) return null;
  return (
    <div>
      <SectionLabel right="decision.meta.inj">Injection analysis</SectionLabel>
      <div className="space-y-2">
        {entries.map(({ controlId, action, inj }, i) => {
          const flags = inj.normalization?.flags ?? [];
          const layers = inj.normalization?.layers ?? [];
          const hidden = inj.normalization?.hidden ?? [];
          const signals = (inj.signals ?? []).slice(0, 12);
          return (
            <div key={`${controlId}-${i}`} className="rounded-md border border-border bg-surface-1 px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <ScanSearch className="size-3.5 text-text-3" />
                <ControlChip id={controlId} />
                <span className="font-mono text-text-2">
                  score <span className="text-text-1">{n2(inj.score)}</span> vs threshold <span className="text-text-1">{n2(inj.threshold)}</span>
                  {typeof inj.review_threshold === 'number' ? <span className="text-text-3"> · review ≥ {n2(inj.review_threshold)}</span> : null}
                </span>
                <span className="rounded-xs border border-border bg-surface-2 px-1.5 font-mono text-2xs text-text-2">{inj.outcome ?? action}</span>
                {inj.trust ? <span className="rounded-xs border border-border bg-surface-2 px-1.5 font-mono text-2xs text-text-3">{inj.trust}</span> : null}
                {inj.degraded ? (
                  <span className="rounded-xs border border-amber-500/40 bg-amber-500/10 px-1.5 font-mono text-2xs text-amber-300" title="semantic models off / unavailable — deterministic heuristic score">
                    heuristic (degraded)
                  </span>
                ) : null}
                {inj.quarantined_spans ? <span className="font-mono text-2xs text-text-3">{inj.quarantined_spans} span(s) quarantined</span> : null}
              </div>
              {typeof inj.score === 'number' ? (
                <div className="mt-2">
                  <ScoreBar score={inj.score} threshold={inj.threshold} review={inj.review_threshold} />
                </div>
              ) : null}
              {signals.length ? (
                <div className="mt-2 space-y-1">
                  {signals.map((s, j) => (
                    <div key={j} className="grid grid-cols-[84px_1fr] gap-2 text-2xs">
                      <span className="font-mono uppercase tracking-wide text-text-3">{s.stage ?? 'signal'}</span>
                      <span className="min-w-0 truncate font-mono text-text-2" title={s.excerpt ?? stageText(s)}>
                        {stageText(s) || '—'}
                        {s.excerpt ? <span className="text-text-4"> · “{s.excerpt}”</span> : null}
                      </span>
                    </div>
                  ))}
                </div>
              ) : null}
              {flags.length || layers.length || hidden.length ? (
                <div className="mt-2 flex flex-wrap items-center gap-1 text-2xs">
                  <span className="mr-1 text-text-3">Normalization</span>
                  {flags.map((f) => (
                    <span key={f} className="rounded-xs border border-border bg-surface-2 px-1.5 font-mono text-text-2">
                      {f}
                    </span>
                  ))}
                  {layers.map((l, k) => (
                    <span key={`l${k}`} className="rounded-xs border border-sky-500/30 bg-sky-500/10 px-1.5 font-mono text-sky-300">
                      {l.kind}@{l.depth}
                    </span>
                  ))}
                  {hidden.map((h, k) => (
                    <span key={`h${k}`} className="rounded-xs border border-rose-500/30 bg-rose-500/10 px-1.5 font-mono text-rose-300">
                      hidden {h.kind} ({h.len})
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
