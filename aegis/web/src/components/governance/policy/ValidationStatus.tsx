// Editor status bar: ✓ valid / ✕ N errors (first line:col — message), self-test n/m when known,
// draft vs base version, line count, editor engine. Owner: B19-dashboard-gov-policy.
import { AlertTriangle, CheckCircle2, CircleDashed, Loader2, XCircle } from 'lucide-react';
import type { ValidationIssue, ValidationReport } from '@/api/types';
import { cn } from '@/lib/utils';

export function ValidationStatus({
  checking,
  dirty,
  issues,
  report,
  baseVersion,
  lines,
  engine,
  isMock,
  onJump,
}: {
  checking: boolean;
  dirty: boolean;
  issues: ValidationIssue[];
  report: ValidationReport | null;
  baseVersion: number | null;
  lines: number;
  engine: 'monaco' | 'plain' | null;
  isMock: boolean;
  onJump: (line: number) => void;
}) {
  const errors = issues.filter((i) => i.severity === 'error');
  const warnings = issues.filter((i) => i.severity === 'warning');
  const first = errors[0] ?? warnings[0];
  const st = report?.selftest ?? [];
  return (
    <div className="flex min-h-8 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border bg-surface-1 px-3 py-1.5 text-xs">
      {!dirty ? (
        <span className="inline-flex items-center gap-1.5 text-text-3">
          <CircleDashed className="size-3.5" /> in sync with active v{baseVersion ?? '…'}
        </span>
      ) : checking ? (
        <span className="inline-flex items-center gap-1.5 text-text-2">
          <Loader2 className="size-3.5 animate-spin" /> validating on the server…
        </span>
      ) : errors.length ? (
        <button
          type="button"
          onClick={() => first?.line && onJump(first.line)}
          className="inline-flex min-w-0 items-center gap-1.5 text-block hover:underline"
          title="Jump to the first error"
        >
          <XCircle className="size-3.5 shrink-0" />
          <span className="font-medium">{errors.length === 1 ? '1 error' : `${errors.length} errors`}</span>
          {first ? (
            <span className="truncate font-mono text-2xs text-block/90">
              {first.line ? `line ${first.line}${first.col ? `:${first.col}` : ''} — ` : ''}
              {first.message}
            </span>
          ) : null}
        </button>
      ) : (
        <span className="inline-flex items-center gap-1.5 text-allow">
          <CheckCircle2 className="size-3.5" /> valid{warnings.length ? '' : ' · schema + semantic checks passed'}
        </span>
      )}
      {dirty && !checking && warnings.length > 0 ? (
        <span className="inline-flex items-center gap-1 text-redact">
          <AlertTriangle className="size-3.5" /> {warnings.length} warning{warnings.length > 1 ? 's' : ''}
        </span>
      ) : null}
      {st.length > 0 ? (
        <span className={cn('tabular', st.every((t) => t.passed) ? 'text-allow' : 'text-block')}>
          self-test {st.filter((t) => t.passed).length}/{st.length}
        </span>
      ) : null}
      <span className="ml-auto flex items-center gap-3 text-text-3">
        {isMock ? <span className="text-2xs uppercase tracking-wider">mock validator</span> : null}
        <span>YAML · {lines} lines</span>
        <span>{dirty ? <span className="text-accent-fg">draft · base v{baseVersion}</span> : `v${baseVersion ?? '…'}`}</span>
        {engine ? <span className="text-2xs">{engine === 'monaco' ? 'Monaco · bundled' : 'plain editor (fallback)'}</span> : null}
        <span className="hidden text-2xs lg:inline">
          <kbd className="rounded border border-border-strong px-1 font-mono">⌘S</kbd> apply
        </span>
      </span>
    </div>
  );
}
