// Fallback editor (Monaco failed or took > 6 s): mono textarea with a line-number gutter that marks
// changed lines (indigo) and error lines (rose), plus the marker list. Same handle API as Monaco so
// the page doesn't care which one is mounted. Ported from the prototype's view-policy.js textarea.
// Owner: B19-dashboard-gov-policy.
import { useEffect, useMemo, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import type { PolicyEditorHandle, PolicyEditorProps } from './editor-types';

const LINE_H = 20;

export function PlainYamlEditor({ initialValue, onChange, markers, changedLines, onSave, onReady, readOnly, className }: PolicyEditorProps) {
  const [text, setText] = useState(initialValue);
  const [flash, setFlash] = useState<Set<number>>(new Set());
  const ta = useRef<HTMLTextAreaElement | null>(null);
  const gutter = useRef<HTMLDivElement | null>(null);
  const cb = useRef({ onChange, onSave, onReady });
  cb.current = { onChange, onSave, onReady };
  const textRef = useRef(text);
  textRef.current = text;

  useEffect(() => {
    const doFlash = (lines: number[]) => {
      setFlash(new Set(lines));
      window.setTimeout(() => setFlash(new Set()), 3000);
    };
    const reveal = (line: number) => {
      const el = ta.current;
      if (!el) return;
      el.scrollTop = Math.max(0, (line - 6) * LINE_H);
      const ls = el.value.split('\n');
      const pos = ls.slice(0, line).join('\n').length;
      el.setSelectionRange(pos, pos);
    };
    const handle: PolicyEditorHandle = {
      kind: 'plain',
      getValue: () => textRef.current,
      focus: () => ta.current?.focus(),
      revealLine: (line, f = true) => {
        reveal(line);
        if (f) doFlash([line]);
      },
      setValue: (v, opts = {}) => {
        setText(v);
        cb.current.onChange(v);
        if (opts.flashLines?.length) doFlash(opts.flashLines);
        if (opts.reveal !== undefined) window.setTimeout(() => reveal(opts.reveal as number), 0);
      },
    };
    cb.current.onReady?.(handle);
  }, []);

  const lines = useMemo(() => text.split('\n'), [text]);
  const errs = useMemo(() => new Map(markers.map((m) => [m.line, m])), [markers]);
  const changed = useMemo(() => new Set(changedLines ?? []), [changedLines]);

  return (
    <div className={cn('flex h-full min-h-[420px] flex-col', className)}>
      <div className="relative flex min-h-0 flex-1 overflow-hidden bg-[#0B0D10] font-mono text-[12.5px]">
        <div ref={gutter} className="w-12 shrink-0 select-none overflow-hidden border-r border-border-subtle py-2.5 text-right text-text-4" aria-hidden>
          {lines.map((_, i) => {
            const n = i + 1;
            const e = errs.get(n);
            return (
              <div
                key={n}
                style={{ height: LINE_H, lineHeight: `${LINE_H}px` }}
                className={cn(
                  'pr-2',
                  e ? (e.severity === 'error' ? 'bg-block/15 text-block' : 'bg-redact/10 text-redact') : changed.has(n) ? 'border-l-2 border-brand text-accent-fg' : '',
                  flash.has(n) && 'bg-brand/25',
                )}
                title={e?.message}
              >
                {n}
              </div>
            );
          })}
        </div>
        <textarea
          ref={ta}
          value={text}
          readOnly={readOnly}
          spellCheck={false}
          wrap="off"
          autoCapitalize="off"
          autoComplete="off"
          aria-label="Policy YAML"
          onScroll={(e) => {
            if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop;
          }}
          onChange={(e) => {
            setText(e.target.value);
            cb.current.onChange(e.target.value);
          }}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
              e.preventDefault();
              cb.current.onSave?.();
            }
          }}
          style={{ lineHeight: `${LINE_H}px`, tabSize: 2 }}
          className="min-h-0 min-w-0 flex-1 resize-none overflow-auto whitespace-pre bg-transparent px-3 py-2.5 text-text-1 caret-accent-fg outline-none"
        />
      </div>
    </div>
  );
}
