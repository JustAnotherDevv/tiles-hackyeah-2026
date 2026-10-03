// Small LCS line diff for the policy editor (flash changed lines after a reload, mock diff/unified).
// Prefix/suffix trimmed so a 2 000-line policy with a one-line edit costs nothing.
// TODO(integration): B18's lib/line-diff.ts is the shared version; this local copy keeps B19
// independent of its exact signature. Owner: B19-dashboard-gov-policy.

export type LineOp = { t: 'ctx' | 'add' | 'del'; s: string; ai?: number; bi?: number };

export function diffLines(aText: string, bText: string): LineOp[] {
  const a = aText.split('\n');
  const b = bText.split('\n');
  let pre = 0;
  while (pre < a.length && pre < b.length && a[pre] === b[pre]) pre++;
  let suf = 0;
  while (suf < a.length - pre && suf < b.length - pre && a[a.length - 1 - suf] === b[b.length - 1 - suf]) suf++;
  const am = a.slice(pre, a.length - suf);
  const bm = b.slice(pre, b.length - suf);
  const ops: LineOp[] = [];
  for (let i = 0; i < pre; i++) ops.push({ t: 'ctx', s: a[i], ai: i, bi: i });
  const n = am.length;
  const m = bm.length;
  if (n * m > 4_000_000) {
    // pathological: fall back to "all deleted, all added"
    am.forEach((s, i) => ops.push({ t: 'del', s, ai: pre + i }));
    bm.forEach((s, j) => ops.push({ t: 'add', s, bi: pre + j }));
  } else {
    const dp: Uint32Array[] = [];
    for (let i = 0; i <= n; i++) dp.push(new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = am[i] === bm[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (am[i] === bm[j]) {
        ops.push({ t: 'ctx', s: am[i], ai: pre + i, bi: pre + j });
        i++;
        j++;
      } else if (dp[i + 1][j] >= dp[i][j + 1]) {
        ops.push({ t: 'del', s: am[i], ai: pre + i });
        i++;
      } else {
        ops.push({ t: 'add', s: bm[j], bi: pre + j });
        j++;
      }
    }
    while (i < n) ops.push({ t: 'del', s: am[i], ai: pre + i++ });
    while (j < m) ops.push({ t: 'add', s: bm[j], bi: pre + j++ });
  }
  for (let k = 0; k < suf; k++) ops.push({ t: 'ctx', s: a[a.length - suf + k], ai: a.length - suf + k, bi: b.length - suf + k });
  return ops;
}

/** 1-based line numbers in `b` that were added/changed vs `a`. */
export function changedLines(a: string, b: string): number[] {
  return diffLines(a, b)
    .filter((o) => o.t === 'add' && o.bi !== undefined)
    .map((o) => (o.bi as number) + 1);
}

/** Minimal unified diff (3 lines of context). */
export function unifiedDiff(a: string, b: string, name = 'policy.yaml'): string {
  const ops = diffLines(a, b);
  const show = new Set<number>();
  ops.forEach((o, i) => {
    if (o.t !== 'ctx') for (let k = i - 3; k <= i + 3; k++) show.add(k);
  });
  if (show.size === 0) return '';
  const out = [`--- a/${name}`, `+++ b/${name}`];
  let prev = -2;
  ops.forEach((o, i) => {
    if (!show.has(i)) return;
    if (i !== prev + 1) out.push(`@@ -${(o.ai ?? 0) + 1} +${(o.bi ?? 0) + 1} @@`);
    prev = i;
    out.push(`${o.t === 'add' ? '+' : o.t === 'del' ? '-' : ' '}${o.s}`);
  });
  return out.join('\n');
}
