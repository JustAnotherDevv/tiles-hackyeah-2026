// Shared props/handle for the Monaco editor and its textarea fallback. Owner: B19-dashboard-gov-policy.
import type { ValidationIssue } from '@/api/types';

export interface EditorMarker {
  line: number;
  col: number;
  message: string;
  severity: 'error' | 'warning';
}

export interface PolicyEditorHandle {
  /** Replace the content (keeps undo history), optionally flash lines (1-based) and reveal one. */
  setValue(text: string, opts?: { flashLines?: number[]; reveal?: number }): void;
  revealLine(line: number, flash?: boolean): void;
  getValue(): string;
  focus(): void;
  kind: 'monaco' | 'plain';
}

export interface PolicyEditorProps {
  initialValue: string;
  onChange: (text: string) => void;
  markers: EditorMarker[];
  /** Lines (1-based, in the current text) that differ from the active policy — gutter bars. */
  changedLines?: number[];
  onSave?: () => void;
  onReady?: (handle: PolicyEditorHandle) => void;
  readOnly?: boolean;
  className?: string;
}

export interface PolicyDiffProps {
  original: string;
  modified: string;
  sideBySide?: boolean;
  className?: string;
  originalLabel?: string;
  modifiedLabel?: string;
}

/** ValidationIssue[] → editor markers (path-only issues go to line 1). */
export function toMarkers(issues: ValidationIssue[] | null | undefined): EditorMarker[] {
  return (issues ?? []).map((i) => ({
    line: Math.max(1, i.line ?? 1),
    col: Math.max(1, i.col ?? 1),
    message: i.line ? i.message : `${i.path ? `${i.path}: ` : ''}${i.message}`,
    severity: i.severity === 'warning' ? 'warning' : 'error',
  }));
}

const STYLE_ID = 'aegis-policy-editor-styles';

/** Decoration classes used by both editors (injected once; owned here, not in global CSS). */
export function ensureEditorStyles(): void {
  if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
  const s = document.createElement('style');
  s.id = STYLE_ID;
  s.textContent = `
.aegis-flash-line { background: rgba(99, 102, 241, 0.22); animation: aegis-flash 3s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
@keyframes aegis-flash { 0% { background: rgba(99, 102, 241, 0.34); } 100% { background: rgba(99, 102, 241, 0); } }
.aegis-changed-gutter { background: #6366f1; width: 3px !important; margin-left: 3px; border-radius: 1px; }
.aegis-error-gutter { background: #fb7185; width: 3px !important; margin-left: 3px; border-radius: 1px; }
.aegis-probe-pulse { animation: aegis-probe-pulse 1s ease-in-out 3; }
@keyframes aegis-probe-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(167, 139, 250, 0); } 50% { box-shadow: 0 0 0 3px rgba(167, 139, 250, 0.35); background: rgba(167, 139, 250, 0.08); } }
@media (prefers-reduced-motion: reduce) { .aegis-flash-line, .aegis-probe-pulse { animation: none; } }
`;
  document.head.appendChild(s);
}
