// Text-level YAML quick edits for the policy editor (UIG-09) — pure, erasable TS, no imports, so Node
// type-stripping can run it (UIG-V03). Edits are minimal line edits (comments and layout preserved,
// so the diff the judges see is one or two lines). Only block-style list items (`- id: X`) are edited;
// flow-style items (`- {id: X, ...}`) return null and the UI says "edit manually".
// Owner: B19-dashboard-gov-policy.

export interface TextEdit {
  yaml: string;
  /** 1-based line of the (first) edited line, for cursor jump + flash. */
  line: number;
}

export interface ControlBlock {
  id: string;
  /** 0-based index of the `- id:` line. */
  start: number;
  /** 0-based exclusive end line. */
  end: number;
  dashIndent: number;
  /** Indent of the item's fields (dashIndent + 2 for `- id:`). */
  fieldIndent: number;
  flow: boolean;
}

export interface ControlSummary {
  id: string;
  name: string | null;
  enabled: boolean;
  mode: string | null;
  action: string | null;
  threshold: number | null;
  line: number; // 1-based
  flow: boolean;
}

const lines = (s: string): string[] => s.split('\n');
const indentOf = (l: string): number => {
  const m = /^( *)/.exec(l);
  return m ? m[1].length : 0;
};
const isBlankOrComment = (l: string): boolean => /^\s*(#.*)?$/.test(l);

/** Split `value  # comment` → [value, '  # comment'] (ignores # inside quotes). */
export function splitComment(rest: string): [string, string] {
  let q: string | null = null;
  for (let i = 0; i < rest.length; i++) {
    const c = rest[i];
    if (q) {
      if (c === q) q = null;
      continue;
    }
    if (c === '"' || c === "'") q = c;
    else if (c === '#' && (i === 0 || /\s/.test(rest[i - 1]))) {
      let j = i;
      while (j > 0 && /\s/.test(rest[j - 1])) j--;
      return [rest.slice(0, j), rest.slice(j)];
    }
  }
  return [rest.replace(/\s+$/, ''), ''];
}

/** Render a JS scalar as YAML. Strings that look like other types or contain specials get quoted. */
export function yamlScalar(v: string | number | boolean | null): string {
  if (v === null) return 'null';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(4)));
  if (/^[A-Za-z_][\w.\-/@*]*$/.test(v) && !/^(true|false|null|yes|no|on|off|~)$/i.test(v)) return v;
  return JSON.stringify(v);
}

function unquote(v: string): string {
  const t = v.trim();
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) return t.slice(1, -1);
  return t;
}

/** Find a top-level key line (column 0). Returns 0-based index or -1. */
export function findTopLevelKey(yaml: string, key: string): number {
  const ls = lines(yaml);
  const re = new RegExp(`^${escapeRe(key)}:(\\s|$)`);
  return ls.findIndex((l) => re.test(l));
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Read a top-level scalar (e.g. `profile`). */
export function getTopLevelScalar(yaml: string, key: string): string | null {
  const ls = lines(yaml);
  const i = findTopLevelKey(yaml, key);
  if (i < 0) return null;
  const rest = ls[i].slice(key.length + 1);
  const [v] = splitComment(rest);
  return v.trim() ? unquote(v) : null;
}

/** Set a top-level scalar, keeping its trailing comment; inserts after `version:` (or at the top) if missing. */
export function setTopLevelScalar(yaml: string, key: string, value: string | number | boolean): TextEdit {
  const ls = lines(yaml);
  const i = findTopLevelKey(yaml, key);
  if (i >= 0) {
    const rest = ls[i].slice(key.length + 1);
    const [v, comment] = splitComment(rest);
    const lead = /^\s*/.exec(v)?.[0] || ' ';
    ls[i] = `${key}:${lead}${yamlScalar(value)}${comment}`;
    return { yaml: ls.join('\n'), line: i + 1 };
  }
  const after = ls.findIndex((l) => /^version:/.test(l));
  const at = after >= 0 ? after + 1 : 0;
  ls.splice(at, 0, `${key}: ${yamlScalar(value)}`);
  return { yaml: ls.join('\n'), line: at + 1 };
}

/** Find a direct child `key:` of a top-level section (block style). Returns 0-based line or -1. */
function findChild(ls: string[], parent: number, key: string): number {
  const re = new RegExp(`^( +)${escapeRe(key)}:(\\s|$)`);
  let childIndent = -1;
  for (let i = parent + 1; i < ls.length; i++) {
    const l = ls[i];
    if (isBlankOrComment(l)) continue;
    const ind = indentOf(l);
    if (ind === 0) return -1;
    if (childIndent < 0) childIndent = ind;
    if (ind === childIndent && re.test(l)) return i;
  }
  return -1;
}

/** Read `section.key` (two-level block mapping, e.g. defaults.mode). */
export function getNestedScalar(yaml: string, section: string, key: string): string | null {
  const ls = lines(yaml);
  const p = findTopLevelKey(yaml, section);
  if (p < 0) return null;
  const c = findChild(ls, p, key);
  if (c < 0) {
    // flow style: `section: {key: value, ...}`
    const m = new RegExp(`[{,]\\s*${escapeRe(key)}:\\s*([^,}]+)`).exec(ls[p]);
    return m ? unquote(m[1]) : null;
  }
  const rest = ls[c].slice(ls[c].indexOf(':') + 1);
  const [v] = splitComment(rest);
  return v.trim() ? unquote(v) : null;
}

/** Set `section.key` in a block mapping (e.g. defaults.mode: monitor). Null if the section is flow-style. */
export function setNestedScalar(yaml: string, section: string, key: string, value: string | number | boolean): TextEdit | null {
  const ls = lines(yaml);
  const p = findTopLevelKey(yaml, section);
  if (p < 0) {
    ls.push(`${section}:`, `  ${key}: ${yamlScalar(value)}`);
    return { yaml: ls.join('\n'), line: ls.length };
  }
  if (/\{/.test(splitComment(ls[p].slice(section.length + 1))[0])) return null;
  const c = findChild(ls, p, key);
  if (c >= 0) {
    const ind = indentOf(ls[c]);
    const rest = ls[c].slice(ls[c].indexOf(':') + 1);
    const [v, comment] = splitComment(rest);
    const lead = /^\s*/.exec(v)?.[0] || ' ';
    ls[c] = `${' '.repeat(ind)}${key}:${lead}${yamlScalar(value)}${comment}`;
    return { yaml: ls.join('\n'), line: c + 1 };
  }
  // insert as first child, matching the existing child indent (default 2)
  let childIndent = 2;
  for (let i = p + 1; i < ls.length; i++) {
    if (isBlankOrComment(ls[i])) continue;
    const ind = indentOf(ls[i]);
    if (ind > 0) childIndent = ind;
    break;
  }
  ls.splice(p + 1, 0, `${' '.repeat(childIndent)}${key}: ${yamlScalar(value)}`);
  return { yaml: ls.join('\n'), line: p + 2 };
}

/** Line range of the top-level `controls:` section (0-based, end exclusive). */
function controlsSection(ls: string[]): { start: number; end: number } | null {
  const s = ls.findIndex((l) => /^controls:(\s|$)/.test(l));
  if (s < 0) return null;
  let e = ls.length;
  for (let i = s + 1; i < ls.length; i++) {
    const l = ls[i];
    if (l.trim() === '' || /^\s*#/.test(l)) continue;
    if (indentOf(l) === 0 && !/^-/.test(l)) {
      e = i;
      break;
    }
  }
  // trailing comments/blank lines belong to the next section
  while (e - 1 > s && isBlankOrComment(ls[e - 1])) e--;
  return { start: s, end: e };
}

/** All control items in `controls:` (block and flow). */
export function listControlBlocks(yaml: string): ControlBlock[] {
  const ls = lines(yaml);
  const sec = controlsSection(ls);
  if (!sec) return [];
  const out: ControlBlock[] = [];
  const itemRe = /^( *)- +(?:id:\s*["']?([A-Za-z0-9_.-]+)["']?|\{\s*id:\s*["']?([A-Za-z0-9_.-]+)["']?)/;
  for (let i = sec.start + 1; i < sec.end; i++) {
    const m = itemRe.exec(ls[i]);
    if (!m) continue;
    const dashIndent = m[1].length;
    const flow = Boolean(m[3]);
    const id = (m[2] ?? m[3]) as string;
    let end = sec.end;
    for (let j = i + 1; j < sec.end; j++) {
      const l = ls[j];
      if (isBlankOrComment(l)) continue;
      if (indentOf(l) <= dashIndent) {
        end = j;
        break;
      }
    }
    // do not swallow trailing comment lines that precede the next item
    while (end - 1 > i && isBlankOrComment(ls[end - 1])) end--;
    out.push({ id, start: i, end, dashIndent, fieldIndent: dashIndent + 2, flow });
    if (flow) continue;
    i = end - 1;
  }
  return out;
}

export function findControlBlock(yaml: string, id: string): ControlBlock | null {
  return listControlBlocks(yaml).find((b) => b.id === id) ?? null;
}

/** Read a direct field of a block-style control (`enabled`, `mode`, `threshold`, `action`, `name`). */
export function getControlField(yaml: string, id: string, field: string): string | null {
  const b = findControlBlock(yaml, id);
  if (!b) return null;
  const ls = lines(yaml);
  if (b.flow) {
    const m = new RegExp(`[{,]\\s*${escapeRe(field)}:\\s*([^,}]+)`).exec(ls[b.start]);
    return m ? unquote(splitComment(m[1])[0]) : null;
  }
  const re = new RegExp(`^ {${b.fieldIndent}}${escapeRe(field)}:(.*)$`);
  for (let i = b.start; i < b.end; i++) {
    const src = i === b.start ? ls[i].replace(/^( *)- /, (_m, sp: string) => `${sp}  `) : ls[i];
    const m = re.exec(src);
    if (m) {
      const [v] = splitComment(m[1]);
      return v.trim() ? unquote(v) : null;
    }
  }
  return null;
}

/**
 * Set a direct field of a block-style control item: replace the value in place (keeping its comment)
 * or insert `field: value` right after the `- id:` line (after `name:` when present).
 * Returns null for flow-style items or unknown ids.
 */
export function setControlField(yaml: string, id: string, field: string, value: string | number | boolean | null): TextEdit | null {
  const b = findControlBlock(yaml, id);
  if (!b || b.flow) return null;
  const ls = lines(yaml);
  const pad = ' '.repeat(b.fieldIndent);
  const re = new RegExp(`^ {${b.fieldIndent}}${escapeRe(field)}:(.*)$`);
  for (let i = b.start + 1; i < b.end; i++) {
    const m = re.exec(ls[i]);
    if (m) {
      const [v, comment] = splitComment(m[1]);
      const lead = /^\s*/.exec(v)?.[0] || ' ';
      ls[i] = `${pad}${field}:${lead}${yamlScalar(value)}${comment}`;
      return { yaml: ls.join('\n'), line: i + 1 };
    }
  }
  let at = b.start + 1;
  const nameRe = new RegExp(`^ {${b.fieldIndent}}name:`);
  for (let i = b.start + 1; i < b.end; i++) {
    if (nameRe.test(ls[i])) {
      at = i + 1;
      break;
    }
  }
  ls.splice(at, 0, `${pad}${field}: ${yamlScalar(value)}`);
  return { yaml: ls.join('\n'), line: at + 1 };
}

/** Append a control item (block text without indentation, first line `- id: X`) to `controls:`. */
export function appendControl(yaml: string, block: string): TextEdit {
  const ls = lines(yaml);
  const sec = controlsSection(ls);
  const blockLines = block.replace(/\n+$/, '').split('\n');
  if (!sec) {
    const start = ls.length + 1;
    const out = [...ls, 'controls:', ...blockLines.map((l) => `  ${l}`)];
    return { yaml: out.join('\n'), line: start + 1 };
  }
  const items = listControlBlocks(yaml);
  const dash = items.length ? items[0].dashIndent : 2;
  const pad = ' '.repeat(dash);
  ls.splice(sec.end, 0, ...blockLines.map((l) => (l ? pad + l : l)));
  return { yaml: ls.join('\n'), line: sec.end + 1 };
}

/** Summaries of every control item (enabled defaults to true when absent). */
export function parseControls(yaml: string): ControlSummary[] {
  return listControlBlocks(yaml).map((b) => {
    const get = (f: string) => getControlField(yaml, b.id, f);
    const enabled = get('enabled');
    const thr = get('threshold');
    const t = thr === null ? null : Number(thr);
    return {
      id: b.id,
      name: get('name'),
      enabled: enabled === null ? true : !/^(false|no|off)$/i.test(enabled),
      mode: get('mode'),
      action: get('action'),
      threshold: t === null || Number.isNaN(t) ? null : t,
      line: b.start + 1,
      flow: b.flow,
    };
  });
}

/**
 * Add a keyword to CUS-01 (customer rules): extends the first `keywords: [...]` flow list inside the
 * CUS-01 block (or a block list), else inserts a new CUS-01 control. Null when CUS-01 exists but has
 * no keyword list we can edit safely.
 */
export function addCustomKeyword(yaml: string, keyword: string, ruleId = 'judge-keyword'): TextEdit | null {
  const b = findControlBlock(yaml, 'CUS-01');
  const q = JSON.stringify(keyword);
  if (!b) {
    return appendControl(
      yaml,
      [
        '- id: CUS-01',
        '  name: Customer-defined rules',
        '  action: block',
        '  params:',
        `    rules: [{id: ${ruleId}, text: "${keyword} must not leave the firm", keywords: [${q}], action: block}]`,
      ].join('\n'),
    );
  }
  const ls = lines(yaml);
  if (b.flow) {
    const l = ls[b.start];
    const m = /keywords:\s*\[([^\]]*)\]/.exec(l);
    if (!m) return null;
    if (m[1].toLowerCase().includes(keyword.toLowerCase())) return { yaml, line: b.start + 1 };
    ls[b.start] = l.replace(/keywords:\s*\[([^\]]*)\]/, (_x, inner: string) => `keywords: [${inner.trim() ? `${inner.trim()}, ` : ''}${q}]`);
    return { yaml: ls.join('\n'), line: b.start + 1 };
  }
  for (let i = b.start; i < b.end; i++) {
    const l = ls[i];
    const m = /keywords:\s*\[([^\]]*)\]/.exec(l);
    if (m) {
      if (m[1].toLowerCase().includes(keyword.toLowerCase())) return { yaml, line: i + 1 };
      ls[i] = l.replace(/keywords:\s*\[([^\]]*)\]/, (_x, inner: string) => `keywords: [${inner.trim() ? `${inner.trim()}, ` : ''}${q}]`);
      return { yaml: ls.join('\n'), line: i + 1 };
    }
    if (/^\s*keywords:\s*(#.*)?$/.test(l)) {
      // block list: append after the last `- item` at deeper indent
      const kInd = indentOf(l);
      let last = i;
      for (let j = i + 1; j < b.end; j++) {
        if (isBlankOrComment(ls[j])) continue;
        if (indentOf(ls[j]) <= kInd) break;
        last = j;
      }
      const itemInd = last > i ? indentOf(ls[last]) : kInd + 2;
      ls.splice(last + 1, 0, `${' '.repeat(itemInd)}- ${q}`);
      return { yaml: ls.join('\n'), line: last + 2 };
    }
  }
  // CUS-01 without keyword lists: add a rules param when there is no params block yet
  const hasParams = ls.slice(b.start, b.end).some((l) => new RegExp(`^ {${b.fieldIndent}}params:`).test(l));
  if (hasParams) return null;
  const pad = ' '.repeat(b.fieldIndent);
  ls.splice(b.end, 0, `${pad}params:`, `${pad}  rules: [{id: ${ruleId}, text: "${keyword} must not leave the firm", keywords: [${q}], action: block}]`);
  return { yaml: ls.join('\n'), line: b.end + 2 };
}

/**
 * Deliberately break the YAML for the rejection demo: indent the INJ-02 `threshold:` line (or the
 * first control field) with a TAB, which every YAML parser rejects with a line:col error.
 */
export function breakYaml(yaml: string): TextEdit {
  const ls = lines(yaml);
  const b = findControlBlock(yaml, 'INJ-02') ?? listControlBlocks(yaml).find((x) => !x.flow) ?? null;
  let target = -1;
  if (b && !b.flow) {
    for (let i = b.start + 1; i < b.end; i++) {
      if (/^\s+threshold:/.test(ls[i])) {
        target = i;
        break;
      }
    }
    if (target < 0) target = Math.min(b.start + 1, ls.length - 1);
  } else {
    target = ls.findIndex((l) => /^ +\S/.test(l));
    if (target < 0) target = 0;
  }
  ls[target] = ls[target].replace(/^ +/, '\t');
  if (!ls[target].startsWith('\t')) ls[target] = `\t${ls[target]}`;
  return { yaml: ls.join('\n'), line: target + 1 };
}

/** Budget limits in `budgets.limits` (flow items `- {scope: ..., window: ..., usd: ...}`). */
export interface LimitEntry {
  scope: string;
  window: string;
  values: Record<string, number>;
  line: number; // 1-based
}

export function parseBudgetLimits(yaml: string): LimitEntry[] {
  const ls = lines(yaml);
  const out: LimitEntry[] = [];
  const b = ls.findIndex((l) => /^budgets:(\s|$)/.test(l));
  if (b < 0) return out;
  for (let i = b + 1; i < ls.length; i++) {
    const l = ls[i];
    if (!isBlankOrComment(l) && indentOf(l) === 0) break;
    const m = /^\s*-\s*\{(.*)\}\s*(#.*)?$/.exec(l);
    if (!m) continue;
    const fields: Record<string, string> = {};
    for (const part of m[1].split(',')) {
      const k = part.indexOf(':');
      if (k < 0) continue;
      fields[part.slice(0, k).trim()] = unquote(part.slice(k + 1));
    }
    if (!fields.scope) continue;
    const values: Record<string, number> = {};
    for (const [k, v] of Object.entries(fields)) {
      if (['scope', 'window', 'label', 'on_soft', 'on_hard'].includes(k)) continue;
      const n = Number(v);
      if (!Number.isNaN(n)) values[k] = n;
    }
    out.push({ scope: fields.scope, window: fields.window ?? 'day', values, line: i + 1 });
  }
  return out;
}

/** Set one dimension of a budget limit line (flow item). Null when not found. */
export function setBudgetLimit(yaml: string, scope: string, window: string, dimension: string, value: number): TextEdit | null {
  const entry = parseBudgetLimits(yaml).find((e) => e.scope === scope && e.window === window);
  if (!entry) return null;
  const ls = lines(yaml);
  const i = entry.line - 1;
  const re = new RegExp(`(\\b${escapeRe(dimension)}:\\s*)(-?[\\d.]+)`);
  if (re.test(ls[i])) ls[i] = ls[i].replace(re, `$1${yamlScalar(value)}`);
  else ls[i] = ls[i].replace(/\}(\s*(#.*)?)$/, `, ${dimension}: ${yamlScalar(value)}}$1`);
  return { yaml: ls.join('\n'), line: entry.line };
}

/** Kill-switch state from `budgets.kill_switch` (flow mapping on one line, or block mapping). */
export interface KillSwitchText {
  global: boolean;
  teams: string[];
  members: string[];
  agents: string[];
  sessions: string[];
}

function parseFlowList(s: string): string[] {
  return s
    .split(',')
    .map((x) => unquote(x))
    .filter(Boolean);
}

export function getKillSwitch(yaml: string): KillSwitchText {
  const out: KillSwitchText = { global: false, teams: [], members: [], agents: [], sessions: [] };
  const line = lines(yaml).find((l) => /^\s+kill_switch:\s*\{/.test(l));
  if (!line) return out;
  out.global = /\bglobal:\s*true\b/.test(line);
  for (const k of ['teams', 'members', 'agents', 'sessions'] as const) {
    const m = new RegExp(`\\b${k}:\\s*\\[([^\\]]*)\\]`).exec(line);
    if (m) out[k] = parseFlowList(m[1]);
  }
  return out;
}

/**
 * Turn a kill switch on/off for `global` or `team:x` / `member:x` / `agent:x` / `session:x`
 * (edits the one-line flow mapping `kill_switch: {global: false, teams: [], ...}`). Null if absent.
 */
export function setKillSwitch(yaml: string, scope: string, active: boolean): TextEdit | null {
  const ls = lines(yaml);
  const i = ls.findIndex((l) => /^\s+kill_switch:\s*\{/.test(l));
  if (i < 0) return null;
  let l = ls[i];
  if (scope === 'global') {
    l = /\bglobal:\s*(true|false)/.test(l) ? l.replace(/\bglobal:\s*(true|false)/, `global: ${active}`) : l.replace('{', `{global: ${active}, `);
  } else {
    const c = scope.indexOf(':');
    const type = c < 0 ? scope : scope.slice(0, c);
    const id = c < 0 ? '' : scope.slice(c + 1);
    const key = ({ team: 'teams', member: 'members', agent: 'agents', session: 'sessions' } as Record<string, string>)[type];
    if (!key || !id) return null;
    const re = new RegExp(`(\\b${key}:\\s*\\[)([^\\]]*)(\\])`);
    const m = re.exec(l);
    const cur = m ? parseFlowList(m[2]) : [];
    const next = active ? (cur.includes(id) ? cur : [...cur, id]) : cur.filter((x) => x !== id);
    const rendered = next.map((x) => yamlScalar(x)).join(', ');
    l = m ? l.replace(re, `$1${rendered}$3`) : l.replace(/\}(\s*(#.*)?)$/, `, ${key}: [${rendered}]}$1`);
  }
  ls[i] = l;
  return { yaml: ls.join('\n'), line: i + 1 };
}

/** Append a new flow limit item to `budgets.limits` (after the last existing item). */
export function addBudgetLimit(yaml: string, scope: string, window: string, dimension: string, value: number): TextEdit | null {
  const all = parseBudgetLimits(yaml);
  if (all.length === 0) return null;
  const last = all[all.length - 1];
  const ls = lines(yaml);
  const ind = indentOf(ls[last.line - 1]);
  ls.splice(last.line, 0, `${' '.repeat(ind)}- {scope: ${JSON.stringify(scope)}, window: ${window}, ${dimension}: ${yamlScalar(value)}}`);
  return { yaml: ls.join('\n'), line: last.line + 1 };
}
