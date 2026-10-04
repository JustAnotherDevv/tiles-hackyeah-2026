// LCS line diff (ported from staging/design/prototype/assets/view-policy.js, + prefix/suffix trimming).
// Pure, erasable TS: no imports at all. Used by the policy editor (B19), mock diff/validate and the
// approvals PayloadView (rendering `unified` blocks). Owner: B18-dashboard-gov-approvals.

export type DiffOpType = 'ctx' | 'del' | 'add';

export interface DiffOp {
  t: DiffOpType;
  /** line text */
  s: string;
  /** 0-based index in `a` (ctx/del) */
  ai?: number;
  /** 0-based index in `b` (ctx/add) */
  bi?: number;
}

export interface DiffHunk {
  /** 1-based start line in a / b and line counts (unified-diff style). */
  aStart: number;
  aLen: number;
  bStart: number;
  bLen: number;
  ops: DiffOp[];
}

export interface LineChange {
  t: 'chg' | 'add' | 'del';
  path: string;
  from?: string;
  to?: string;
}

const MAX_CELLS = 4_000_000; // guard the O(n·m) table (2k × 2k lines)

/** Line diff a → b. Common prefix/suffix are trimmed before the LCS so big files with small edits are cheap. */
export function lineDiff(a: string[], b: string[]): DiffOp[] {
  let pre = 0;
  while (pre < a.length && pre < b.length && a[pre] === b[pre]) pre++;
  let suf = 0;
  while (suf < a.length - pre && suf < b.length - pre && a[a.length - 1 - suf] === b[b.length - 1 - suf]) suf++;

  const ops: DiffOp[] = [];
  for (let i = 0; i < pre; i++) ops.push({ t: 'ctx', s: a[i], ai: i, bi: i });

  const a2 = a.slice(pre, a.length - suf);
  const b2 = b.slice(pre, b.length - suf);
  const n = a2.length;
  const m = b2.length;

  if (n * m > MAX_CELLS) {
    // Too big for LCS: emit a block replace (still correct, just less minimal).
    for (let i = 0; i < n; i++) ops.push({ t: 'del', s: a2[i], ai: pre + i });
    for (let j = 0; j < m; j++) ops.push({ t: 'add', s: b2[j], bi: pre + j });
  } else {
    const dp: Uint32Array[] = [];
    for (let i = 0; i <= n; i++) dp.push(new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        dp[i][j] = a2[i] === b2[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (a2[i] === b2[j]) {
        ops.push({ t: 'ctx', s: a2[i], ai: pre + i, bi: pre + j });
        i++;
        j++;
      } else if (dp[i + 1][j] >= dp[i][j + 1]) {
        ops.push({ t: 'del', s: a2[i], ai: pre + i });
        i++;
      } else {
        ops.push({ t: 'add', s: b2[j], bi: pre + j });
        j++;
      }
    }
    while (i < n) {
      ops.push({ t: 'del', s: a2[i], ai: pre + i });
      i++;
    }
    while (j < m) {
      ops.push({ t: 'add', s: b2[j], bi: pre + j });
      j++;
    }
  }

  const offA = a.length - suf;
  const offB = b.length - suf;
  for (let k = 0; k < suf; k++) ops.push({ t: 'ctx', s: a[offA + k], ai: offA + k, bi: offB + k });
  return ops;
}

export function diffText(a: string, b: string): DiffOp[] {
  return lineDiff(splitLines(a), splitLines(b));
}

export function splitLines(text: string): string[] {
  return text.replace(/\r\n?/g, '\n').split('\n');
}

/** True when the diff contains any add/del op. */
export function hasChanges(ops: DiffOp[]): boolean {
  return ops.some((o) => o.t !== 'ctx');
}

/** 0-based indices of lines in `b` that were added or changed (for editor decorations / flashes). */
export function changedLinesB(ops: DiffOp[]): number[] {
  return ops.filter((o) => o.t === 'add' && o.bi !== undefined).map((o) => o.bi as number);
}

/** Group ops into hunks with `context` lines around changes. */
export function hunks(ops: DiffOp[], context = 3): DiffHunk[] {
  const idx: number[] = [];
  ops.forEach((o, k) => {
    if (o.t !== 'ctx') idx.push(k);
  });
  if (idx.length === 0) return [];
  const ranges: [number, number][] = [];
  for (const k of idx) {
    const lo = Math.max(0, k - context);
    const hi = Math.min(ops.length - 1, k + context);
    const last = ranges[ranges.length - 1];
    if (last && lo <= last[1] + 1) last[1] = Math.max(last[1], hi);
    else ranges.push([lo, hi]);
  }
  return ranges.map(([lo, hi]) => {
    const slice = ops.slice(lo, hi + 1);
    const firstA = slice.find((o) => o.ai !== undefined)?.ai ?? 0;
    const firstB = slice.find((o) => o.bi !== undefined)?.bi ?? 0;
    return {
      aStart: firstA + 1,
      aLen: slice.filter((o) => o.t !== 'add').length,
      bStart: firstB + 1,
      bLen: slice.filter((o) => o.t !== 'del').length,
      ops: slice,
    };
  });
}

/** Render a unified diff string (for mocks and copy/paste). */
export function unifiedDiff(a: string, b: string, names: { a?: string; b?: string } = {}, context = 3): string {
  const hs = hunks(diffText(a, b), context);
  if (hs.length === 0) return '';
  const out = [`--- ${names.a ?? 'active'}`, `+++ ${names.b ?? 'draft'}`];
  for (const h of hs) {
    out.push(`@@ -${h.aStart},${h.aLen} +${h.bStart},${h.bLen} @@`);
    for (const o of h.ops) out.push(`${o.t === 'add' ? '+' : o.t === 'del' ? '-' : ' '}${o.s}`);
  }
  return out.join('\n');
}

/** Classify a line of a unified diff for colouring. */
export function unifiedLineKind(line: string): 'add' | 'del' | 'hunk' | 'meta' | 'ctx' {
  if (line.startsWith('+++') || line.startsWith('---')) return 'meta';
  if (line.startsWith('@@')) return 'hunk';
  if (line.startsWith('+')) return 'add';
  if (line.startsWith('-')) return 'del';
  return 'ctx';
}

// ------------------------------------------------------------------ YAML-ish change summary

const indentOf = (l: string): number => (/^\s*/.exec(l)?.[0].length ?? 0);
const stripComment = (l: string): string => l.replace(/(^|\s)#.*$/, '');
const keyOf = (l: string): string => {
  const m = /^\s*(?:- )?([^:[\]{}]+):/.exec(stripComment(l));
  return m ? m[1].trim() : l.trim();
};
const valOf = (l: string): string => {
  const k = l.indexOf(':');
  return k < 0 ? l.trim() : stripComment(l.slice(k + 1)).trim();
};

/** Dotted path of a YAML line from indentation (list items keyed by `- id:` / `- scope:`). */
export function yamlPathOf(lines: string[], idx: number): string {
  const parts = [keyOf(lines[idx])];
  let cur = indentOf(lines[idx]);
  for (let k = idx - 1; k >= 0 && cur > 0; k--) {
    const l = lines[k];
    if (!l.trim() || /^\s*#/.test(l)) continue;
    const ind = indentOf(l);
    if (ind < cur) {
      const item = /^\s*- (?:id|scope):\s*(\S+)/.exec(l);
      parts.unshift(item ? item[1] : keyOf(l));
      cur = ind;
    }
  }
  return parts.join('.');
}

/** Pair deleted/added lines with the same key into "chg" entries (prototype `summarize`). */
export function summarizeChanges(ops: DiffOp[], aLines: string[], bLines: string[]): LineChange[] {
  const out: LineChange[] = [];
  let k = 0;
  while (k < ops.length) {
    if (ops[k].t === 'ctx') {
      k++;
      continue;
    }
    const dels: DiffOp[] = [];
    const adds: DiffOp[] = [];
    while (k < ops.length && ops[k].t !== 'ctx') {
      (ops[k].t === 'del' ? dels : adds).push(ops[k]);
      k++;
    }
    const used = new Set<number>();
    for (const d of dels) {
      if (!d.s.trim()) continue;
      const ai = adds.findIndex((a, x) => !used.has(x) && keyOf(a.s) === keyOf(d.s));
      if (ai >= 0) {
        used.add(ai);
        out.push({ t: 'chg', path: yamlPathOf(bLines, adds[ai].bi ?? 0), from: valOf(d.s), to: valOf(adds[ai].s) });
      } else {
        out.push({ t: 'del', path: yamlPathOf(aLines, d.ai ?? 0) });
      }
    }
    adds.forEach((a, x) => {
      if (!used.has(x) && a.s.trim()) out.push({ t: 'add', path: yamlPathOf(bLines, a.bi ?? 0), to: valOf(a.s) });
    });
  }
  return out;
}

export function changeText(c: LineChange): string {
  if (c.t === 'chg') return `${c.path} ${c.from} → ${c.to}`;
  if (c.t === 'add') return `+ ${c.path}${c.to ? `: ${c.to}` : ''}`;
  return `− ${c.path}`;
}
