// Redaction diff builders (plan 16 §2.3 "Redaction diff"). PURE module, node-testable.
// Keys "{seg}:{n}" link an original span, its outbound placeholder, response tokens and the entity table row.
import type { Redaction, WireView } from '@/api/types';
import type { DiffPart } from '../types';

const TOKEN_SRC = '\\[(?:REDACTED:[A-Z_]+|[A-Z][A-Z0-9_]*_\\d+)\\]|\\b\\d{6}\\*{6}\\d{4}\\b';
const isMask = (s: string) => /^\d{6}\*{6}\d{4}$/.test(s);
const isDrop = (s: string) => s.startsWith('[REDACTED:');

export interface KeyedRedaction {
  key: string;
  n: number;
  r: Redaction;
}

/** Redactions of one segment sorted by start with overlapping spans dropped (first kept wins). */
export function keyedRedactions(redactions: Redaction[], segIdx: number): KeyedRedaction[] {
  const list = redactions
    .filter((r) => r.segment_index === segIdx && r.end > r.start)
    .slice()
    .sort((a, b) => a.start - b.start || b.end - a.end);
  const out: KeyedRedaction[] = [];
  let lastEnd = -1;
  for (const r of list) {
    if (r.start < lastEnd) continue;
    out.push({ key: `${segIdx}:${out.length}`, n: out.length, r });
    lastEnd = r.end;
  }
  return out;
}

function tokenKind(token: string): DiffPart['kind'] {
  if (isDrop(token)) return 'dropped';
  if (isMask(token)) return 'masked';
  return 'placeholder';
}

/** Plain text with any leftover placeholder tokens marked (no hover key). */
function splitLoose(text: string, out: DiffPart[]): void {
  if (!text) return;
  const re = new RegExp(TOKEN_SRC, 'g');
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push({ kind: 'text', text: text.slice(last, m.index) });
    out.push({ kind: tokenKind(m[0]), text: m[0], placeholder: m[0] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ kind: 'text', text: text.slice(last) });
}

/** Original (local) text with detected entity spans. */
export function buildOriginalParts(text: string, redactions: Redaction[], segIdx: number): DiffPart[] {
  const out: DiffPart[] = [];
  let cursor = 0;
  for (const { key, r } of keyedRedactions(redactions, segIdx)) {
    const start = Math.max(cursor, Math.min(r.start, text.length));
    const end = Math.min(r.end, text.length);
    if (start > cursor) out.push({ kind: 'text', text: text.slice(cursor, start) });
    if (end > start) {
      out.push({
        kind: 'entity',
        text: text.slice(start, end),
        key,
        entity: r.entity,
        dataClass: r.data_class,
        placeholder: r.placeholder,
        reversible: r.reversible,
      });
    }
    cursor = Math.max(cursor, end);
  }
  if (cursor < text.length) out.push({ kind: 'text', text: text.slice(cursor) });
  return out;
}

/** Outbound (on-the-wire) text: each redaction's placeholder is located from a moving cursor. */
export function buildOutboundParts(text: string, redactions: Redaction[], segIdx: number): DiffPart[] {
  const out: DiffPart[] = [];
  let cursor = 0;
  for (const { key, r } of keyedRedactions(redactions, segIdx)) {
    if (!r.placeholder) continue;
    const at = text.indexOf(r.placeholder, cursor);
    if (at < 0) continue;
    splitLoose(text.slice(cursor, at), out);
    out.push({
      kind: tokenKind(r.placeholder),
      text: r.placeholder,
      key,
      entity: r.entity,
      dataClass: r.data_class,
      placeholder: r.placeholder,
      reversible: r.reversible,
    });
    cursor = at + r.placeholder.length;
  }
  splitLoose(text.slice(cursor), out);
  return out;
}

/** placeholder → first hover key, across all segments. */
export function placeholderKeys(redactions: Redaction[]): Map<string, KeyedRedaction> {
  const segs = Array.from(new Set(redactions.map((r) => r.segment_index))).sort((a, b) => a - b);
  const map = new Map<string, KeyedRedaction>();
  for (const s of segs) {
    for (const k of keyedRedactions(redactions, s)) {
      if (k.r.placeholder && !map.has(k.r.placeholder)) map.set(k.r.placeholder, k);
    }
  }
  return map;
}

/** placeholder → original value (sliced locally from wire.original; never leaves the browser). */
export function originalsFromWire(wire: Pick<WireView, 'original'> | null, redactions: Redaction[]): Map<string, string> {
  const map = new Map<string, string>();
  if (!wire) return map;
  for (const r of redactions) {
    const seg = wire.original[r.segment_index];
    if (!seg || map.has(r.placeholder)) continue;
    const v = seg.text.slice(r.start, r.end);
    if (v) map.set(r.placeholder, v);
  }
  return map;
}

/**
 * Response panes. `raw`: what the model returned (placeholders, keyed by placeholder string).
 * `local`: what the user sees — each reversible original value found in the text is marked "restored".
 */
export function buildResponseParts(
  text: string,
  mode: 'raw' | 'local',
  redactions: Redaction[],
  originals: Map<string, string>,
): DiffPart[] {
  const keys = placeholderKeys(redactions);
  const out: DiffPart[] = [];
  if (mode === 'raw') {
    const re = new RegExp(TOKEN_SRC, 'g');
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) out.push({ kind: 'text', text: text.slice(last, m.index) });
      const k = keys.get(m[0]);
      out.push({
        kind: tokenKind(m[0]),
        text: m[0],
        key: k?.key,
        entity: k?.r.entity,
        dataClass: k?.r.data_class ?? null,
        placeholder: m[0],
        reversible: k?.r.reversible,
      });
      last = m.index + m[0].length;
    }
    if (last < text.length) out.push({ kind: 'text', text: text.slice(last) });
    return out;
  }
  // local: locate restored values (longest first, non-overlapping)
  const candidates: { value: string; k: KeyedRedaction }[] = [];
  for (const [ph, k] of keys) {
    if (!k.r.reversible) continue;
    const value = originals.get(ph);
    if (value && value.length >= 2) candidates.push({ value, k });
  }
  candidates.sort((a, b) => b.value.length - a.value.length);
  const hits: { start: number; end: number; k: KeyedRedaction }[] = [];
  for (const c of candidates) {
    let from = 0;
    for (;;) {
      const at = text.indexOf(c.value, from);
      if (at < 0) break;
      const end = at + c.value.length;
      if (!hits.some((h) => at < h.end && end > h.start)) hits.push({ start: at, end, k: c.k });
      from = end;
    }
  }
  hits.sort((a, b) => a.start - b.start);
  let cursor = 0;
  for (const h of hits) {
    if (h.start > cursor) splitLoose(text.slice(cursor, h.start), out);
    out.push({
      kind: 'restored',
      text: text.slice(h.start, h.end),
      key: h.k.key,
      entity: h.k.r.entity,
      dataClass: h.k.r.data_class,
      placeholder: h.k.r.placeholder,
      reversible: true,
    });
    cursor = h.end;
  }
  if (cursor < text.length) splitLoose(text.slice(cursor), out);
  return out;
}

/** Segment indexes that carry redactions or whose outbound text differs from the original. */
export function changedSegmentIndexes(wire: Pick<WireView, 'original' | 'outbound'>, redactions: Redaction[]): number[] {
  const out = new Set<number>();
  for (const r of redactions) out.add(r.segment_index);
  const n = Math.max(wire.original.length, wire.outbound.length);
  for (let i = 0; i < n; i++) {
    if ((wire.original[i]?.text ?? '') !== (wire.outbound[i]?.text ?? '')) out.add(i);
  }
  return Array.from(out).filter((i) => i < n).sort((a, b) => a - b);
}

export interface RedactionStats {
  entities: number;
  tokenized: number;
  dropped: number;
  masked: number;
  segmentsChanged: number;
}

export function redactionStats(wire: Pick<WireView, 'original' | 'outbound'> | null, redactions: Redaction[]): RedactionStats {
  let tokenized = 0;
  let dropped = 0;
  let masked = 0;
  for (const r of redactions) {
    if (isDrop(r.placeholder)) dropped++;
    else if (isMask(r.placeholder)) masked++;
    else tokenized++;
  }
  return {
    entities: redactions.length,
    tokenized,
    dropped,
    masked,
    segmentsChanged: wire ? changedSegmentIndexes(wire, redactions).length : 0,
  };
}
