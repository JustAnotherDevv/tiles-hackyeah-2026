// Tiny LCS line diff + unified-line parser (MCP pin diffs). PURE module, node-testable.

export interface DiffLine {
  op: ' ' | '+' | '-';
  text: string;
}

/** Line diff between two texts (O(n·m); tool descriptions are short). */
export function lineDiff(oldText: string, newText: string): DiffLine[] {
  const a = oldText.split('\n');
  const b = newText.split('\n');
  const n = a.length;
  const m = b.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i]![j] = a[i] === b[j] ? lcs[i + 1]![j + 1]! + 1 : Math.max(lcs[i + 1]![j]!, lcs[i]![j + 1]!);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ op: ' ', text: a[i]! });
      i++;
      j++;
    } else if (lcs[i + 1]![j]! >= lcs[i]![j + 1]!) {
      out.push({ op: '-', text: a[i++]! });
    } else {
      out.push({ op: '+', text: b[j++]! });
    }
  }
  while (i < n) out.push({ op: '-', text: a[i++]! });
  while (j < m) out.push({ op: '+', text: b[j++]! });
  return out;
}

/** Parse unified-diff lines (as sent by the server) into DiffLines; hunk headers are dropped. */
export function parseUnified(lines: string[]): DiffLine[] {
  const out: DiffLine[] = [];
  for (const l of lines) {
    if (l.startsWith('@@') || l.startsWith('+++') || l.startsWith('---')) continue;
    if (l.startsWith('+')) out.push({ op: '+', text: l.slice(1) });
    else if (l.startsWith('-')) out.push({ op: '-', text: l.slice(1) });
    else out.push({ op: ' ', text: l.startsWith(' ') ? l.slice(1) : l });
  }
  return out;
}
