// Bundled Monaco for the policy editor (UIG-04). Never loaded from a CDN (CONTRACTS §5.4): the core
// API + editor features + the YAML tokenizer come from the local `monaco-editor` package and the
// editor worker is bundled with Vite's `?worker`. Language services (TS/CSS/JSON/HTML) are NOT
// imported, so their heavy workers never enter the bundle. This module is only reached through the
// React.lazy PolicyEditor / PolicyDiffView chunks, so Monaco never loads on other pages.
// Owner: B19-dashboard-gov-policy.
import * as monaco from 'monaco-editor/editor';
import 'monaco-editor/features/register.all';
import 'monaco-editor/languages/definitions/yaml/register';
import EditorWorker from 'monaco-editor/editor/editor.worker?worker';

declare global {
  interface Window {
    __aegisMonacoReady?: boolean;
  }
}

if (!window.__aegisMonacoReady) {
  window.__aegisMonacoReady = true;
  self.MonacoEnvironment = {
    getWorker: () => new EditorWorker(),
  };
  monaco.editor.defineTheme('aegis-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'type', foreground: '9DB2D6' }, // keys
      { token: 'type.yaml', foreground: '9DB2D6' },
      { token: 'string', foreground: 'A8C79A' },
      { token: 'string.yaml', foreground: 'A8C79A' },
      { token: 'number', foreground: 'D7B377' },
      { token: 'number.yaml', foreground: 'D7B377' },
      { token: 'keyword', foreground: 'C3A6D9' },
      { token: 'keyword.yaml', foreground: 'C3A6D9' },
      { token: 'comment', foreground: '6B7280' },
      { token: 'comment.yaml', foreground: '6B7280' },
      { token: 'operators', foreground: '7A808C' },
      { token: 'delimiter', foreground: '7A808C' },
    ],
    colors: {
      'editor.background': '#0B0D10',
      'editor.foreground': '#ECEEF1',
      'editorLineNumber.foreground': '#3B414C',
      'editorLineNumber.activeForeground': '#A2A8B3',
      'editor.lineHighlightBackground': '#13161A',
      'editor.lineHighlightBorder': '#00000000',
      'editor.selectionBackground': '#6366F140',
      'editor.inactiveSelectionBackground': '#6366F120',
      'editorCursor.foreground': '#A5B4FC',
      'editorIndentGuide.background1': '#1E2228',
      'editorIndentGuide.activeBackground1': '#2A2F37',
      'editorGutter.background': '#0B0D10',
      'editorError.foreground': '#FB7185',
      'editorWarning.foreground': '#FBBF24',
      'editorOverviewRuler.border': '#00000000',
      'scrollbarSlider.background': '#22262C80',
      'scrollbarSlider.hoverBackground': '#2E333BA0',
      'editorWidget.background': '#191C21',
      'editorWidget.border': '#2A2F37',
      'editorHoverWidget.background': '#191C21',
      'editorHoverWidget.border': '#2A2F37',
      'diffEditor.insertedTextBackground': '#10B98126',
      'diffEditor.removedTextBackground': '#F43F5E26',
      'diffEditor.insertedLineBackground': '#10B98114',
      'diffEditor.removedLineBackground': '#F43F5E14',
      'focusBorder': '#6366F180',
    },
  });
}

export const MONACO_OPTIONS: monaco.editor.IStandaloneEditorConstructionOptions = {
  theme: 'aegis-dark',
  language: 'yaml',
  automaticLayout: true,
  fontFamily: '"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
  fontSize: 12.5,
  lineHeight: 20,
  tabSize: 2,
  insertSpaces: true,
  detectIndentation: false,
  renderWhitespace: 'selection',
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  smoothScrolling: false,
  padding: { top: 10, bottom: 10 },
  glyphMargin: true,
  folding: true,
  stickyScroll: { enabled: true },
  fixedOverflowWidgets: true,
  overviewRulerBorder: false,
  renderLineHighlight: 'line',
  guides: { indentation: true },
};

export { monaco };
