// Lazy Monaco hosts with a guaranteed fallback: React.lazy chunk + ErrorBoundary + 6 s load timeout →
// PlainYamlEditor / a unified-diff view, so the editor is never blank (venue Wi-Fi, worker hiccups).
// Owner: B19-dashboard-gov-policy.
import { Component, lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Loader2 } from '@/components/icons';
import { cn } from '@/lib/utils';
import type { PolicyDiffProps, PolicyEditorHandle, PolicyEditorProps } from './editor-types';
import { diffLines } from './line-ops';
import { PlainYamlEditor } from './PlainYamlEditor';

const LazyPolicyEditor = lazy(() => import('./PolicyEditor'));
const LazyPolicyDiffView = lazy(() => import('./PolicyDiffView'));

class Boundary extends Component<{ fallback: ReactNode; onError?: (e: Error) => void; children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error) {
    console.warn('[aegis] Monaco failed, using the plain editor', error);
    this.props.onError?.(error);
  }
  render() {
    return this.state.error ? this.props.fallback : this.props.children;
  }
}

function Loading({ label }: { label: string }) {
  return (
    <div className="grid h-full min-h-[420px] place-items-center bg-[#0B0D10] text-xs text-text-3">
      <span className="inline-flex items-center gap-2">
        <Loader2 className="size-3.5 animate-spin" /> {label}
      </span>
    </div>
  );
}

const LOAD_TIMEOUT_MS = 10000; // cold dev-server loads of Monaco can take > 6 s

export function EditorHost(props: PolicyEditorProps & { onEngine?: (kind: 'monaco' | 'plain') => void; forcePlain?: boolean }) {
  const { onReady, onEngine, forcePlain, ...rest } = props;
  const [failed, setPlain] = useState(false);
  const plain = failed || Boolean(forcePlain);
  const ready = useRef(false);
  const engineRef = useRef(onEngine);
  engineRef.current = onEngine;

  useEffect(() => {
    const t = window.setTimeout(() => {
      if (!ready.current) setPlain(true);
    }, LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    if (plain) engineRef.current?.('plain');
  }, [plain]);

  const handleReady = (h: PolicyEditorHandle) => {
    ready.current = true;
    if (h.kind === 'monaco') engineRef.current?.('monaco');
    onReady?.(h);
  };

  const fallback = <PlainYamlEditor {...rest} onReady={handleReady} />;
  if (plain) return fallback;
  return (
    <Boundary fallback={fallback} onError={() => setPlain(true)}>
      <Suspense fallback={<Loading label="Loading editor…" />}>
        <LazyPolicyEditor {...rest} onReady={handleReady} />
      </Suspense>
    </Boundary>
  );
}

/** Unified diff fallback (also used for small inline diffs). */
export function PlainDiff({ original, modified, className }: Pick<PolicyDiffProps, 'original' | 'modified' | 'className'>) {
  const rows = useMemo(() => {
    const ops = diffLines(original, modified);
    const show = new Set<number>();
    ops.forEach((o, i) => {
      if (o.t !== 'ctx') for (let k = i - 3; k <= i + 3; k++) show.add(k);
    });
    const out: { key: string; kind: 'hunk' | 'ctx' | 'add' | 'del'; n: number | null; text: string }[] = [];
    let prev = -2;
    ops.forEach((o, i) => {
      if (!show.has(i)) return;
      if (i !== prev + 1) out.push({ key: `h${i}`, kind: 'hunk', n: null, text: `@@ line ${(o.bi ?? o.ai ?? 0) + 1} @@` });
      prev = i;
      out.push({ key: `l${i}`, kind: o.t, n: (o.t === 'del' ? o.ai : o.bi) ?? null, text: o.s });
    });
    return out;
  }, [original, modified]);
  if (rows.length === 0) return <div className={cn('p-4 text-xs text-text-3', className)}>No differences.</div>;
  return (
    <div className={cn('overflow-auto bg-[#0B0D10] py-1 font-mono text-[12px] leading-5', className)}>
      {rows.map((r) => (
        <div
          key={r.key}
          className={cn(
            'flex whitespace-pre px-2',
            r.kind === 'add' && 'bg-allow/10 text-allow',
            r.kind === 'del' && 'bg-block/10 text-block',
            r.kind === 'hunk' && 'text-accent-fg/80',
            r.kind === 'ctx' && 'text-text-3',
          )}
        >
          <span className="w-10 shrink-0 select-none pr-2 text-right text-text-4">{r.n !== null ? r.n + 1 : ''}</span>
          <span className="w-4 shrink-0 select-none">{r.kind === 'add' ? '+' : r.kind === 'del' ? '−' : ''}</span>
          <span>{r.text}</span>
        </div>
      ))}
    </div>
  );
}

export function DiffHost(props: PolicyDiffProps & { forcePlain?: boolean }) {
  const [failed, setPlain] = useState(false);
  const plain = failed || Boolean(props.forcePlain);
  const fallback = <PlainDiff original={props.original} modified={props.modified} className={cn('h-full min-h-[420px]', props.className)} />;
  if (plain) return fallback;
  return (
    <Boundary fallback={fallback} onError={() => setPlain(true)}>
      <Suspense fallback={<Loading label="Loading diff editor…" />}>
        <LazyPolicyDiffView original={props.original} modified={props.modified} sideBySide={props.sideBySide} className={props.className} originalLabel={props.originalLabel} modifiedLabel={props.modifiedLabel} />
      </Suspense>
    </Boundary>
  );
}
