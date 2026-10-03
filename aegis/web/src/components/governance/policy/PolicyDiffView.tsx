// Monaco side-by-side / inline diff (lazy chunk). Original is read-only. Mounted only while its tab is
// visible and disposed on unmount (memory on the 8 GB demo laptop). Owner: B19-dashboard-gov-policy.
import { useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';
import { ensureEditorStyles, type PolicyDiffProps } from './editor-types';
import { monaco, MONACO_OPTIONS } from './monaco-setup';

let seq = 0;

export default function PolicyDiffView({ original, modified, sideBySide = true, className }: PolicyDiffProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const diffRef = useRef<monaco.editor.IStandaloneDiffEditor | null>(null);
  const models = useRef<{ a: monaco.editor.ITextModel; b: monaco.editor.ITextModel } | null>(null);
  const init = useRef({ original, modified });

  useEffect(() => {
    ensureEditorStyles();
    if (!host.current) return;
    seq += 1;
    const a = monaco.editor.createModel(init.current.original, 'yaml', monaco.Uri.parse(`inmemory://aegis/diff-a-${seq}.yaml`));
    const b = monaco.editor.createModel(init.current.modified, 'yaml', monaco.Uri.parse(`inmemory://aegis/diff-b-${seq}.yaml`));
    const d = monaco.editor.createDiffEditor(host.current, {
      theme: MONACO_OPTIONS.theme,
      automaticLayout: true,
      fontFamily: MONACO_OPTIONS.fontFamily,
      fontSize: MONACO_OPTIONS.fontSize,
      lineHeight: MONACO_OPTIONS.lineHeight,
      readOnly: true,
      originalEditable: false,
      renderSideBySide: sideBySide,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      hideUnchangedRegions: { enabled: true, contextLineCount: 3, minimumLineCount: 4, revealLineCount: 10 },
      renderOverviewRuler: false,
      ignoreTrimWhitespace: false,
      padding: { top: 8, bottom: 8 },
    });
    d.setModel({ original: a, modified: b });
    diffRef.current = d;
    models.current = { a, b };
    return () => {
      d.dispose();
      a.dispose();
      b.dispose();
      diffRef.current = null;
      models.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const m = models.current;
    if (!m) return;
    if (m.a.getValue() !== original) m.a.setValue(original);
    if (m.b.getValue() !== modified) m.b.setValue(modified);
  }, [original, modified]);

  useEffect(() => {
    diffRef.current?.updateOptions({ renderSideBySide: sideBySide });
  }, [sideBySide]);

  return <div ref={host} className={cn('h-full min-h-[420px] w-full', className)} data-testid="policy-monaco-diff" />;
}
