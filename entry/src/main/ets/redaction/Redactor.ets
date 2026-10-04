/**
 * On-device PII detection and placeholder redaction ("What data leaves" preview).
 *
 * Pure ArkTS, no network, no storage: the text never leaves the device. It mirrors the Aegis
 * gateway's local-first redaction (aegis/docs/CONTRACTS.md §3.4): entity names EMAIL, PHONE,
 * PESEL, IBAN and PAN, placeholders `[ENTITY_N]` numbered per entity and stable per value
 * (the same e-mail twice gets the same placeholder), checksum validation where one exists.
 *
 * Performance: every pattern is anchored with an explicit look-behind so it is only attempted at
 * the start of a token (not at every character of a long digit or letter run), all quantifiers
 * are bounded, and overlap checks use an occupancy bitmap, so a call is linear in the input
 * length. Boundaries are written as ASCII look-arounds instead of `\b`, which the ArkTS runtime
 * evaluates inconsistently next to some non-ASCII characters (ArkTS runtime FAQ, "Inconsistent
 * \b Handling"). The UI additionally caps the input at MAX_PREVIEW_CHARS and debounces typing.
 *
 * Known limitations: e-mail addresses are ASCII only (non-ASCII / internationalised local parts
 * and domains are not detected); IBANs are matched case-insensitively but must use the standard
 * grouping (no separators other than single spaces); phone numbers are a heuristic (9-15 digits).
 */

/** Upper bound the preview UI accepts (characters, UTF-16 code units). */
export const MAX_PREVIEW_CHARS: number = 20000;

export class Finding {
  entity: string;
  placeholder: string;
  masked: string;
  start: number; // offset in the original text
  length: number;

  constructor(entity: string, placeholder: string, masked: string, start: number, length: number) {
    this.entity = entity;
    this.placeholder = placeholder;
    this.masked = masked;
    this.start = start;
    this.length = length;
  }
}

export class RedactionResult {
  text: string = '';
  findings: Finding[] = [];
  /** Unique values per entity, e.g. EMAIL -> 2. */
  counts: Map<string, number> = new Map<string, number>();
}

class Span {
  entity: string;
  start: number;
  end: number;
  value: string;

  constructor(entity: string, start: number, end: number, value: string) {
    this.entity = entity;
    this.start = start;
    this.end = end;
    this.value = value;
  }
}

class Detector {
  entity: string;
  pattern: string;
  flags: string;
  validate: (value: string) => boolean;

  constructor(entity: string, pattern: string, flags: string, validate: (value: string) => boolean) {
    this.entity = entity;
    this.pattern = pattern;
    this.flags = flags;
    this.validate = validate;
  }
}

export class Checksums {
  static digitsOnly(s: string): string {
    let out: string = '';
    for (let i = 0; i < s.length; i++) {
      const c: string = s.charAt(i);
      if (c >= '0' && c <= '9') {
        out += c;
      }
    }
    return out;
  }

  /** Payment card numbers (PAN): 13-19 digits passing the Luhn check. */
  static luhn(value: string): boolean {
    const d: string = Checksums.digitsOnly(value);
    if (d.length < 13 || d.length > 19) {
      return false;
    }
    let sum: number = 0;
    let dbl: boolean = false;
    for (let i = d.length - 1; i >= 0; i--) {
      let n: number = d.charCodeAt(i) - 48;
      if (dbl) {
        n = n * 2;
        if (n > 9) {
          n -= 9;
        }
      }
      sum += n;
      dbl = !dbl;
    }
    return sum % 10 === 0;
  }

  /** Polish PESEL: 11 digits, weights 1-3-7-9, control digit, plausible month field. */
  static pesel(value: string): boolean {
    const d: string = Checksums.digitsOnly(value);
    if (d.length !== 11) {
      return false;
    }
    const w: number[] = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3];
    let sum: number = 0;
    for (let i = 0; i < 10; i++) {
      sum += (d.charCodeAt(i) - 48) * w[i];
    }
    const control: number = (10 - (sum % 10)) % 10;
    if (control !== d.charCodeAt(10) - 48) {
      return false;
    }
    const month: number = ((d.charCodeAt(2) - 48) * 10 + (d.charCodeAt(3) - 48)) % 20;
    const day: number = (d.charCodeAt(4) - 48) * 10 + (d.charCodeAt(5) - 48);
    return month >= 1 && month <= 12 && day >= 1 && day <= 31;
  }

  /** IBAN: ISO 13616 mod-97 check (country code, check digits, BBAN). */
  static iban(value: string): boolean {
    let s: string = '';
    for (let i = 0; i < value.length; i++) {
      const c: string = value.charAt(i);
      if (c !== ' ') {
        s += c.toUpperCase();
      }
    }
    if (s.length < 15 || s.length > 34) {
      return false;
    }
    const rearranged: string = s.substring(4) + s.substring(0, 4);
    let rem: number = 0;
    for (let i = 0; i < rearranged.length; i++) {
      const code: number = rearranged.charCodeAt(i);
      if (code >= 48 && code <= 57) {
        rem = (rem * 10 + (code - 48)) % 97;
      } else if (code >= 65 && code <= 90) {
        const v: number = code - 55; // A=10 ... Z=35
        rem = (rem * 100 + v) % 97;
      } else {
        return false;
      }
    }
    return rem === 1;
  }

  /**
   * Phone numbers: 9-15 digits after stripping separators. A bare run of digits without
   * "+" or separators only counts when it has exactly 9 digits (Polish national format),
   * so failed PESEL / card candidates are not re-labelled as phones.
   */
  static phone(value: string): boolean {
    const d: string = Checksums.digitsOnly(value);
    if (d.length < 9 || d.length > 15) {
      return false;
    }
    if (d.length === value.length) {
      return d.length === 9;
    }
    return true;
  }
}

/** Order matters: longer, checksummed entities first so a card number is not taken for a phone. */
const DETECTORS: Detector[] = [
  new Detector('EMAIL', '(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}', 'g',
    (v: string): boolean => true),
  new Detector('IBAN',
    '(?<![A-Za-z0-9])[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?(?![A-Za-z0-9])', 'gi',
    Checksums.iban),
  new Detector('PAN', '(?<![0-9])[0-9](?:[ -]?[0-9]){12,18}(?![0-9])', 'g', Checksums.luhn),
  new Detector('PESEL', '(?<![0-9])[0-9]{11}(?![0-9])', 'g', Checksums.pesel),
  new Detector('PHONE',
    '(?<![0-9+])(?:\\+[0-9]{1,3}[ -]?)?\\(?[0-9]{2,4}\\)?(?:[ -]?[0-9]{2,4}){2,4}(?![0-9])', 'g',
    Checksums.phone)
];

export class Redactor {
  static redact(input: string): RedactionResult {
    const spans: Span[] = [];
    const result: RedactionResult = new RedactionResult();
    if (input.length === 0) {
      return result;
    }
    // occupied[i] === 1 when code unit i already belongs to an accepted span.
    const occupied: Uint8Array = new Uint8Array(input.length);
    for (const det of DETECTORS) {
      const re: RegExp = new RegExp(det.pattern, det.flags);
      let m: RegExpExecArray | null = re.exec(input);
      while (m !== null) {
        const matched: string = m[0];
        const start: number = m.index;
        let value: string = matched;
        if (value.length > 0 && !det.validate(value) && det.entity === 'IBAN') {
          // The case-insensitive IBAN pattern can swallow a following 4-letter word
          // ("... 2874 from"): retry shorter prefixes that end at a group boundary.
          value = Redactor.validIbanPrefix(value, det.validate);
        } else if (value.length > 0 && !det.validate(value)) {
          value = '';
        }
        const end: number = start + value.length;
        if (value.length > 0 && !Redactor.overlaps(occupied, start, end)) {
          spans.push(new Span(det.entity, start, end, value));
          occupied.fill(1, start, end);
        }
        if (matched.length === 0) {
          re.lastIndex++;
        }
        m = re.exec(input);
      }
    }
    spans.sort((a: Span, b: Span) => a.start - b.start);

    const placeholders: Map<string, string> = new Map<string, string>();
    let out: string = '';
    let cursor: number = 0;
    for (const s of spans) {
      const key: string = s.entity + '|' + Redactor.normalize(s.entity, s.value);
      let ph: string | undefined = placeholders.get(key);
      if (ph === undefined) {
        const n: number = (result.counts.get(s.entity) ?? 0) + 1;
        result.counts.set(s.entity, n);
        ph = '[' + s.entity + '_' + n.toString() + ']';
        placeholders.set(key, ph);
      }
      out += input.substring(cursor, s.start) + ph;
      cursor = s.end;
      result.findings.push(new Finding(s.entity, ph, Redactor.mask(s.entity, s.value), s.start, s.end - s.start));
    }
    out += input.substring(cursor);
    result.text = out;
    return result;
  }

  /** Longest prefix of `value` that ends before a space and passes `validate`, or ''. */
  private static validIbanPrefix(value: string, validate: (v: string) => boolean): string {
    let cut: number = value.lastIndexOf(' ');
    while (cut > 0) {
      const candidate: string = value.substring(0, cut);
      if (validate(candidate)) {
        return candidate;
      }
      cut = candidate.lastIndexOf(' ');
    }
    return '';
  }

  /** O(end - start): spans are short, so this replaces the former O(spans) scan per match. */
  private static overlaps(occupied: Uint8Array, start: number, end: number): boolean {
    for (let i = start; i < end; i++) {
      if (occupied[i] === 1) {
        return true;
      }
    }
    return false;
  }

  private static normalize(entity: string, value: string): string {
    if (entity === 'EMAIL') {
      return value.toLowerCase();
    }
    if (entity === 'IBAN') {
      return value.split(' ').join('').toUpperCase();
    }
    return Checksums.digitsOnly(value);
  }

  /** Masked preview of the original value for the findings list (never the full value). */
  static mask(entity: string, value: string): string {
    if (entity === 'EMAIL') {
      const at: number = value.indexOf('@');
      if (at <= 1) {
        return '***' + value.substring(at);
      }
      return value.charAt(0) + '***' + value.substring(at);
    }
    if (entity === 'PAN') {
      const d: string = Checksums.digitsOnly(value);
      // PCI style: first 6 and last 4 only.
      return d.substring(0, 6) + '******' + d.substring(d.length - 4);
    }
    const compact: string = entity === 'IBAN' ? value.split(' ').join('') : Checksums.digitsOnly(value);
    if (compact.length <= 4) {
      return '****';
    }
    return compact.substring(0, 2) + '*'.repeat(Math.max(3, compact.length - 4)) +
      compact.substring(compact.length - 2);
  }
}

/** Fictional sample text (all identifiers are synthetic test values that pass the checksums). */
export const SAMPLE_TEXT: string =
  'Hi, please summarise the complaint from Anna Kowalska (anna.kowalska@example.com, ' +
  'tel. +48 601 234 567). Her PESEL is 44051401359 and the refund should go to ' +
  'PL61 1090 1014 0000 0712 1981 2874. She paid with card 4111 1111 1111 1111. ' +
  'CC the account manager at m.nowak@example.com.';
