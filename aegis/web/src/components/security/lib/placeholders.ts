// Placeholder helpers (CONTRACTS §3.4 entities). PURE module, node-testable.
import type { DataClass } from '@/api/types';

/** `[ENTITY_N]` reversible placeholders and `[REDACTED:ENTITY]` irreversible drops. Global — reset lastIndex. */
export const PLACEHOLDER_RE = /\[(?:REDACTED:[A-Z_]+|[A-Z][A-Z0-9_]*_\d+)\]/g;
/** PCI display mask first6/last4 (never more digits). */
export const PCI_MASK_RE = /\b\d{6}\*{6}\d{4}\b/g;
/** Placeholder or PCI mask, used to highlight previews. */
export const TOKEN_RE = /\[(?:REDACTED:[A-Z_]+|[A-Z][A-Z0-9_]*_\d+)\]|\b\d{6}\*{6}\d{4}\b/g;

export const ENTITY_CLASS: Record<string, DataClass> = {
  EMAIL: 'CONFIDENTIAL', PHONE: 'CONFIDENTIAL', PERSON: 'CONFIDENTIAL', ADDRESS: 'CONFIDENTIAL', DOB: 'CONFIDENTIAL',
  PESEL: 'CONFIDENTIAL', NIP: 'CONFIDENTIAL', REGON: 'CONFIDENTIAL', PL_ID_CARD: 'CONFIDENTIAL', PASSPORT: 'CONFIDENTIAL',
  IBAN: 'CONFIDENTIAL', HEALTH: 'CONFIDENTIAL',
  PAN: 'RESTRICTED', CARD_EXPIRY: 'RESTRICTED', CVV: 'RESTRICTED', TRACK_DATA: 'RESTRICTED',
  AWS_KEY: 'SECRET', AWS_SECRET: 'SECRET', GITHUB_TOKEN: 'SECRET', SLACK_TOKEN: 'SECRET', STRIPE_KEY: 'SECRET',
  OPENAI_KEY: 'SECRET', ANTHROPIC_KEY: 'SECRET', JWT: 'SECRET', PRIVATE_KEY: 'SECRET', PASSWORD: 'SECRET',
  CONNECTION_STRING: 'SECRET', GENERIC_SECRET: 'SECRET',
  IP_ADDRESS: 'INTERNAL', HOSTNAME: 'INTERNAL', INTERNAL_URL: 'INTERNAL', FILE_PATH: 'INTERNAL', USERNAME: 'INTERNAL',
  GIT_EMAIL: 'INTERNAL',
};

export function dataClassOf(entity: string | null | undefined): DataClass | null {
  if (!entity) return null;
  return ENTITY_CLASS[entity] ?? null;
}

/** Entity name encoded in a placeholder: `[PESEL_1]` → PESEL, `[REDACTED:CVV]` → CVV, PCI mask → PAN. */
export function entityOfPlaceholder(ph: string): string | null {
  if (/^\d{6}\*{6}\d{4}$/.test(ph)) return 'PAN';
  const m = /^\[(?:REDACTED:([A-Z_]+)|([A-Z][A-Z0-9_]*)_\d+)\]$/.exec(ph);
  if (!m) return null;
  return m[1] ?? m[2] ?? null;
}

export function isIrreversible(placeholder: string): boolean {
  return placeholder.startsWith('[REDACTED:');
}

export function isPciMask(s: string): boolean {
  return /^\d{6}\*{6}\d{4}$/.test(s);
}

export interface TokenPiece {
  text: string;
  token: boolean;
}

/** Split text into plain pieces and placeholder/PCI-mask tokens (for preview highlighting). */
export function splitTokens(text: string): TokenPiece[] {
  const out: TokenPiece[] = [];
  const re = new RegExp(TOKEN_RE.source, 'g');
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), token: false });
    out.push({ text: m[0], token: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), token: false });
  return out;
}
