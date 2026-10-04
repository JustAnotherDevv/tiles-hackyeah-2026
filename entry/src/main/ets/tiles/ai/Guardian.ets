/**
 * Guardian: on-device scam shield for seniors (docs/TILES_SPEC.md, mockups/ideas.html "Guardian").
 *
 * A deterministic, explainable rule engine (EN + PL keyword/pattern rules, no model, no network): it reads a call
 * transcript or SMS and returns a risk score, the red flags it found (each with the exact phrase that triggered
 * it), a calm instruction for the person on the phone and a caregiver alert. Everything runs in this process; the
 * caregiver preview is built with the existing on-device PII redactor so phone numbers / IBANs / card numbers are
 * replaced by placeholders before anything would be shared.
 *
 * Inputs in the demo are SIMULATED (labelled "Demo call" / "Demo SMS"); the app does not intercept real calls or
 * messages. The same analyze() entry point could later be fed by a real call-screening or SMS source.
 */
import { Redactor, RedactionResult } from '../../redaction/Redactor';
import { TileAction, TileBlock, TileSpec } from '../model/Tile';

/** One explainable warning sign. */
export class RedFlag {
  id: string = '';
  label: string = ''; // short English label, e.g. "Asks for money"
  labelPl: string = ''; // Polish label
  why: string = ''; // one-sentence explanation for the person / caregiver
  icon: string = ''; // sys.symbol.<icon>
  points: number = 0; // contribution to the risk score
  evidence: string = ''; // the phrase in the message that triggered the flag ('' for metadata flags)
}

/** A simulated incoming call transcript or SMS. */
export class GuardianSample {
  id: string = '';
  kind: string = 'call'; // call | sms
  lang: string = 'en'; // en | pl
  chip: string = ''; // short chip label, e.g. "Demo call · PL"
  from: string = ''; // caller display, e.g. "Unknown number"
  knownContact: boolean = false;
  text: string = '';
}

export class GuardianVerdict {
  risk: number = 0; // 0..100
  level: string = 'safe'; // safe | caution | scam
  flags: RedFlag[] = [];
  headline: string = ''; // huge calm line, in the message language
  instruction: string = ''; // what to do, in the message language
  headlineEn: string = ''; // English version (shown small when the message is Polish)
  instructionEn: string = '';
  alertTitle: string = ''; // caregiver notification title
  alertBody: string = ''; // caregiver notification body (no raw PII)
  sharedPreview: string = ''; // redacted excerpt that WOULD be shared with the caregiver
  redactedCount: number = 0; // number of PII values replaced by placeholders
  redactedKinds: string[] = []; // e.g. ["PHONE_1", "IBAN_1"]
}

class Rule {
  id: string;
  label: string;
  labelPl: string;
  why: string;
  icon: string;
  points: number;
  needles: string[]; // lower-case, diacritics stripped

  constructor(id: string, label: string, labelPl: string, why: string, icon: string, points: number,
    needles: string[]) {
    this.id = id;
    this.label = label;
    this.labelPl = labelPl;
    this.why = why;
    this.icon = icon;
    this.points = points;
    this.needles = needles;
  }
}

/** Keyword rules, EN + PL. Needles are matched on a lower-cased, diacritic-free copy of the text. */
const RULES: Rule[] = [
  new Rule('money', 'Asks for money', 'Prosi o pieniądze',
    'Strangers and "relatives" in trouble asking for cash or a transfer is the most common scam.',
    'wallet_fill', 30,
    ['money', 'cash', 'transfer', 'send me', 'pay ', 'payment', 'loan', 'bail', 'deposit', ' pln', 'euro',
      'dollars', 'pieniadz', 'pieniedz', 'kasa', 'kase', 'gotowk', 'przelew', 'przelej', 'pozycz', 'wplac',
      'kaucj', 'zlotych', ' zl', 'doplac', 'doplat', 'tysiac', 'tysiecy']),
  new Rule('urgency', 'Pressure: right now', 'Presja: natychmiast',
    'Scammers rush you so you have no time to think or ask someone.',
    'clock_fill', 18,
    ['right now', 'immediately', 'urgent', 'hurry', 'asap', 'today', 'within 15', 'within 10', 'minutes',
      'last chance', 'dzis', 'dzisiaj', 'teraz', 'natychmiast', 'pilne', 'pilnie', 'szybko', 'zaraz',
      'od razu', 'minut']),
  new Rule('secrecy', 'Asks you to keep it secret', 'Każe zachować tajemnicę',
    'A real family member will never ask you to hide something from the rest of the family.',
    'eye_slash', 20,
    ['don\'t tell', 'dont tell', 'do not tell', 'secret', 'between us', 'nobody', 'no one', 'nie mow',
      'nikomu', 'tajemnic', 'sekret', 'miedzy nami', 'nie dzwon']),
  new Rule('family', 'Pretends to be family', 'Podaje się za rodzinę',
    'The caller claims to be a grandchild or relative but is calling from a number you do not know.',
    'person_2', 16,
    ['grandma', 'grandpa', 'granny', 'it\'s me', 'its me', 'your grandson', 'your granddaughter', 'babciu',
      'babcia', 'dziadku', 'to ja', 'wnucz', 'ciociu', 'wujku']),
  new Rule('official', 'Pretends to be bank or police', 'Podaje się za bank lub policję',
    'Banks and the police never ask for codes, passwords or money transfers by phone or SMS.',
    'person_shield_fill', 16,
    ['police', 'officer', 'bank security', 'your bank', 'account is blocked', 'account blocked', 'policj',
      'prokurat', 'konsultant banku', 'twoje konto', 'konto zostalo', 'zablokowan']),
  new Rule('emergency', 'Sudden emergency story', 'Nagła dramatyczna historia',
    'An accident, hospital or arrest story is used to make you panic.',
    'exclamationmark_triangle_fill', 12,
    ['accident', 'hospital', 'arrested', 'in trouble', 'crash', 'wypadek', 'wypadku', 'szpital', 'areszt',
      'klopoty', 'potracil']),
  new Rule('code', 'Asks for a BLIK / SMS code', 'Prosi o kod BLIK / SMS',
    'A BLIK or SMS code gives away your money. Never read a code to anyone.',
    'lock_fill', 24,
    ['blik', 'code', 'kod', ' pin', 'password', 'haslo', 'one-time']),
  new Rule('link', 'Contains a link', 'Zawiera link',
    'Links in unexpected messages lead to fake payment pages that steal card details.',
    'link', 22,
    ['http://', 'https://', 'www.', 'bit.ly', 'click', 'kliknij', 'wejdz na', '.xyz', '.top', '.info/'])
];

const UNKNOWN_NUMBER_POINTS: number = 8;
const COMBO_POINTS: number = 10; // money together with pressure or secrecy
const MAX_RISK: number = 97;
const MIN_RISK: number = 3;

export class Guardian {
  /** Simulated inputs for the demo (clearly labelled). All numbers / accounts are synthetic test values. */
  static samples(): GuardianSample[] {
    const out: GuardianSample[] = [];
    out.push(Guardian.sample('call-pl', 'call', 'pl', 'Demo call · PL', 'Unknown number', false,
      'Babciu, to ja Tomek, miałem wypadek, potrzebuję pieniędzy dziś, nie mów mamie. ' +
        'Przelej 8000 zł na konto PL61 1090 1014 0000 0712 1981 2874.'));
    out.push(Guardian.sample('call-en', 'call', 'en', 'Demo call · EN', 'Unknown number', false,
      'Grandma, it\'s me, Tomek. I had an accident and I need money today. Please don\'t tell Mum. ' +
        'Call me back on +48 512 345 678.'));
    out.push(Guardian.sample('sms-pl', 'sms', 'pl', 'Demo SMS · PL', '+48 739 000 112', false,
      'Twoja paczka czeka. Dopłać 1,99 zł w ciągu 15 minut: http://paczka-doplata.xyz/pl ' +
        'i podaj kod BLIK.'));
    out.push(Guardian.sample('sms-en', 'sms', 'en', 'Demo SMS · EN', 'Unknown sender', false,
      'Bank security: your account is blocked. Confirm right now with your BLIK code at ' +
        'https://secure-bank-verify.top'));
    out.push(Guardian.sample('sms-safe', 'sms', 'en', 'Demo SMS · safe', 'Kasia (daughter)', true,
      'Hi Mum, I will pick you up at 5 for Sunday dinner. Love you!'));
    return out;
  }

  /**
   * Analyse a transcript / message. `knownContact` = the sender is in the person's contacts.
   * `caregiver` is the caregiver's first name used in the instruction ("Kasia already knows").
   */
  static analyze(text: string, knownContact: boolean, lang: string, caregiver: string,
    kind: string = 'call'): GuardianVerdict {
    const v: GuardianVerdict = new GuardianVerdict();
    const who: string = caregiver.length > 0 ? caregiver : 'Your family';
    const norm: string = Guardian.normalize(text);
    let score: number = 0;
    for (const rule of RULES) {
      const at: number = Guardian.findFirst(norm, rule.needles);
      if (at >= 0) {
        const f: RedFlag = new RedFlag();
        f.id = rule.id;
        f.label = rule.label;
        f.labelPl = rule.labelPl;
        f.why = rule.why;
        f.icon = rule.icon;
        f.points = rule.points;
        f.evidence = rule.id === 'link' ? Guardian.tokenAt(text, at) : Guardian.phraseAt(text, at);
        v.flags.push(f);
        score += rule.points;
      }
    }
    if (!knownContact) {
      const f: RedFlag = new RedFlag();
      f.id = 'unknown';
      f.label = 'Unknown number';
      f.labelPl = 'Nieznany numer';
      f.why = 'The sender is not in your contacts.';
      f.icon = 'phone_badge_nosign';
      f.points = UNKNOWN_NUMBER_POINTS;
      v.flags.push(f);
      score += UNKNOWN_NUMBER_POINTS;
    }
    const has = (id: string): boolean => v.flags.some((x: RedFlag) => x.id === id);
    if (has('money') && (has('urgency') || has('secrecy'))) {
      score += COMBO_POINTS;
    }
    // A known contact with no other signs is reassuring.
    if (knownContact && v.flags.length === 0) {
      score = 0;
    }
    v.risk = Math.max(MIN_RISK, Math.min(MAX_RISK, Math.round(score)));
    v.level = v.risk >= 65 ? 'scam' : (v.risk >= 35 ? 'caution' : 'safe');
    v.flags.sort((a: RedFlag, b: RedFlag) => b.points - a.points);

    if (v.level === 'scam') {
      v.headlineEn = 'This looks like a scam.';
      const call: boolean = kind === 'call';
      v.instructionEn = (call ? 'Hang up. ' : 'Do not reply or tap the link. ') + who + ' already knows.';
      v.headline = lang === 'pl' ? 'To wygląda na oszustwo.' : v.headlineEn;
      v.instruction = lang === 'pl' ?
        (call ? 'Rozłącz się. ' : 'Nie odpowiadaj i nie klikaj. ') + who + ' już wie.' : v.instructionEn;
    } else if (v.level === 'caution') {
      v.headlineEn = 'Be careful.';
      v.instructionEn = 'Do not send money or codes. Ask ' + who + ' first.';
      v.headline = lang === 'pl' ? 'Uważaj.' : v.headlineEn;
      v.instruction = lang === 'pl' ? 'Nie wysyłaj pieniędzy ani kodów. Najpierw zapytaj: ' + who + '.' :
        v.instructionEn;
    } else {
      v.headlineEn = 'This looks safe.';
      v.instructionEn = 'No warning signs found.';
      v.headline = lang === 'pl' ? 'Wygląda bezpiecznie.' : v.headlineEn;
      v.instruction = lang === 'pl' ? 'Nie znaleziono sygnałów ostrzegawczych.' : v.instructionEn;
    }

    // Caregiver preview: PII replaced on-device before anything would leave the phone.
    const red: RedactionResult = Redactor.redact(text);
    v.sharedPreview = red.text;
    v.redactedCount = red.findings.length;
    for (const fd of red.findings) {
      if (v.redactedKinds.indexOf(fd.placeholder) < 0) {
        v.redactedKinds.push(fd.placeholder);
      }
    }
    const top: string[] = [];
    for (let i = 0; i < v.flags.length && i < 3; i++) {
      top.push(v.flags[i].label.toLowerCase());
    }
    v.alertTitle = v.level === 'scam' ? 'Guardian alert: possible scam call' : 'Guardian: suspicious message';
    v.alertBody = 'Scam risk ' + v.risk.toString() + '%. Red flags: ' + top.join(', ') +
      '. Analysed on the phone; no recording or message text was sent.';
    return v;
  }

  /**
   * Tile template for Composer / SeedTiles: the home-screen entry point to Guardian. Its button is a TileAction
   * kind 'navigate' arg 'guardian' (route 'guardian' -> GuardianView).
   */
  static tile(caregiver: string): TileSpec {
    const who: string = caregiver.length > 0 ? caregiver : 'your family';
    const t: TileSpec = new TileSpec();
    t.id = 'guardian';
    t.type = 'guardian';
    t.title = 'Guardian';
    t.subtitle = 'Scam shield is on';
    t.icon = 'shield';
    t.color = 'mint';
    t.size = '2x1';
    t.source = 'seed';
    t.speakText = 'Guardian is on. If a call or message looks like a scam, I will tell you and let ' + who +
      ' know.';
    const b: TileBlock = new TileBlock();
    b.kind = 'text';
    b.text = 'Checks calls and SMS on this phone. ' + who + ' is told if something looks wrong.';
    const open: TileAction = new TileAction();
    open.label = 'Open Guardian';
    open.kind = 'navigate';
    open.arg = 'guardian';
    const actions: TileBlock = new TileBlock();
    actions.kind = 'buttons';
    actions.actions = [open];
    t.blocks = [b, actions];
    return t;
  }

  private static sample(id: string, kind: string, lang: string, chip: string, from: string,
    knownContact: boolean, text: string): GuardianSample {
    const s: GuardianSample = new GuardianSample();
    s.id = id;
    s.kind = kind;
    s.lang = lang;
    s.chip = chip;
    s.from = from;
    s.knownContact = knownContact;
    s.text = text;
    return s;
  }

  /** 'pl' when the text has Polish letters or common Polish words, else 'en'. */
  static detectLang(text: string): string {
    if (new RegExp('[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]').test(text)) {
      return 'pl';
    }
    const n: string = ' ' + text.toLowerCase() + ' ';
    const words: string[] = [' jest ', ' nie ', ' to ', ' na ', ' babciu ', ' prosze ', ' twoj', ' konto ', ' kod '];
    for (const w of words) {
      if (n.indexOf(w) >= 0) {
        return 'pl';
      }
    }
    return 'en';
  }

  /** Lower-case and strip Polish diacritics; keeps a 1:1 index mapping with the original text. */
  static normalize(text: string): string {
    const from: string = 'ąćęłńóśźżĄĆĘŁŃÓŚŹŻ';
    const to: string = 'acelnoszzacelnoszz';
    let out: string = '';
    for (let i = 0; i < text.length; i++) {
      const c: string = text.charAt(i);
      const k: number = from.indexOf(c);
      out += k >= 0 ? to.charAt(k) : c.toLowerCase().charAt(0);
    }
    return out;
  }

  private static findFirst(norm: string, needles: string[]): number {
    let best: number = -1;
    for (const n of needles) {
      const i: number = norm.indexOf(n);
      if (i >= 0 && (best < 0 || i < best)) {
        best = i;
      }
    }
    return best;
  }

  /** The whitespace-delimited token starting at / containing `at` (used for links). */
  private static tokenAt(text: string, at: number): string {
    let start: number = at;
    while (start > 0 && text.charAt(start - 1) !== ' ') {
      start--;
    }
    let end: number = at;
    while (end < text.length && text.charAt(end) !== ' ') {
      end++;
    }
    let t: string = text.substring(start, end);
    if (t.length > 40) {
      t = t.substring(0, 40) + '…';
    }
    return t;
  }

  /** The few words around a match, from the original text, for the "why" evidence line. */
  private static phraseAt(text: string, at: number): string {
    let start: number = at;
    while (start > 0 && text.charAt(start - 1) !== ' ' && text.charAt(start - 1) !== ',' &&
      text.charAt(start - 1) !== '.') {
      start--;
    }
    // Include the previous word for context ("need money", "nie mów").
    let s2: number = start - 1;
    while (s2 > 0 && text.charAt(s2 - 1) !== ' ' && text.charAt(s2 - 1) !== ',' && text.charAt(s2 - 1) !== '.') {
      s2--;
    }
    if (start > 0 && text.charAt(start - 1) === ' ' && s2 >= 0 && start - s2 <= 12) {
      start = s2;
    }
    let end: number = at;
    let words: number = 0;
    while (end < text.length && words < 2) {
      const c: string = text.charAt(end);
      if (c === ',' || c === '.' || c === '!' || c === '?' || c === ':') {
        break;
      }
      if (c === ' ' && end > at) {
        words++;
        if (words >= 2) {
          break;
        }
      }
      end++;
    }
    let p: string = text.substring(start, end).trim();
    if (p.length > 40) {
      p = p.substring(0, 40) + '…';
    }
    return p;
  }
}

/** Tile template constant (caregiver Kasia, Senior ICP) for Composer / SeedTiles. */
export const GUARDIAN_TILE: TileSpec = Guardian.tile('Kasia');
