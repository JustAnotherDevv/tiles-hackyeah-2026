/**
 * Tiles on-device intent + slot extraction (EN + PL). Pure ArkTS, no kits, deterministic.
 *
 * This is the "understanding" half of the rule-based generator used by Composer.ets: it detects
 * which tile templates a request asks for and pulls out slots (time, day, people, place, food,
 * budget, medicine, subject, list items, minutes). No network and no LLM is involved.
 */

export class Slots {
  lang: string = 'en';          // 'pl' when the prompt looks Polish
  raw: string = '';
  times: string[] = [];         // 'HH:MM'
  day: string = '';             // canonical EN key: monday..sunday|today|tomorrow|weekend
  people: string[] = [];        // display names (nominative)
  place: string = '';
  food: string = '';            // e.g. 'vegan', 'pizza'
  budget: string = '';          // e.g. '80 zł'
  medicine: string = '';        // display name
  subject: string = '';         // canonical EN key: math|english|...
  items: string[] = [];         // list items
  minutes: number = 0;
  amount: string = '';          // money amount seen in a letter/bill text
  date: string = '';            // date seen in a letter/bill text ('15.10')
  sender: string = '';          // letter/bill sender keyword (ZUS, PGE...)
  twiceDaily: boolean = false;
}

class IntentRule {
  intent: string;
  words: string[];
  constructor(intent: string, words: string[]) {
    this.intent = intent;
    this.words = words;
  }
}

/** Generic intents give way when a more specific template matches. */
export const GENERIC_INTENTS: string[] = ['reminder', 'note', 'checklist'];

/** Keyword stems on diacritic-free lower-case text. Leading space = word start. */
const RULES: IntentRule[] = [
  new IntentRule('scam', [' scam', 'fraud', 'suspicious', 'is this real', 'is it real', 'oszust', 'podejrzan',
    'wyludz', 'na wnuczka', 'na policjanta', 'phishing', 'fake call', 'fake sms', 'dziwny sms', 'dziwny telefon']),
  new IntentRule('letter', ['letter', ' bill', 'invoice', 'explain this', ' pismo', 'pisma', 'rachunek', 'rachunku',
    'faktur', 'wyjasnij to', 'wyjasnij mi to', 'co to za pismo', ' zus', 'urzad', 'wezwanie', 'tax form', ' pit ']),
  new IntentRule('sos', [' sos', 'emergency', ' i fell', 'ambulance', 'karetk', 'ratunku', 'upadl', 'nagly wypadek',
    'alarm button', 'przycisk alarm', 'panic button', 'i need help now']),
  new IntentRule('pills', [' pill', 'medicine', 'medication', 'tablets', ' lek ', ' leki', ' leku',
    ' lekow', ' lekach', ' lekami', ' lekarstw', 'tabletk', 'pigulk', 'witamin', 'vitamin', 'aspirin', 'aspiryn', 'metformin', 'ibuprofen',
    'paracetamol', 'insulin', 'euthyrox', 'bisoprolol', 'magnes', 'omega', ' apap', 'polopiryn', 'dose', 'dawk']),
  new IntentRule('call', [' call ', ' call', ' ring ', ' phone ', ' dial', 'zadzwon', 'zadzwonic', 'polacz',
    'telefon do', 'facetime']),
  new IntentRule('weather', ['weather', ' wear', 'umbrella', ' rain', ' coat', ' jacket', 'pogod', 'ubrac',
    'ubierz', 'parasol', 'deszcz', 'kurtk', 'zimno', ' cold out', 'is it cold']),
  new IntentRule('plan', ['dinner', 'lunch', 'breakfast', 'brunch', ' meet ', 'meet up', 'meetup', 'hang out',
    'party', 'cinema', 'movie night', 'drinks', 'kolacj', ' obiad', 'sniadani', 'spotkani', 'spotkac',
    'spotykamy', 'znajom', 'impreza', ' kino', 'wyjscie', 'with friends', 'ze znajomymi', 'plan a', 'zaplanuj']),
  new IntentRule('homework', ['homework', 'lekcje', 'zadanie domowe', 'zadania domowe', 'praca domowa',
    'odrabian', 'worksheet', 'school task', 'do szkoly', 'spelling', 'dyktand']),
  new IntentRule('timer', ['focus', 'timer', 'pomodoro', 'concentrat', 'skupien', 'minutnik', 'stoper',
    'study session', 'nauka przez', 'countdown', 'odliczan']),
  new IntentRule('screentime', ['screen time', 'screentime', 'czas ekran', 'czas przed ekranem', 'how long have i',
    'ile czasu', 'tablet time', 'game time', 'czas na gry', 'bajki']),
  new IntentRule('shopping', ['shopping', 'groceries', 'grocery', ' buy ', 'zakup', ' kupic', ' kup ', 'sklep',
    'supermarket']),
  new IntentRule('commute', ['commute', ' bus ', ' tram', 'train', 'dojazd', 'autobus', 'tramwaj', 'pociag',
    'to work', 'do pracy']),
  new IntentRule('adventure', ['adventure', 'something fun', 'przygod', 'cos fajnego', 'zabaw', 'game idea',
    'bored', 'nudzi']),
  new IntentRule('checklist', ['checklist', 'to-do', 'todo', 'to do list', 'tasks', 'lista zadan', 'do zrobienia',
    'packing', ' pack ', 'spakowac', 'list for', 'lista']),
  new IntentRule('reminder', ['remind', 'reminder', "don't forget", 'dont forget', 'przypomnij', 'przypomnien',
    'nie zapomnij', 'pamietaj']),
  new IntentRule('note', [' note', 'write down', 'remember that', 'notatk', 'zapisz', 'zanotuj', 'notuj'])
];

const PL_HINTS: string[] = [' z ', ' w ', ' na ', ' o ', ' mi ', 'mnie', 'jutro', 'dzis', 'prosze',
  'zadzwon', 'przypomnij', 'kolacj', 'piatek', 'sobot', 'niedziel', 'zakupy', 'lekcje', 'pogod', 'jak ',
  'czy ', 'moj', 'dla ', 'albo', 'oraz', 'ze ', 'jest', 'zrob', 'dodaj'];

const PL_CHARS: string = 'ąćęłńóśźżĄĆĘŁŃÓŚŹŻ';

/** Lower-case + strip Polish diacritics, padded with spaces for word-start matching. */
export function norm(s: string): string {
  const from = 'ąćęłńóśźż';
  const to = 'acelnoszz';
  let out = '';
  const low = s.toLowerCase();
  for (let i = 0; i < low.length; i++) {
    const c = low.charAt(i);
    const k = from.indexOf(c);
    out += k >= 0 ? to.charAt(k) : c;
  }
  out = out.replace(/[!?;()"„”]/g, ' ').replace(/\s+/g, ' ');
  return ' ' + out.trim() + ' ';
}

export function detectLang(text: string): string {
  // 'zł' (currency) appears in English requests too, so it does not count as a Polish letter.
  const t = text.replace(/zł/gi, 'zl');
  for (let i = 0; i < t.length; i++) {
    if (PL_CHARS.indexOf(t.charAt(i)) >= 0) {
      return 'pl';
    }
  }
  const n = norm(text);
  let hits = 0;
  for (const h of PL_HINTS) {
    if (n.indexOf(h) >= 0) {
      hits++;
    }
  }
  const en = [' the ', ' my ', ' me ', ' and ', ' with ', ' at ', ' for ', ' to ', ' is ', 'please', ' a ', ' what ',
    ' should', ' today', ' how ', ' do i ', ' you', ' this', ' some', ' left', ' much', ' fun', ' remind', ' call ',
    ' next ', ' i ', ' timer', ' focus', ' note', ' shopping', ' homework', ' dinner', ' weather'];
  let enHits = 0;
  for (const h of en) {
    if (n.indexOf(h) >= 0) {
      enHits++;
    }
  }
  return hits > enHits ? 'pl' : 'en';
}

export class IntentScore {
  intent: string = '';
  score: number = 0;
  first: number = 0;   // first match position, used as a tiebreaker (earlier = primary)
}

/** All matching intents, best first. Generic intents are removed when a specific one matches. */
export function detectIntents(text: string): string[] {
  const n = norm(text);
  // An explicit leading keyword wins ("Note: buy batteries" is a note, not a shopping list).
  if (/^ (note|notatka|zapisz|zanotuj)\b/.test(n)) {
    return ['note'];
  }
  if (/^ (checklist|to-do|todo|lista zadan|lista)\b/.test(n) && !/^ lista zakupow/.test(n)) {
    return ['checklist'];
  }
  const scores: IntentScore[] = [];
  for (const r of RULES) {
    let score = 0;
    let first = 100000;
    for (const w of r.words) {
      const at = n.indexOf(w);
      if (at >= 0) {
        score++;
        first = Math.min(first, at);
      }
    }
    if (score > 0) {
      const s = new IntentScore();
      s.intent = r.intent;
      s.score = score;
      s.first = first;
      scores.push(s);
    }
  }
  // Medicine names imply pills even without the word "pill".
  if (findMedicine(text).length > 0 && !hasIntent(scores, 'pills')) {
    const s = new IntentScore();
    s.intent = 'pills';
    s.score = 1;
    s.first = 0;
    scores.push(s);
  }
  scores.sort((a: IntentScore, b: IntentScore) => b.score !== a.score ? b.score - a.score : a.first - b.first);
  const specific: string[] = [];
  const generic: string[] = [];
  for (const s of scores) {
    if (GENERIC_INTENTS.indexOf(s.intent) >= 0) {
      generic.push(s.intent);
    } else {
      specific.push(s.intent);
    }
  }
  // Scam / letter checks are single-purpose: never mix them with other templates.
  if (specific.length > 0 && (specific[0] === 'scam' || specific[0] === 'letter')) {
    return [specific[0]];
  }
  // Homework already contains a timer; timer + homework stay both only if the user asked for focus explicitly.
  const out: string[] = [];
  for (const i of specific) {
    out.push(i);
  }
  if (out.length === 0) {
    for (const g of generic) {
      out.push(g);
    }
  } else if (generic.indexOf('reminder') >= 0 && (out[0] === 'plan' || out[0] === 'call')) {
    // "Dinner Friday … and remind me Thursday" → plan + reminder.
    if (/(remind|przypomnij)[^.]*\b(and|i|oraz|tez|also)\b|\b(and|i|oraz|also)\b[^.]*(remind|przypomnij)/.test(n)) {
      out.push('reminder');
    }
  }
  return out.slice(0, 3);
}

function hasIntent(list: IntentScore[], intent: string): boolean {
  for (const s of list) {
    if (s.intent === intent) {
      return true;
    }
  }
  return false;
}

function pad2(n: number): string {
  return n < 10 ? '0' + n.toString() : n.toString();
}

function pushTime(out: string[], h: number, m: number): void {
  if (h < 0 || h > 23 || m < 0 || m > 59) {
    return;
  }
  const t = pad2(h) + ':' + pad2(m);
  if (out.indexOf(t) < 0) {
    out.push(t);
  }
}

export function findTimes(text: string): string[] {
  const n = norm(text);
  const out: string[] = [];
  // 8:00, 19.30, 7:15pm
  const re1 = /(\d{1,2})[:.](\d{2})\s*(am|pm)?/g;
  let m: RegExpExecArray | null = re1.exec(n);
  while (m !== null) {
    let h = parseInt(m[1]);
    if (m[3] === 'pm' && h < 12) {
      h += 12;
    }
    if (m[3] === 'am' && h === 12) {
      h = 0;
    }
    // Skip dates like 15.10 (day.month) when the "hour" would not be a time.
    const after = n.substring(m.index + m[0].length, m.index + m[0].length + 1);
    if (!(m[0].indexOf('.') >= 0 && (after === '.' || parseInt(m[2]) > 59 || h > 23))) {
      pushTime(out, h, parseInt(m[2]));
    }
    m = re1.exec(n);
  }
  // 8am, 7 pm
  const re2 = /\b(\d{1,2})\s*(am|pm)\b/g;
  m = re2.exec(n);
  while (m !== null) {
    let h = parseInt(m[1]);
    if (m[2] === 'pm' && h < 12) {
      h += 12;
    }
    if (m[2] === 'am' && h === 12) {
      h = 0;
    }
    pushTime(out, h, 0);
    m = re2.exec(n);
  }
  // "at 8", "o 8", "na 19", "godz. 7", "o godzinie 20"
  const re3 = /\b(at|o|na|godz|godzinie|around|okolo)\.?\s+(godz\.?\s+|godzinie\s+)?(\d{1,2})\b(?![:.]\d)(?!\s*(min|minut|zl|pln|%|osob|people|friends))/g;
  m = re3.exec(n);
  while (m !== null) {
    const h = parseInt(m[3]);
    if (h <= 23) {
      // "at 7" with no am/pm in a dinner context → evening.
      const hh = (h >= 1 && h <= 6) ? h + 12 : h;
      pushTime(out, hh, 0);
    }
    m = re3.exec(n);
  }
  if (out.length === 0) {
    if (/\b(morning|rano|rankiem|po przebudzeniu)/.test(n)) {
      pushTime(out, 8, 0);
    }
    if (/\b(noon|midday|w poludnie)/.test(n)) {
      pushTime(out, 12, 0);
    }
    if (/\b(afternoon|po poludniu)/.test(n)) {
      pushTime(out, 15, 0);
    }
    if (/\b(evening|wieczor)/.test(n)) {
      pushTime(out, 19, 0);
    }
    if (/\b(night|bedtime|przed snem|na noc)/.test(n)) {
      pushTime(out, 21, 0);
    }
  }
  if (/\b(twice a day|two times a day|2x a day|2 times a day|dwa razy dziennie|2x dziennie|2 razy dziennie)/.test(n)) {
    pushTime(out, 8, 0);
    pushTime(out, 20, 0);
  }
  out.sort();
  return out.slice(0, 4);
}

class DayWord {
  key: string;
  stems: string[];
  constructor(key: string, stems: string[]) {
    this.key = key;
    this.stems = stems;
  }
}

const DAYS: DayWord[] = [
  new DayWord('monday', ['monday', ' mon ', 'poniedzial']),
  new DayWord('tuesday', ['tuesday', ' tue ', 'wtor']),
  new DayWord('wednesday', ['wednesday', ' wed ', ' srod', ' sroda', ' srode']),
  new DayWord('thursday', ['thursday', ' thu ', 'czwart']),
  new DayWord('friday', ['friday', ' fri ', 'piatek', 'piatk']),
  new DayWord('saturday', ['saturday', ' sat ', 'sobot']),
  new DayWord('sunday', ['sunday', ' sun ', 'niedziel']),
  new DayWord('tomorrow', ['tomorrow', 'jutro']),
  new DayWord('today', ['today', 'tonight', ' dzis', 'dzisiaj', 'wieczorem dzis']),
  new DayWord('weekend', ['weekend'])
];

export function findDay(text: string): string {
  const n = norm(text);
  let best = '';
  let bestAt = 100000;
  for (const d of DAYS) {
    for (const s of d.stems) {
      const at = n.indexOf(s);
      if (at >= 0 && at < bestAt) {
        best = d.key;
        bestAt = at;
      }
    }
  }
  return best;
}

const DAY_EN: Map<string, string> = new Map<string, string>([
  ['monday', 'Monday'], ['tuesday', 'Tuesday'], ['wednesday', 'Wednesday'], ['thursday', 'Thursday'],
  ['friday', 'Friday'], ['saturday', 'Saturday'], ['sunday', 'Sunday'], ['tomorrow', 'Tomorrow'],
  ['today', 'Today'], ['weekend', 'Weekend']
]);
const DAY_PL: Map<string, string> = new Map<string, string>([
  ['monday', 'Poniedziałek'], ['tuesday', 'Wtorek'], ['wednesday', 'Środa'], ['thursday', 'Czwartek'],
  ['friday', 'Piątek'], ['saturday', 'Sobota'], ['sunday', 'Niedziela'], ['tomorrow', 'Jutro'],
  ['today', 'Dziś'], ['weekend', 'Weekend']
]);

export function dayLabel(key: string, lang: string): string {
  const v = lang === 'pl' ? DAY_PL.get(key) : DAY_EN.get(key);
  return v === undefined ? '' : v;
}

/** Inflected / alias form (diacritic-free, lower) → display name (nominative). */
const PEOPLE: Map<string, string> = new Map<string, string>([
  ['kasia', 'Kasia'], ['kasi', 'Kasia'], ['kasie', 'Kasia'], ['kasia\'s', 'Kasia'],
  ['ola', 'Ola'], ['ole', 'Ola'], ['oli', 'Ola'], ['ola\'s', 'Ola'],
  ['kuba', 'Kuba'], ['kube', 'Kuba'], ['kuby', 'Kuba'], ['kubie', 'Kuba'],
  ['ania', 'Ania'], ['ani', 'Ania'], ['anie', 'Ania'],
  ['tomek', 'Tomek'], ['tomkiem', 'Tomek'], ['tomka', 'Tomek'], ['tomkowi', 'Tomek'],
  ['zosia', 'Zosia'], ['zosi', 'Zosia'], ['zosie', 'Zosia'],
  ['halina', 'Halina'], ['halina\'s', 'Halina'], ['haliny', 'Halina'], ['halinie', 'Halina'],
  ['michal', 'Michał'], ['michalem', 'Michał'], ['michala', 'Michał'],
  ['daniel', 'Daniel'], ['danielem', 'Daniel'], ['daniela', 'Daniel'],
  ['marta', 'Marta'], ['marte', 'Marta'], ['marty', 'Marta'],
  ['piotr', 'Piotr'], ['piotrem', 'Piotr'], ['piotra', 'Piotr'],
  ['mum', 'Mum'], ['mom', 'Mum'], ['mummy', 'Mum'], ['mommy', 'Mum'], ['mama', 'Mum'], ['mame', 'Mum'],
  ['mamy', 'Mum'], ['mamie', 'Mum'], ['mamusi', 'Mum'], ['mamusia', 'Mum'],
  ['dad', 'Dad'], ['daddy', 'Dad'], ['tata', 'Dad'], ['tate', 'Dad'], ['taty', 'Dad'], ['tacie', 'Dad'],
  ['tatus', 'Dad'],
  ['grandma', 'Grandma'], ['granny', 'Grandma'], ['babcia', 'Grandma'], ['babci', 'Grandma'], ['babcie', 'Grandma'],
  ['grandpa', 'Grandpa'], ['dziadek', 'Grandpa'], ['dziadka', 'Grandpa'], ['dziadkiem', 'Grandpa'],
  ['doctor', 'Doctor'], ['lekarz', 'Doctor'], ['lekarza', 'Doctor'], ['lekarzem', 'Doctor'],
  ['daughter', '@caregiver'], ['corka', '@caregiver'], ['corki', '@caregiver'], ['corce', '@caregiver'],
  ['corke', '@caregiver'], ['son', '@son'], ['syn', '@son'], ['syna', '@son'], ['synem', '@son'],
  ['nurse', 'Nurse'], ['pielegniark', 'Nurse']
]);

const PL_PEOPLE: Map<string, string> = new Map<string, string>([
  ['Mum', 'Mama'], ['Dad', 'Tata'], ['Grandma', 'Babcia'], ['Grandpa', 'Dziadek'], ['Doctor', 'Lekarz'],
  ['Nurse', 'Pielęgniarka']
]);

export function personLabel(name: string, lang: string): string {
  if (lang === 'pl') {
    const v = PL_PEOPLE.get(name);
    if (v !== undefined) {
      return v;
    }
  }
  return name;
}

const NOT_NAMES: string[] = ['I', 'Me', 'My', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Tiles', 'SOS',
  'Remind', 'Call', 'Dinner', 'Lunch', 'Plan', 'Make', 'Add', 'Please', 'Can', 'Is', 'The', 'A', 'What', 'How',
  'Zadzwoń', 'Przypomnij', 'Dodaj', 'Zrób', 'Proszę', 'Czy', 'Jak', 'Co', 'Kolacja', 'Obiad', 'Lekcje', 'Zakupy',
  'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday', 'Kazimierz', 'Rynek', 'Kraków',
  'Krakow', 'Podgórze', 'Zabłocie', 'Old', 'Town', 'ZUS', 'PGE', 'Tauron', 'BLIK', 'Focus', 'Homework', 'Shopping',
  'Weather', 'Note', 'Explain', 'Help', 'Emergency', 'Screen', 'Timer'];

export function findPeople(text: string, caregiver: string): string[] {
  const out: string[] = [];
  const tokens = text.replace(/[,.!?;:()]/g, ' ').split(/\s+/);
  for (let i = 0; i < tokens.length; i++) {
    const tok = tokens[i];
    if (tok.length === 0) {
      continue;
    }
    const key = norm(tok).trim();
    let name = PEOPLE.get(key);
    if (name === '@caregiver') {
      name = caregiver.length > 0 ? caregiver : 'Kasia';
    } else if (name === '@son') {
      name = 'Tomek';
    }
    if (name === undefined) {
      // Unknown capitalised word right after "with"/"z"/"call"/"zadzwoń do"/"and"/"i" → treat as a name.
      const prev = i > 0 ? norm(tokens[i - 1]).trim() : '';
      const cap = tok.charAt(0) !== tok.charAt(0).toLowerCase() && /^[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{2,}$/.test(tok);
      if (cap && NOT_NAMES.indexOf(tok) < 0 && ['with', 'z', 'ze', 'call', 'do', 'and', 'i', 'oraz', 'ring',
        'phone', 'zadzwon', 'meet'].indexOf(prev) >= 0) {
        name = plNominative(tok);
      }
    }
    if (name !== undefined && out.indexOf(name) < 0) {
      out.push(name);
    }
  }
  return out.slice(0, 6);
}

/** Very small Polish instrumental → nominative helper for unknown names ("Olą" → "Ola"). */
function plNominative(w: string): string {
  if (w.endsWith('ą')) {
    return w.substring(0, w.length - 1) + 'a';
  }
  if (w.endsWith('em') && w.length > 4) {
    return w.substring(0, w.length - 2);
  }
  return w;
}

class PlaceWord {
  key: string;
  label: string;
  constructor(key: string, label: string) {
    this.key = key;
    this.label = label;
  }
}

const PLACES: PlaceWord[] = [
  new PlaceWord('kazimierz', 'Kazimierz'), new PlaceWord('rynek', 'Rynek'), new PlaceWord('old town', 'Old Town'),
  new PlaceWord('stare miasto', 'Stare Miasto'), new PlaceWord('podgorz', 'Podgórze'),
  new PlaceWord('zablocie', 'Zabłocie'), new PlaceWord('nowa huta', 'Nowa Huta'),
  new PlaceWord('kleparz', 'Kleparz'), new PlaceWord('bronowic', 'Bronowice'), new PlaceWord('ruczaj', 'Ruczaj'),
  new PlaceWord('centrum', 'Centrum'), new PlaceWord('city centre', 'City centre'),
  new PlaceWord('downtown', 'Downtown'), new PlaceWord('galeria', 'Galeria'), new PlaceWord('park', 'Park'),
  new PlaceWord('home', 'Home'), new PlaceWord('w domu', 'Dom'), new PlaceWord('u mnie', 'Dom'),
  new PlaceWord('school', 'School'), new PlaceWord('szkol', 'Szkoła'), new PlaceWord('office', 'Office'),
  new PlaceWord('biuro', 'Biuro'), new PlaceWord('pharmacy', 'Pharmacy'), new PlaceWord('aptek', 'Apteka'),
  new PlaceWord('clinic', 'Clinic'), new PlaceWord('przychodni', 'Przychodnia')
];

export function findPlace(text: string): string {
  const n = norm(text);
  for (const p of PLACES) {
    if (n.indexOf(p.key) >= 0) {
      return p.label;
    }
  }
  // "near X" / "in X" / "at X" with a capitalised X
  const m = /\b(near|in|at|koło|kolo|przy|na|w)\s+([A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźż]+(\s[A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźż]+)?)/.exec(text);
  if (m !== null && NOT_NAMES.indexOf(m[2]) < 0 && findDay(m[2]).length === 0) {
    return m[2];
  }
  return '';
}

class FoodWord {
  key: string;
  stems: string[];
  constructor(key: string, stems: string[]) {
    this.key = key;
    this.stems = stems;
  }
}

const FOODS: FoodWord[] = [
  new FoodWord('vegan', ['vegan', 'wegan']), new FoodWord('vegetarian', ['vegetarian', 'veggie', 'wege', 'wegetar']),
  new FoodWord('gluten-free', ['gluten', 'bezgluten']), new FoodWord('pizza', ['pizz']),
  new FoodWord('sushi', ['sushi']), new FoodWord('ramen', ['ramen']), new FoodWord('pierogi', ['pierog']),
  new FoodWord('burger', ['burger']), new FoodWord('kebab', ['kebab']), new FoodWord('coffee', ['coffee', 'kaw']),
  new FoodWord('cake', ['cake', 'ciast', 'deser']), new FoodWord('thai', ['thai', 'tajsk']),
  new FoodWord('indian', ['indian', 'curry', 'indyjsk']), new FoodWord('italian', ['italian', 'wlosk', 'pasta', 'makaron'])
];

export function findFood(text: string): string {
  const n = norm(text);
  for (const f of FOODS) {
    for (const s of f.stems) {
      if (n.indexOf(s) >= 0) {
        return f.key;
      }
    }
  }
  return '';
}

export function findBudget(text: string): string {
  const n = norm(text);
  const m = /(\d{1,5})\s*(zl|pln|zlotych|eur|euro|usd|\$)/.exec(n);
  if (m !== null) {
    const cur = m[2] === 'eur' || m[2] === 'euro' ? '€' : (m[2] === 'usd' || m[2] === '$' ? '$' : 'zł');
    return cur === 'zł' ? m[1] + ' zł' : cur + m[1];
  }
  const m2 = /\$\s?(\d{1,5})/.exec(text);
  if (m2 !== null) {
    return '$' + m2[1];
  }
  return '';
}

class MedWord {
  stem: string;
  label: string;
  constructor(stem: string, label: string) {
    this.stem = stem;
    this.label = label;
  }
}

const MEDS: MedWord[] = [
  new MedWord('aspirin', 'Aspirin'), new MedWord('aspiryn', 'Aspiryna'), new MedWord('polopiryn', 'Polopiryna'),
  new MedWord('metformin', 'Metformin'), new MedWord('ibuprofen', 'Ibuprofen'), new MedWord('paracetamol', 'Paracetamol'),
  new MedWord(' apap', 'Apap'), new MedWord('insulin', 'Insulin'), new MedWord('euthyrox', 'Euthyrox'),
  new MedWord('bisoprolol', 'Bisoprolol'), new MedWord('amlodipin', 'Amlodipine'), new MedWord('atorvastatin', 'Atorvastatin'),
  new MedWord('vitamin d', 'Vitamin D'), new MedWord('witamin d', 'Witamina D'), new MedWord('vitamin c', 'Vitamin C'),
  new MedWord('witamin c', 'Witamina C'), new MedWord('magnes', 'Magnesium'), new MedWord('omega', 'Omega-3'),
  new MedWord('warfarin', 'Warfarin'), new MedWord('blood pressure', 'Blood pressure pill'),
  new MedWord('cisnien', 'Lek na ciśnienie'), new MedWord('heart pill', 'Heart pill'), new MedWord('na serce', 'Lek na serce')
];

export function findMedicine(text: string): string {
  const n = norm(text);
  for (const md of MEDS) {
    if (n.indexOf(md.stem) >= 0) {
      return md.label;
    }
  }
  return '';
}

class SubjectWord {
  key: string;
  stems: string[];
  constructor(key: string, stems: string[]) {
    this.key = key;
    this.stems = stems;
  }
}

const SUBJECTS: SubjectWord[] = [
  new SubjectWord('math', ['math', 'matma', 'matematy', 'tabliczk', 'times table', 'fraction', 'ulamk']),
  new SubjectWord('english', ['english', 'angielsk']), new SubjectWord('polish', ['polish', 'polsk']),
  new SubjectWord('reading', ['reading', 'czytan', 'lektur', 'book report']),
  new SubjectWord('spelling', ['spelling', 'dyktand', 'ortograf']),
  new SubjectWord('science', ['science', 'przyrod', 'biolog']), new SubjectWord('history', ['history', 'histori']),
  new SubjectWord('geography', ['geograph', 'geograf']), new SubjectWord('music', ['music', 'muzyk', 'piano', 'pianin']),
  new SubjectWord('art', [' art ', 'drawing', 'plastyk', 'rysow'])
];

const SUBJECT_EN: Map<string, string> = new Map<string, string>([
  ['math', 'Maths'], ['english', 'English'], ['polish', 'Polish'], ['reading', 'Reading'], ['spelling', 'Spelling'],
  ['science', 'Science'], ['history', 'History'], ['geography', 'Geography'], ['music', 'Music'], ['art', 'Art']
]);
const SUBJECT_PL: Map<string, string> = new Map<string, string>([
  ['math', 'Matematyka'], ['english', 'Angielski'], ['polish', 'Polski'], ['reading', 'Czytanie'],
  ['spelling', 'Dyktando'], ['science', 'Przyroda'], ['history', 'Historia'], ['geography', 'Geografia'],
  ['music', 'Muzyka'], ['art', 'Plastyka']
]);

export function findSubject(text: string): string {
  const n = norm(text);
  for (const s of SUBJECTS) {
    for (const st of s.stems) {
      if (n.indexOf(st) >= 0) {
        return s.key;
      }
    }
  }
  return '';
}

export function subjectLabel(key: string, lang: string): string {
  const v = lang === 'pl' ? SUBJECT_PL.get(key) : SUBJECT_EN.get(key);
  return v === undefined ? '' : v;
}

export function findMinutes(text: string): number {
  const n = norm(text);
  const m = /(\d{1,3})\s*(min|minutes|minut|minuty|mins|m\b)/.exec(n);
  if (m !== null) {
    return Math.max(1, Math.min(180, parseInt(m[1])));
  }
  const h = /(\d)\s*(h\b|hour|hours|godzin|godz\b)/.exec(n);
  if (h !== null) {
    return Math.min(180, parseInt(h[1]) * 60);
  }
  if (/\b(an hour|one hour|godzine|godzina)\b/.test(n)) {
    return 60;
  }
  if (/\b(half an hour|pol godziny)\b/.test(n)) {
    return 30;
  }
  return 0;
}

const LIST_STOP: string[] = ['and', 'i', 'oraz', 'also', 'tez', 'please', 'prosze', 'some', 'troche', 'a', 'the', ''];

/** Items after ':' or after buy/kup/need/pack, split on commas and and/i/oraz. */
export function findItems(text: string): string[] {
  let seg = '';
  const colon = text.indexOf(':');
  if (colon >= 0 && colon < text.length - 2) {
    seg = text.substring(colon + 1);
  } else {
    const m = /\b(buy|get|need|pack|kupić|kupic|kup|potrzebuję|potrzebuje|spakować|spakowac|zabrać|zabrac|tasks?|zadania)\b\s+(.*)$/i.exec(text);
    if (m !== null) {
      seg = m[2];
    }
  }
  if (seg.length === 0) {
    return [];
  }
  seg = seg.replace(/\b(for|on|at|before|by|na|w|przed|do)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today|jutro|dziś|dzis|piątek|piatek|sobotę|sobote|niedzielę|niedziele)\b.*$/i, '');
  const parts = seg.split(/,|;|\band\b|\boraz\b|\s+i\s+|\+|\n/);
  const out: string[] = [];
  for (const p of parts) {
    let s = p.trim().replace(/[.!?]+$/, '');
    if (LIST_STOP.indexOf(s.toLowerCase()) >= 0 || s.length > 40) {
      continue;
    }
    s = s.charAt(0).toUpperCase() + s.substring(1);
    if (out.indexOf(s) < 0) {
      out.push(s);
    }
  }
  return out.slice(0, 8);
}

const SENDERS: string[] = ['ZUS', 'PGE', 'Tauron', 'Enea', 'Energa', 'PGNiG', 'Orange', 'Play', 'Plus', 'T-Mobile',
  'UPC', 'Vectra', 'NFZ', 'PIT', 'Urząd Skarbowy', 'urząd', 'bank', 'Bank', 'Wodociągi', 'MPWiK', 'spółdzielnia'];

export function extractSlots(text: string, caregiver: string): Slots {
  const s = new Slots();
  s.raw = text.trim();
  // Language of the request itself: ignore quoted messages ("Is this a scam? \"Babciu, to ja…\"").
  const unquoted = text.replace(/["„“”][^"„“”]*["„“”]?/g, ' ').trim();
  s.lang = detectLang(unquoted.length >= 4 ? unquoted : text);
  s.times = findTimes(text);
  s.day = findDay(text);
  s.people = findPeople(text, caregiver);
  s.place = findPlace(text);
  s.food = findFood(text);
  s.budget = findBudget(text);
  s.medicine = findMedicine(text);
  s.subject = findSubject(text);
  s.items = findItems(text);
  s.minutes = findMinutes(text);
  const n = norm(text);
  s.twiceDaily = /(twice|dwa razy|2x|2 razy)/.test(n);
  const amt = /(\d{1,6}(?:[.,]\d{2})?)\s*(zł|zl|pln)/i.exec(text);
  if (amt !== null) {
    s.amount = amt[1] + ' zł';
  }
  const dt = /\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b/.exec(text);
  if (dt !== null && parseInt(dt[2]) <= 12 && (dt[3] !== undefined || text.indexOf(dt[0] + ' ') >= 0 ||
    text.endsWith(dt[0]))) {
    const d = parseInt(dt[1]);
    const mo = parseInt(dt[2]);
    if (d >= 1 && d <= 31 && mo >= 1 && mo <= 12 && (dt[3] !== undefined || dt[0].indexOf(':') < 0)) {
      s.date = pad2(d) + '.' + pad2(mo);
      // a date-looking "15.10" must not also be read as a time 15:10
      const asTime = pad2(d) + ':' + pad2(mo);
      const k = s.times.indexOf(asTime);
      if (k >= 0 && dt[0].indexOf(':') < 0) {
        s.times.splice(k, 1);
      }
    }
  }
  for (const snd of SENDERS) {
    if (text.indexOf(snd) >= 0) {
      s.sender = snd;
      break;
    }
  }
  return s;
}
