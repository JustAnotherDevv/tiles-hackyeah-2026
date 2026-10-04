// Monaco YAML editor (lazy chunk). Uncontrolled model: content changes flow out via onChange; the page
// pushes content in through the handle (pushEditOperations keeps undo). Server validation issues are
// shown as markers at line:col; lines changed vs the active policy get a gutter bar; external reloads
// flash the changed lines for 3 s. Cmd/Ctrl+S = apply. Owner: B19-dashboard-gov-policy.
import { useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';
import { ensureEditorStyles, type PolicyEditorHandle, type PolicyEditorProps } from './editor-types';
import { monaco, MONACO_OPTIONS } from './monaco-setup';

let modelSeq = 0;

export default function PolicyEditor({ initialValue, onChange, markers, changedLines, onSave, onReady, readOnly, className }: PolicyEditorProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const flashIds = useRef<monaco.editor.IEditorDecorationsCollection | null>(null);
  const gutterIds = useRef<monaco.editor.IEditorDecorationsCollection | null>(null);
  const cb = useRef({ onChange, onSave, onReady });
  cb.current = { onChange, onSave, onReady };
  const initial = useRef(initialValue);

  useEffect(() => {
    ensureEditorStyles();
    if (!host.current) return;
    modelSeq += 1;
    const model = monaco.editor.createModel(initial.current, 'yaml', monaco.Uri.parse(`inmemory://aegis/policy-${modelSeq}.yaml`));
    const ed = monaco.editor.create(host.current, { ...MONACO_OPTIONS, model, readOnly: Boolean(readOnly) });
    editorRef.current = ed;
    flashIds.current = ed.createDecorationsCollection();
    gutterIds.current = ed.createDecorationsCollection();
    const sub = model.onDidChangeContent(() => cb.current.onChange(model.getValue()));
    ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => cb.current.onSave?.());

    const flash = (lines: number[]) => {
      const max = model.getLineCount();
      flashIds.current?.set(
        lines
          .filter((l) => l >= 1 && l <= max)
          .slice(0, 200)
          .map((l) => ({ range: new monaco.Range(l, 1, l, 1), options: { isWholeLine: true, className: 'aegis-flash-line' } })),
      );
      window.setTimeout(() => flashIds.current?.clear(), 3200);
    };
    const handle: PolicyEditorHandle = {
      kind: 'monaco',
      getValue: () => model.getValue(),
      focus: () => ed.focus(),
      revealLine: (line, doFlash = true) => {
        const l = Math.min(Math.max(1, line), model.getLineCount());
        ed.revealLineInCenterIfOutsideViewport(l);
        ed.setPosition({ lineNumber: l, column: model.getLineMaxColumn(l) });
        if (doFlash) flash([l]);
      },
      setValue: (text, opts = {}) => {
        if (text !== model.getValue()) {
          const view = ed.saveViewState();
          model.pushEditOperations([], [{ range: model.getFullModelRange(), text }], () => null);
          ed.pushUndoStop();
          if (view && opts.reveal === undefined) ed.restoreViewState(view);
        }
        if (opts.flashLines?.length) flash(opts.flashLines);
        if (opts.reveal !== undefined) handle.revealLine(opts.reveal, !opts.flashLines?.length);
      },
    };
    cb.current.onReady?.(handle);
    return () => {
      sub.dispose();
      ed.dispose();
      model.dispose();
      editorRef.current = null;
    };
    // created once per mount; readOnly is handled below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    editorRef.current?.updateOptions({ readOnly: Boolean(readOnly) });
  }, [readOnly]);

  useEffect(() => {
    const ed = editorRef.current;
    const model = ed?.getModel();
    if (!ed || !model) return;
    const max = model.getLineCount();
    monaco.editor.setModelMarkers(
      model,
      'aegis',
      markers.map((m) => {
        const line = Math.min(Math.max(1, m.line), max);
        const endCol = Math.max(model.getLineMaxColumn(line), m.col + 1);
        return {
          startLineNumber: line,
          startColumn: Math.min(m.col, model.getLineMaxColumn(line)),
          endLineNumber: line,
          endColumn: endCol,
          message: m.message,
          severity: m.severity === 'warning' ? monaco.MarkerSeverity.Warning : monaco.MarkerSeverity.Error,
          source: 'aegis',
        };
      }),
    );
  }, [markers]);

  useEffect(() => {
    const ed = editorRef.current;
    const model = ed?.getModel();
    if (!ed || !model || !gutterIds.current) return;
    const max = model.getLineCount();
    const errLines = new Set(markers.filter((m) => m.severity === 'error').map((m) => m.line));
    gutterIds.current.set([
      ...(changedLines ?? [])
        .filter((l) => l >= 1 && l <= max && !errLines.has(l))
        .slice(0, 400)
        .map((l) => ({ range: new monaco.Range(l, 1, l, 1), options: { isWholeLine: true, linesDecorationsClassName: 'aegis-changed-gutter' } })),
      ...[...errLines].filter((l) => l >= 1 && l <= max).map((l) => ({ range: new monaco.Range(l, 1, l, 1), options: { isWholeLine: true, linesDecorationsClassName: 'aegis-error-gutter' } })),
    ]);
  }, [changedLines, markers]);

  return <div ref={host} className={cn('h-full min-h-[420px] w-full', className)} data-testid="policy-monaco" />;
}
