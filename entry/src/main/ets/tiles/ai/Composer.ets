/**
 * Composer — the Tiles generative-UI engine ("generator").
 *
 * compose(prompt, profile) turns a request typed (or spoken) into the assistant bar into 1–3 TileSpecs that the app
 * renders natively, plus a friendly reply and follow-up chips. This implementation is an ON-DEVICE, DETERMINISTIC,
 * RULE-BASED planner: keyword intent detection + slot extraction for English and Polish (Intents.ets) feeding rich
 * tile templates that differ per profile (senior / kid / low vision / everyday). No network, no LLM.
 *
 * It is pluggable: any generator that emits the same ComposeResult / TileSpec JSON (model/Tile.ets) can replace it,
 * e.g. an LLM behind the Aegis gateway in a future live mode. Nothing in this file claims or calls a model.
 *
 * Demo-data honesty: forecasts, venue options, transit times and screen-time numbers are sample data and the tiles
 * say so ("demo forecast", "demo options"). Scam checks use the on-device Guardian rule engine.
 */
import { ComposeResult, Profile, TileAction, TileBlock, TileSpec } from '../model/Tile';
import {
  act, alertBlock, bigBlock, buttonsBlock, checklistBlock, chipsBlock, listBlock, progressBlock, textBlock, tile,
  timerBlock, weatherBlock
} from '../data/SeedTiles';
import { Guardian, GuardianVerdict } from './Guardian';
import {
  dayLabel, detectIntents, extractSlots, norm, personLabel, Slots, subjectLabel
} from './Intents';

/** Pick the EN or PL string. */
function L(s: Slots, en: string, pl: string): string {
  return s.lang === 'pl' ? pl : en;
}

/** '08:00' → '8:00'. */
function hm(t: string): string {
  return t.startsWith('0') ? t.substring(1) : t;
}

function cap(s: string): string {
  return s.length === 0 ? s : s.charAt(0).toUpperCase() + s.substring(1);
}

function short(s: string, max: number): string {
  const t = s.trim();
  return t.length <= max ? t : t.substring(0, max - 1).trim() + '…';
}

function joinNames(names: string[], lang: string): string {
  if (names.length === 0) {
    return '';
  }
  if (names.length === 1) {
    return names[0];
  }
  const and = lang === 'pl' ? ' i ' : ' and ';
  return names.slice(0, names.length - 1).join(', ') + and + names[names.length - 1];
}

function isBig(p: Profile): boolean {
  return p.id === 'senior' || p.id === 'lowvision' || p.columns <= 2;
}

/** Senior / low-vision grids are 2 columns: never emit 1x1 there. */
function sz(p: Profile, want: string): string {
  if (want === '1x1' && isBig(p)) {
    return '2x1';
  }
  return want;
}

function caregiverOf(p: Profile): string {
  if (p.caregiver.length > 0) {
    return p.caregiver;
  }
  return p.id === 'kid' ? 'Mum' : '';
}

class Venue {
  name: string;
  price: number;
  constructor(name: string, price: number) {
    this.name = name;
    this.price = price;
  }
}

/** Demo venue options (labelled "demo options" on the tile). */
function venuesFor(food: string): Venue[] {
  switch (food) {
    case 'vegan':
    case 'vegetarian':
      return [new Venue('Veganda', 62), new Venue('Krowarzywa', 45), new Venue('Glonojad', 55)];
    case 'pizza':
    case 'italian':
      return [new Venue('Nolio', 70), new Venue('Pizzeria Cyklop', 48), new Venue('Pizza Garden', 40)];
    case 'sushi':
      return [new Venue('Sushi Kushi', 85), new Venue('Edo Sushi', 95), new Venue('Youmiko', 75)];
    case 'ramen':
    case 'thai':
    case 'indian':
      return [new Venue('Tao Ramen', 55), new Venue('Thai Corner', 50), new Venue('Masala House', 60)];
    case 'pierogi':
      return [new Venue('Przystanek Pierogarnia', 35), new Venue('Pierogi Mr Vincent', 40),
        new Venue('Zapiecek', 38)];
    case 'burger':
    case 'kebab':
      return [new Venue('Moaburger', 50), new Venue('Bunkier Burger', 45), new Venue('Kebab Kazimierz', 30)];
    case 'coffee':
    case 'cake':
      return [new Venue('Café Camelot', 35), new Venue('Massolit Café', 30), new Venue('Charlotte', 40)];
    default:
      return [new Venue('Bistro Kazimierz', 65), new Venue('Zielony Talerz', 55), new Venue('Mleczarnia', 40)];
  }
}

/** Builds TileSpecs with unique ids and assistant provenance. */
class Factory {
  private n: number = 0;
  private stamp: number = Date.now();

  make(type: string, title: string, subtitle: string, icon: string, color: string, size: string,
    blocks: TileBlock[], speak: string): TileSpec {
    this.n++;
    const t: TileSpec = tile('as-' + type + '-' + this.stamp.toString(36) + '-' + this.n.toString(), type, title,
      subtitle, icon, color, size, blocks, speak);
    t.source = 'assistant';
    t.createdAt = this.stamp;
    return t;
  }
}

/** Result under construction. */
class Draft {
  tiles: TileSpec[] = [];
  replies: string[] = [];
  followUps: string[] = [];

  addFollow(f: string): void {
    if (f.length > 0 && this.followUps.indexOf(f) < 0 && this.followUps.length < 4) {
      this.followUps.push(f);
    }
  }
}

export class Composer {
  /** Engine label for UI/docs (honest: rule-based, on-device). */
  static readonly ENGINE: string = 'On-device rule-based generator (EN + PL)';

  /**
   * Plan tiles for a request. Deterministic for a given (prompt, profile) apart from ids/timestamps.
   */
  static compose(prompt: string, profile: Profile): ComposeResult {
    const r: ComposeResult = new ComposeResult();
    const text = prompt.trim();
    const s: Slots = extractSlots(text, caregiverOf(profile));
    if (text.length === 0) {
      r.reply = L(s, 'Tell me what you need — a reminder, a call, a plan — and I will make a tile for it.',
        'Powiedz, czego potrzebujesz — przypomnienie, telefon, plan — a zrobię z tego kafelek.');
      r.followUps = Composer.quickChips(profile);
      return r;
    }
    const f = new Factory();
    const d = new Draft();
    const intents: string[] = detectIntents(text);
    if (intents.length === 0) {
      Composer.fallback(s, profile, f, d);
    } else {
      for (const it of intents) {
        if (d.tiles.length >= 3) {
          break;
        }
        Composer.build(it, s, profile, f, d);
      }
      if (d.tiles.length === 0) {
        Composer.fallback(s, profile, f, d);
      }
    }
    r.tiles = d.tiles.slice(0, 3);
    r.needsApproval = Composer.needsApproval(profile) && r.tiles.length > 0;
    let reply = d.replies.join(' ');
    if (r.needsApproval) {
      const who = caregiverOf(profile);
      const whoLabel = personLabel(who, s.lang);
      reply += ' ' + L(s, whoLabel + ' will get it to approve first.',
        whoLabel + ' najpierw to zatwierdzi.');
    }
    r.reply = reply.trim();
    r.followUps = d.followUps;
    return r;
  }

  /** Senior and kid profiles: new tiles wait for the caregiver / parent. */
  static needsApproval(profile: Profile): boolean {
    return profile.id === 'senior' || profile.id === 'kid';
  }

  /** Quick-start chips shown in the assistant sheet, per profile (ICP). */
  static quickChips(profile: Profile): string[] {
    switch (profile.id) {
      case 'senior':
        return ['Remind me to take Aspirin at 8:00 and 20:00', 'Call Kasia on Sunday at 12', 'What should I wear today?',
          'Is this a scam? "Babciu, to ja, potrzebuję pieniędzy, nie mów nikomu"', 'Explain this bill: PGE 142,30 zł due 15.10'];
      case 'kid':
        return ['Homework: maths p. 42, read 10 pages, spelling', 'Focus timer 20 min for reading', 'Call Mum',
          'Something fun to do after school', 'How much screen time do I have left?'];
      case 'lowvision':
        return ['Call Tomek', 'Eye drops at 9:00', 'What is the weather?', 'Next bus to Rondo Mogilskie',
          'Note: buy batteries for the radio'];
      default:
        return ['Dinner Friday with Ola and Kuba, vegan, near Kazimierz, under 80 zł', 'Focus timer 25 min',
          'Shopping: oat milk, tofu, apples', 'Kolacja w piątek o 19:30 z Olą, pizza', 'Remind me to call Mum on Sunday at 18'];
    }
  }

  // ------------------------------------------------------------------------------------------------------------

  private static build(intent: string, s: Slots, p: Profile, f: Factory, d: Draft): void {
    switch (intent) {
      case 'pills':
        Composer.pills(s, p, f, d);
        break;
      case 'call':
        Composer.call(s, p, f, d);
        break;
      case 'weather':
        Composer.weather(s, p, f, d);
        break;
      case 'plan':
        Composer.plan(s, p, f, d);
        break;
      case 'timer':
        Composer.timer(s, p, f, d);
        break;
      case 'homework':
        Composer.homework(s, p, f, d);
        break;
      case 'checklist':
        Composer.checklist(s, p, f, d);
        break;
      case 'shopping':
        Composer.shopping(s, p, f, d);
        break;
      case 'reminder':
        Composer.reminder(s, p, f, d);
        break;
      case 'note':
        Composer.note(s, p, f, d);
        break;
      case 'sos':
        Composer.sos(s, p, f, d);
        break;
      case 'screentime':
        Composer.screentime(s, p, f, d);
        break;
      case 'letter':
        Composer.letter(s, p, f, d);
        break;
      case 'scam':
        Composer.scam(s, p, f, d);
        break;
      case 'commute':
        Composer.commute(s, p, f, d);
        break;
      case 'adventure':
        Composer.adventure(s, p, f, d);
        break;
      default:
        break;
    }
  }

  private static pills(s: Slots, p: Profile, f: Factory, d: Draft): void {
    const med = s.medicine.length > 0 ? s.medicine : L(s, 'Pills', 'Leki');
    const times: string[] = s.times.length > 0 ? s.times : ['08:00'];
    const who = caregiverOf(p);
    for (let i = 0; i < times.length && i < 2; i++) {
      const t = hm(times[i]);
      const hour = parseInt(times[i].substring(0, 2));
      const when = hour < 12 ? L(s, 'Morning dose', 'Dawka poranna') :
        (hour < 18 ? L(s, 'Afternoon dose', 'Dawka popołudniowa') : L(s, 'Evening dose', 'Dawka wieczorna'));
      const title = (s.medicine.length > 0 ? s.medicine : L(s, 'Pills', 'Leki')) + ' ' + t;
      const sub = s.day.length > 0 ? dayLabel(s.day, s.lang) : L(s, 'Every day', 'Codziennie');
      const actions: TileAction[] = [act(L(s, 'Taken', 'Wzięte'), 'done', 'pills-' + times[i]),
        act(L(s, 'Remind in 15 min', 'Przypomnij za 15 min'), 'remind', '15')];
      const blocks: TileBlock[] = [bigBlock(t, when), checklistBlock('', [med], [false]), buttonsBlock(actions)];
      if (who.length > 0 && (p.id === 'senior' || p.id === 'lowvision')) {
        blocks.splice(2, 0, textBlock(L(s, 'If you miss it, ' + who + ' gets a gentle note.',
          'Jeśli zapomnisz, ' + personLabel(who, s.lang) + ' dostanie delikatną wiadomość.')));
      }
      d.tiles.push(f.make('pills', title, sub, 'cross_case_fill', i === 0 ? 'mint' : 'grape', '2x1', blocks,
        L(s, 'Time for ' + med + ' at ' + t + '. Tap Taken when you have taken it.',
          'Pora na ' + med + ' o ' + t + '. Dotknij Wzięte, gdy weźmiesz.')));
    }
    const list = times.map((x: string) => hm(x)).join(L(s, ' and ', ' i '));
    d.replies.push(L(s, 'Done — a pill tile for ' + med + ' at ' + list + ', with a reminder.',
      'Gotowe — kafelek z lekiem ' + med + ' na ' + list + ', z przypomnieniem.'));
    if (times.length === 1) {
      d.addFollow(L(s, 'Also remind me at 20:00', 'Przypomnij też o 20:00'));
    }
    if (p.id === 'senior') {
      d.addFollow(L(s, 'Call Kasia if I miss my pills', 'Zadzwoń do Kasi, jeśli zapomnę leków'));
    }
    d.addFollow(L(s, 'Note: pharmacy refill on Friday', 'Notatka: wykupić receptę w piątek'));
  }

  private static call(s: Slots, p: Profile, f: Factory, d: Draft): void {
    const people: string[] = s.people.length > 0 ? s.people : [caregiverOf(p).length > 0 ? caregiverOf(p) : 'Mum'];
    const who = people[0];
    const label = personLabel(who, s.lang);
    const when: string[] = [];
    if (s.day.length > 0) {
      when.push(dayLabel(s.day, s.lang));
    }
    if (s.times.length > 0) {
      when.push(hm(s.times[0]));
    }
    const sub = when.length > 0 ? L(s, 'Reminder: ', 'Przypomnienie: ') + when.join(' ') :
      (who === caregiverOf(p) && p.caregiverRole.length > 0 ? L(s, 'Your ' + p.caregiverRole, 'Twoja rodzina') :
        L(s, 'One tap to call', 'Jedno dotknięcie, by zadzwonić'));
    const actions: TileAction[] = [act(L(s, 'Call', 'Zadzwoń'), 'call', who)];
    if (when.length > 0) {
      const weekday = s.day.length > 0 && s.day !== 'today' && s.day !== 'tomorrow' && s.day !== 'weekend';
      actions.push(act(L(s, 'Remind me', 'Przypomnij'), 'remind', (weekday ? s.day.substring(0, 3) + '-' : '') +
        (s.times.length > 0 ? s.times[0] : '18:00')));
    }
    const blocks: TileBlock[] = [];
    if (when.length > 0) {
      blocks.push(bigBlock(s.times.length > 0 ? hm(s.times[0]) : dayLabel(s.day, s.lang),
        s.day.length > 0 && s.times.length > 0 ? dayLabel(s.day, s.lang) : L(s, 'Call time', 'Pora telefonu')));
    }
    blocks.push(buttonsBlock(actions));
    const title = L(s, 'Call ' + label, 'Zadzwoń: ' + label);
    d.tiles.push(f.make('call', title, sub, 'phone_fill', p.id === 'kid' ? 'coral' : 'sky',
      sz(p, when.length > 0 ? '2x1' : '1x1'), blocks, L(s, 'Call ' + label + '. ' + sub, 'Zadzwoń: ' + label + '. ' + sub)));
    d.replies.push(when.length > 0 ?
      L(s, 'Here is a call tile for ' + label + ' with a reminder ' + when.join(' ') + '.',
        'Oto kafelek do rozmowy z: ' + label + ', z przypomnieniem ' + when.join(' ') + '.') :
      L(s, 'One tap and you are calling ' + label + '.', 'Jedno dotknięcie i dzwonisz: ' + label + '.'));
    if (when.length === 0) {
      d.addFollow(L(s, 'Remind me to call ' + label + ' on Sunday at 18', 'Przypomnij o telefonie w niedzielę o 18'));
    }
    if (people.length > 1) {
      d.addFollow(L(s, 'Call ' + personLabel(people[1], s.lang), 'Zadzwoń: ' + personLabel(people[1], s.lang)));
    }
  }

  private static weather(s: Slots, p: Profile, f: Factory, d: Draft): void {
    const city = s.place.length > 0 ? s.place : 'Kraków';
    const day = s.day.length > 0 ? dayLabel(s.day, s.lang) : L(s, 'Today', 'Dziś');
    const wear: string[] = p.id === 'kid' ?
      [L(s, 'Raincoat + wellies', 'Kurtka przeciwdeszczowa + kalosze'), L(s, 'Warm hat', 'Ciepła czapka')] :
      [L(s, 'Umbrella', 'Parasol'), L(s, 'Warm coat', 'Ciepły płaszcz'), L(s, 'Waterproof shoes', 'Nieprzemakalne buty')];
    const blocks: TileBlock[] = [
      weatherBlock('14°', L(s, 'Rain until 15:00, 11–14°', 'Deszcz do 15:00, 11–14°'), wear),
      textBlock(L(s, 'Dry from 18:00 — good time for a walk.', 'Od 18:00 sucho — dobra pora na spacer.'))
    ];
    const title = p.id === 'kid' ? L(s, 'Wellies day!', 'Dzień kaloszy!') : L(s, '14° and rain', '14° i deszcz');
    d.tiles.push(f.make('weather', title, city + ' · ' + day + ' · ' + L(s, 'demo forecast', 'prognoza demo'),
      'umbrella', 'peach', sz(p, '2x1'), blocks,
      L(s, day + ' in ' + city + ': 14 degrees and rain until 3 PM. Take ' + wear.join(', ').toLowerCase() + '.',
        day + ' w ' + city + ': 14 stopni i deszcz do 15. Weź: ' + wear.join(', ').toLowerCase() + '.')));
    d.replies.push(L(s, 'It looks rainy, so I added what to wear. (Demo forecast — no live weather source yet.)',
      'Będzie padać, więc dodałem, co założyć. (Prognoza demo — bez źródła na żywo.)'));
    d.addFollow(L(s, 'Remind me to take the umbrella at 8:00', 'Przypomnij o parasolu o 8:00'));
  }

  private static plan(s: Slots, p: Profile, f: Factory, d: Draft): void {
    const n = s.raw.length > 0 ? norm(s.raw) : '';
    let what = L(s, 'Dinner', 'Kolacja');
    let defTime = '19:30';
    if (n.indexOf('lunch') >= 0 || n.indexOf(' obiad') >= 0) {
      what = L(s, 'Lunch', 'Obiad');
      defTime = '13:00';
    } else if (n.indexOf('breakfast') >= 0 || n.indexOf('brunch') >= 0 || n.indexOf('sniadani') >= 0) {
      what = L(s, 'Brunch', 'Śniadanie');
      defTime = '10:30';
    } else if (n.indexOf('cinema') >= 0 || n.indexOf(' kino') >= 0 || n.indexOf('movie') >= 0) {
      what = L(s, 'Cinema', 'Kino');
      defTime = '20:00';
    } else if (n.indexOf('party') >= 0 || n.indexOf('impreza') >= 0) {
      what = L(s, 'Party', 'Impreza');
      defTime = '20:00';
    } else if (n.indexOf('drinks') >= 0 || n.indexOf('coffee') >= 0 || n.indexOf('kaw') >= 0) {
      what = L(s, 'Coffee', 'Kawa');
      defTime = '17:00';
    } else if (n.indexOf('dinner') < 0 && n.indexOf('kolacj') < 0 && s.food.length === 0) {
      what = L(s, 'Meet-up', 'Spotkanie');
      defTime = '18:00';
    }
    const time = s.times.length > 0 ? hm(s.times[0]) : hm(defTime);
    const dayKey = s.day.length > 0 ? s.day : 'friday';
    const dayShort = dayLabel(dayKey, s.lang).substring(0, s.lang === 'pl' ? 3 : 3);
    const friends: string[] = [];
    for (const x of s.people) {
      if (x !== p.name) {
        friends.push(personLabel(x, s.lang));
      }
    }
    const place = s.place.length > 0 ? s.place : 'Kazimierz';
    let budgetMax = 0;
    if (s.budget.length > 0) {
      budgetMax = parseInt(s.budget.replace(/[^0-9]/g, ''));
    }
    const all: Venue[] = venuesFor(s.food);
    let opts: Venue[] = all.filter((v: Venue) => budgetMax <= 0 || v.price <= budgetMax);
    if (opts.length < 2) {
      opts = all.slice().sort((a: Venue, b: Venue) => a.price - b.price).slice(0, 2);
    }
    const lines: string[] = opts.map((v: Venue) => v.name + ' · ~' + v.price.toString() + ' zł');
    const chips: string[] = [];
    if (s.food.length > 0) {
      chips.push(s.food);
    }
    chips.push(place);
    if (s.budget.length > 0) {
      chips.push(L(s, 'under ', 'do ') + s.budget);
    }
    if (friends.length > 0) {
      chips.push((friends.length + 1).toString() + L(s, ' people', ' osoby'));
    }
    const votes: TileAction[] = [];
    for (let i = 0; i < opts.length && i < 2; i++) {
      votes.push(act(L(s, 'Vote ', 'Głosuj: ') + opts[i].name, 'vote', opts[i].name));
    }
    const sub = place + (friends.length > 0 ? ' · ' + joinNames(friends, s.lang) + L(s, ' + you', ' + Ty') : '');
    const title = what + ' ' + dayShort + ' ' + time;
    d.tiles.push(f.make('plan', title, sub, 'fork_knife', 'grape', isBig(p) ? '2x2' : '2x2', [
      chipsBlock(chips),
      listBlock(L(s, 'Options (demo)', 'Propozycje (demo)'), lines),
      buttonsBlock(votes)
    ], L(s, what + ' on ' + dayLabel(dayKey, 'en') + ' at ' + time + ' in ' + place +
      (friends.length > 0 ? ' with ' + joinNames(friends, 'en') : '') + '. Options: ' +
      opts.map((v: Venue) => v.name).join(', ') + '.',
      what + ' ' + dayLabel(dayKey, 'pl') + ' o ' + time + ', ' + place +
        (friends.length > 0 ? ', z: ' + joinNames(friends, 'pl') : '') + '. Propozycje: ' +
        opts.map((v: Venue) => v.name).join(', ') + '.')));
    d.replies.push(L(s, 'I drafted the plan with ' + opts.length.toString() + ' options' +
      (friends.length > 0 ? ' — ' + joinNames(friends, 'en') + ' can vote' : '') + '. (Venues are demo options.)',
      'Przygotowałem plan z ' + opts.length.toString() + ' propozycjami' +
        (friends.length > 0 ? ' — ' + joinNames(friends, 'pl') + (friends.length === 1 ? ' może' : ' mogą') + ' głosować' : '') + '. (Lokale to dane demo.)'));
    d.addFollow(L(s, 'Remind me Thursday at 18:00 to book a table', 'Przypomnij w czwartek o 18:00 o rezerwacji'));
    d.addFollow(s.food === 'vegan' ? L(s, 'Make it pizza instead', 'Zmień na pizzę') :
      L(s, 'Make it vegan instead', 'Zmień na wegańską'));
  }

  private static timer(s: Slots, p: Profile, f: Factory, d: Draft): void {
    const mins = s.minutes > 0 ? s.minutes : (p.id === 'kid' ? 15 : 25);
    const mm = mins.toString() + ':00';
    const subj = s.subject.length > 0 ? subjectLabel(s.subject, s.lang) : '';
    const label = p.id === 'kid' ? L(s, 'Focus timer', 'Minutnik skupienia') : L(s, 'Focus', 'Skupienie');
    const sub = subj.length > 0 ? subj : (p.id === 'kid' ? L(s, 'Then a 5 min break', 'Potem 5 min przerwy') :
      L(s, 'Phone on silent while it runs', 'Telefon wyciszony w trakcie'));
    d.tiles.push(f.make('timer', label + ' ' + mm, sub, 'timer', p.id === 'kid' ? 'grape' : 'sky', sz(p, '2x1'), [
      timerBlock(p.id === 'kid' ? L(s, 'You can do it!', 'Dasz radę!') : L(s, 'Deep work', 'Głęboka praca'),
        mins.toString()),
      buttonsBlock([act(L(s, 'Start', 'Start'), 'open', 'timer:' + mins.toString())])
    ], L(s, 'Focus timer, ' + mins.toString() + ' minutes.', 'Minutnik, ' + mins.toString() + ' minut.')));
    d.replies.push(L(s, 'A ' + mins.toString() + '-minute focus timer is ready.',
      'Minutnik na ' + mins.toString() + ' minut gotowy.'));
    d.addFollow(L(s, 'Focus timer 45 min', 'Minutnik 45 min'));
  }

  private static homework(s: Slots, p: Profile, f: Factory, d: Draft): void {
    let items: string[] = s.items.slice(0, 6);
    if (items.length === 0) {
      const subj = s.subject.length > 0 ? subjectLabel(s.subject, s.lang) : '';
      items = subj.length > 0 ? [subj + L(s, ' exercises', ' — zadania'), L(s, 'Check answers', 'Sprawdź odpowiedzi'),
        L(s, 'Pack school bag', 'Spakuj plecak')] :
        [L(s, 'Maths p. 42', 'Matematyka str. 42'), L(s, 'Read 10 pages', 'Przeczytaj 10 stron'),
          L(s, 'Pack school bag', 'Spakuj plecak')];
    }
    const day = s.day.length > 0 ? dayLabel(s.day, s.lang) : L(s, 'Today', 'Dziś');
    d.tiles.push(f.make('homework', L(s, 'Homework', 'Lekcje'), day + ' · 0 ' + L(s, 'of ', 'z ') +
      items.length.toString() + L(s, ' done', ' zrobione'), 'book_pages_fill', 'sun', sz(p, '2x2'), [
      progressBlock(p.id === 'kid' ? L(s, 'Let\'s go!', 'Do dzieła!') : '', '0 ' + L(s, 'of ', 'z ') +
        items.length.toString(), 0),
      checklistBlock('', items, [])
    ], L(s, 'Homework: ', 'Lekcje: ') + items.join(', ') + '.'));
    d.replies.push(L(s, 'Homework list with ' + items.length.toString() + ' steps — tick them off as you go.',
      'Lista lekcji: ' + items.length.toString() + ' kroki — odhaczaj po kolei.'));
    if (d.tiles.length < 3 && p.id === 'kid') {
      d.addFollow(L(s, 'Focus timer 15 min', 'Minutnik 15 min'));
    }
    d.addFollow(L(s, 'Remind me at 16:00 to start homework', 'Przypomnij o 16:00 o lekcjach'));
  }

  private static checklist(s: Slots, p: Profile, f: Factory, d: Draft): void {
    const n = norm(s.raw);
    const packing = n.indexOf('pack') >= 0 || n.indexOf('spakow') >= 0;
    let items: string[] = s.items;
    if (items.length === 0) {
      items = packing ? [L(s, 'Phone charger', 'Ładowarka'), L(s, 'ID card', 'Dowód'), L(s, 'Keys', 'Klucze')] :
        [L(s, 'First thing', 'Pierwsza rzecz'), L(s, 'Second thing', 'Druga rzecz')];
    }
    const title = packing ? L(s, 'Packing list', 'Do spakowania') : L(s, 'To-do', 'Do zrobienia');
    const sub = s.day.length > 0 ? dayLabel(s.day, s.lang) : items.length.toString() + L(s, ' items', ' pozycji');
    d.tiles.push(f.make('note', title, sub, 'list', 'leaf', sz(p, '2x1'), [checklistBlock('', items, [])],
      title + ': ' + items.join(', ') + '.'));
    d.replies.push(L(s, 'Checklist ready — tap items to tick them off.', 'Lista gotowa — dotknij, by odhaczyć.'));
    d.addFollow(L(s, 'Remind me at 18:00 to check the list', 'Przypomnij o 18:00 o liście'));
  }

  private static shopping(s: Slots, p: Profile, f: Factory, d: Draft): void {
    let items: string[] = s.items;
    const starter = items.length === 0;
    if (starter) {
      items = [L(s, 'Milk', 'Mleko'), L(s, 'Bread', 'Chleb'), L(s, 'Eggs', 'Jajka')];
    }
    const sub = (s.place.length > 0 ? s.place : L(s, 'On the way home', 'W drodze do domu')) +
      (s.day.length > 0 ? ' · ' + dayLabel(s.day, s.lang) : '');
    const blocks: TileBlock[] = [checklistBlock(starter ? L(s, 'Starter list — edit me', 'Lista startowa — zmień') : '',
      items, [])];
    if (s.budget.length > 0) {
      blocks.push(textBlock(L(s, 'Budget: ', 'Budżet: ') + s.budget));
    }
    d.tiles.push(f.make('note', L(s, 'Shopping', 'Zakupy'), sub, 'cart_fill', 'leaf', sz(p, '2x1'), blocks,
      L(s, 'Shopping list: ', 'Lista zakupów: ') + items.join(', ') + '.'));
    d.replies.push(starter ? L(s, 'Started a shopping list — tell me what to add.', 'Zacząłem listę zakupów — powiedz, co dodać.') :
      L(s, 'Shopping list with ' + items.length.toString() + ' items.', 'Lista zakupów: ' + items.length.toString() + ' pozycji.'));
    d.addFollow(L(s, 'Shopping: bananas, coffee', 'Zakupy: banany, kawa'));
  }

  /** Strip trigger words so "remind me to call the plumber at 18" → "Call the plumber". */
  private static what(raw: string): string {
    let w = raw.replace(/^(please\s+|proszę\s+|prosze\s+)/i, '');
    w = w.replace(/^(remind me( to)?|reminder( to)?|don'?t forget( to)?|przypomnij( mi)?( żeby| zeby| o| że| ze)?|nie zapomnij( o)?|note:?|notatka:?|zapisz:?|zanotuj:?|remember that|pamiętaj( o| że)?)\s*/i, '');
    w = w.replace(/\b(at|o|on|w|we|in|na)\s+\d{1,2}([:.]\d{2})?\s*(am|pm)?\b/ig, '');
    w = w.replace(/\b(today|tomorrow|tonight|on (monday|tuesday|wednesday|thursday|friday|saturday|sunday)|monday|tuesday|wednesday|thursday|friday|saturday|sunday|jutro|dziś|dzis|dzisiaj|w (poniedziałek|wtorek|środę|czwartek|piątek|sobotę|niedzielę)|we (wtorek|środę|czwartek))\b/ig, '');
    w = w.replace(/\s+/g, ' ').replace(/^[\s:,-]+|[\s:,.-]+$/g, '');
    w = w.replace(/^(to|że|ze|żeby|zeby|o)\s+/i, '');
    return cap(w);
  }

  private static reminder(s0: Slots, p: Profile, f: Factory, d: Draft): void {
    let s: Slots = s0;
    if (d.tiles.length > 0) {
      // Secondary reminder in a combined request ("Dinner Friday … and remind me Thursday to book"):
      // read its own day / time from the clause after "remind".
      const m = /(remind|przypomnij)/i.exec(s0.raw);
      if (m !== null) {
        s = extractSlots(s0.raw.substring(m.index), '');
        s.lang = s0.lang;
      }
    }
    let what = Composer.what(s.raw);
    if (what.length === 0) {
      what = L(s, 'Reminder', 'Przypomnienie');
    }
    const time = s.times.length > 0 ? s.times[0] : '18:00';
    const day = s.day.length > 0 ? dayLabel(s.day, s.lang) : L(s, 'Today', 'Dziś');
    const title = short(what, 22) + ' ' + hm(time);
    d.tiles.push(f.make('reminder', title, day + ' · ' + hm(time), 'bell_fill', 'sun', sz(p, '2x1'), [
      bigBlock(hm(time), day),
      textBlock(short(what, 80)),
      buttonsBlock([act(L(s, 'Done', 'Zrobione'), 'done', 'reminder'),
        act(L(s, 'Snooze 1 h', 'Później (1 h)'), 'remind', '60')])
    ], L(s, 'Reminder ', 'Przypomnienie ') + day + ' ' + hm(time) + ': ' + what + '.'));
    d.replies.push(L(s, 'I will remind you ' + (s.day.length > 0 && s.day !== 'today' && s.day !== 'tomorrow' ? 'on ' + day :
      day.toLowerCase()) + ' at ' + hm(time) + '.',
      'Przypomnę ' + day.toLowerCase() + ' o ' + hm(time) + '.'));
    if (s.times.length === 0) {
      d.addFollow(L(s, 'Make it 9:00 instead', 'Zmień na 9:00'));
    }
  }

  private static note(s: Slots, p: Profile, f: Factory, d: Draft): void {
    let body = Composer.what(s.raw);
    if (body.length === 0) {
      body = s.raw;
    }
    const words = body.split(' ');
    const title = short(words.slice(0, 4).join(' '), 24);
    if (s.items.length >= 2) {
      d.tiles.push(f.make('note', title, L(s, 'Note', 'Notatka'), 'note', 'ink', sz(p, '2x1'),
        [checklistBlock('', s.items, [])], body));
    } else {
      d.tiles.push(f.make('note', title, L(s, 'Note', 'Notatka'), 'note', 'ink', sz(p, '2x1'),
        [textBlock(short(body, 140))], body));
    }
    d.replies.push(L(s, 'Saved as a note tile.', 'Zapisane jako notatka.'));
    d.addFollow(L(s, 'Remind me: ', 'Przypomnij: ') + short(body, 30) + L(s, ' at 18:00', ' o 18:00'));
  }

  private static sos(s: Slots, p: Profile, f: Factory, d: Draft): void {
    const who = caregiverOf(p).length > 0 ? caregiverOf(p) : '112';
    const label = personLabel(who, s.lang);
    d.tiles.push(f.make('sos', 'SOS', L(s, 'Hold to call ' + label, 'Przytrzymaj, by zadzwonić: ' + label),
      'phone_sos', 'coral', sz(p, isBig(p) ? '2x1' : '1x1'), [
      alertBlock(L(s, 'Hold for 2 seconds: calls ' + label + ' and shares where you are.',
        'Przytrzymaj 2 sekundy: dzwoni (' + label + ') i wysyła, gdzie jesteś.'), 'info', []),
      buttonsBlock([act(L(s, 'Hold for help', 'Przytrzymaj po pomoc'), 'sos', who),
        act(L(s, 'Call 112', 'Zadzwoń 112'), 'call', '112')])
    ], L(s, 'S O S. Hold to call ' + label + '.', 'S O S. Przytrzymaj, by zadzwonić: ' + label + '.')));
    d.replies.push(L(s, 'Your SOS tile is ready. If this is an emergency right now, call 112.',
      'Kafelek SOS gotowy. Jeśli to nagły wypadek teraz — dzwoń 112.'));
  }

  private static screentime(s: Slots, p: Profile, f: Factory, d: Draft): void {
    if (p.id === 'kid') {
      d.tiles.push(f.make('screentime', L(s, 'Screen time', 'Czas ekranowy'), L(s, '45 of 60 min left', 'Zostało 45 z 60 min'),
        'hourglass', 'mint', '2x1', [
        progressBlock(L(s, 'Plenty left for today', 'Dziś jeszcze sporo'), '45 min', 0.75),
        chipsBlock([L(s, 'Demo data', 'Dane demo')])
      ], L(s, 'You have 45 of 60 minutes of screen time left today.', 'Zostało Ci 45 z 60 minut na dziś.')));
      d.replies.push(L(s, 'You still have 45 minutes today — nice!', 'Masz jeszcze 45 minut — super!'));
      d.addFollow(L(s, 'Something fun to do after school', 'Coś fajnego po szkole'));
    } else {
      d.tiles.push(f.make('screentime', L(s, 'Screen time', 'Czas ekranowy'), L(s, '2 h 10 min today · goal 3 h',
        'Dziś 2 h 10 min · cel 3 h'), 'hourglass', 'grape', sz(p, '2x1'), [
        progressBlock(L(s, 'Under your goal', 'Poniżej celu'), '2 h 10 min', 0.72),
        chipsBlock([L(s, 'Demo data', 'Dane demo')])
      ], L(s, 'Screen time today: 2 hours 10 minutes of a 3 hour goal.', 'Czas ekranowy dziś: 2 godziny 10 minut.')));
      d.replies.push(L(s, 'Here is today\'s screen time (demo numbers).', 'Oto czas ekranowy (dane demo).'));
    }
  }

  private static letter(s: Slots, p: Profile, f: Factory, d: Draft): void {
    const hasContent = s.amount.length > 0 || s.date.length > 0 || s.sender.length > 0;
    const sender = s.sender.length > 0 ? s.sender : (hasContent ? L(s, 'Sender', 'Nadawca') : 'PGE');
    const amount = s.amount.length > 0 ? s.amount : (hasContent ? '' : '142,30 zł');
    const due = s.date.length > 0 ? s.date : (hasContent ? '' : '15.10');
    const n = norm(s.raw);
    let kind = L(s, 'Bill to pay', 'Rachunek do zapłaty');
    if (n.indexOf('zus') >= 0 || n.indexOf('urzad') >= 0 || n.indexOf(' pit') >= 0 || n.indexOf('tax') >= 0) {
      kind = L(s, 'Official letter', 'Pismo urzędowe');
    }
    if (n.indexOf('wezwanie') >= 0 || n.indexOf('overdue') >= 0 || n.indexOf('reminder to pay') >= 0) {
      kind = L(s, 'Payment reminder', 'Wezwanie do zapłaty');
    }
    const meaning: string[] = [];
    if (amount.length > 0) {
      meaning.push(L(s, 'You need to pay ', 'Do zapłaty: ') + amount);
    }
    if (due.length > 0) {
      meaning.push(L(s, 'Deadline: ', 'Termin: ') + due);
    }
    meaning.push(L(s, 'Pay only via your bank app or the post office — never via a link in an SMS.',
      'Płać tylko w aplikacji banku lub na poczcie — nigdy przez link z SMS-a.'));
    const who = caregiverOf(p);
    const actions: TileAction[] = [];
    if (due.length > 0) {
      actions.push(act(L(s, 'Remind me at 9:00', 'Przypomnij o 9:00'), 'remind', '09:00'));
    }
    actions.push(act(L(s, 'Mark paid', 'Zapłacone'), 'done', 'bill'));
    if (who.length > 0) {
      actions.push(act(L(s, 'Ask ', 'Zapytaj: ') + personLabel(who, s.lang), 'call', who));
    }
    const blocks: TileBlock[] = [];
    if (amount.length > 0) {
      blocks.push(bigBlock(amount, due.length > 0 ? L(s, 'due ', 'termin ') + due : kind));
    }
    blocks.push(listBlock(L(s, 'What it means', 'Co to znaczy'), meaning));
    blocks.push(buttonsBlock(actions));
    const sub = kind + (hasContent ? '' : L(s, ' · demo letter', ' · pismo demo'));
    d.tiles.push(f.make('note', L(s, 'Letter: ', 'Pismo: ') + sender, sub, 'doc_text_fill', 'sky', sz(p, '2x2'),
      blocks, kind + '. ' + meaning.join('. ')));
    d.replies.push(hasContent ? L(s, 'In short: ' + meaning.slice(0, 2).join(', ') + '.',
      'W skrócie: ' + meaning.slice(0, 2).join(', ') + '.') :
      L(s, 'Here is how I explain a letter — this one uses a demo bill. Paste the letter text and I will summarise it.',
        'Tak tłumaczę pisma — tu na przykładowym rachunku. Wklej treść pisma, a je streszczę.'));
    d.addFollow(L(s, 'Is this a scam? "Your account is blocked, pay now via this link"',
      'Czy to oszustwo? "Konto zablokowane, zapłać teraz przez link"'));
  }

  private static scam(s: Slots, p: Profile, f: Factory, d: Draft): void {
    // Text after the question = the message to check ("Is this a scam? <message>").
    let msg = s.raw.replace(/^.*?(scam|oszustwo|oszust\w*|podejrzan\w*|suspicious|fraud|real)\s*\??\s*[:\-–]?\s*/i, '');
    msg = msg.replace(/^["'„“]|["'”“]$/g, '').trim();
    const who = caregiverOf(p);
    const guardianBtn = act(L(s, 'Open Guardian', 'Otwórz Guardian'), 'navigate', 'guardian');
    if (msg.length < 12) {
      const t: TileSpec = Guardian.tile(who);
      const g: TileSpec = f.make('guardian', t.title, t.subtitle, 'exclamationmark_shield_fill', 'mint', sz(p, '2x1'),
        t.blocks, t.speakText);
      d.tiles.push(g);
      d.replies.push(L(s, 'Guardian checks calls and messages for scam signs. Paste the message after your question, ' +
        'or open Guardian to try a demo call.',
        'Guardian sprawdza telefony i SMS-y pod kątem oszustw. Wklej treść wiadomości albo otwórz Guardian i wypróbuj demo.'));
      d.addFollow(L(s, 'Is this a scam? "Grandma, it\'s me, I need money now, don\'t tell anyone"',
        'Czy to oszustwo? "Babciu, to ja, potrzebuję pieniędzy, nie mów nikomu"'));
      return;
    }
    const v: GuardianVerdict = Guardian.analyze(msg, false, s.lang, who);
    const chips: string[] = [];
    for (let i = 0; i < v.flags.length && i < 3; i++) {
      chips.push(s.lang === 'pl' ? v.flags[i].labelPl : v.flags[i].label);
    }
    const actions: TileAction[] = [guardianBtn];
    if (who.length > 0) {
      actions.push(act(L(s, 'Call ', 'Zadzwoń: ') + personLabel(who, s.lang), 'call', who));
    }
    const color = v.level === 'scam' ? 'coral' : (v.level === 'caution' ? 'sun' : 'mint');
    const alert: TileBlock = alertBlock(v.headline + ' ' + v.instruction,
      v.level === 'scam' ? 'danger' : (v.level === 'caution' ? 'warn' : 'info'), chips);
    d.tiles.push(f.make('guardian', L(s, 'Guardian check', 'Sprawdzenie Guardian'),
      L(s, 'Scam risk ', 'Ryzyko oszustwa ') + v.risk.toString() + '%', 'exclamationmark_shield_fill', color,
      sz(p, '2x2'), [
      alert,
      textBlock('"' + short(msg, 90) + '"'),
      buttonsBlock(actions)
    ], v.headline + ' ' + v.instruction));
    d.replies.push(v.level === 'scam' ?
      L(s, 'Guardian thinks this is a scam (' + v.risk.toString() + '%). Do not send money or codes.',
        'Guardian uważa, że to oszustwo (' + v.risk.toString() + '%). Nie wysyłaj pieniędzy ani kodów.') :
      L(s, 'Guardian checked it on this phone: ' + v.headline.toLowerCase(),
        'Guardian sprawdził to na telefonie: ' + v.headline.toLowerCase()));
    d.addFollow(L(s, 'Open Guardian', 'Otwórz Guardian'));
  }

  private static commute(s: Slots, p: Profile, f: Factory, d: Draft): void {
    const dest = s.place.length > 0 ? s.place : (p.id === 'lowvision' ? 'Rondo Mogilskie' : 'Rynek');
    const n = norm(s.raw);
    const bus = n.indexOf('bus') >= 0 || n.indexOf('autobus') >= 0;
    const title = bus ? L(s, 'Bus 179 in 6 min', 'Autobus 179 za 6 min') : L(s, 'Tram 52 in 4 min', 'Tramwaj 52 za 4 min');
    d.tiles.push(f.make('commute', title, L(s, 'To ', 'Do: ') + dest + L(s, ' · demo times', ' · czasy demo'),
      bus ? 'bus_fill' : 'tram_fill', 'sun', sz(p, '2x1'), [
      bigBlock(bus ? '6 min' : '4 min', L(s, 'then 12 min ride', 'potem 12 min jazdy')),
      buttonsBlock([act(L(s, 'Directions', 'Prowadź'), 'navigate', dest)])
    ], title + '. ' + L(s, 'To ', 'Do: ') + dest + '.'));
    d.replies.push(L(s, 'Commute tile added (demo timetable).', 'Dodałem kafelek dojazdu (rozkład demo).'));
  }

  private static adventure(s: Slots, p: Profile, f: Factory, d: Draft): void {
    const items = [L(s, 'A red leaf', 'Czerwony liść'), L(s, 'A chestnut', 'Kasztan'),
      L(s, 'Something round', 'Coś okrągłego')];
    d.tiles.push(f.make('adventure', L(s, 'Today\'s adventure', 'Dzisiejsza przygoda'),
      s.place.length > 0 && s.place !== 'School' && s.place !== 'Szkoła' ? s.place :
        L(s, 'Park after school', 'Park po szkole'), 'star_fill', 'leaf', sz(p, '2x1'), [
      checklistBlock(L(s, 'Find 3 things', 'Znajdź 3 rzeczy'), items, [])
    ], L(s, 'Today\'s adventure: find ', 'Dzisiejsza przygoda: znajdź ') + items.join(', ') + '.'));
    d.replies.push(L(s, 'Adventure time! Find all three.', 'Czas na przygodę! Znajdź wszystkie trzy.'));
  }

  /** Unknown request: a sensible note (or checklist) plus clarifying chips. */
  private static fallback(s: Slots, p: Profile, f: Factory, d: Draft): void {
    const body = Composer.what(s.raw).length > 0 ? Composer.what(s.raw) : s.raw;
    const parts = s.raw.split(/,|;/).map((x: string) => x.trim()).filter((x: string) => x.length > 0);
    if (parts.length >= 3) {
      const items = parts.slice(0, 8).map((x: string) => cap(x));
      d.tiles.push(f.make('note', L(s, 'My list', 'Moja lista'), items.length.toString() + L(s, ' items', ' pozycji'),
        'list', 'leaf', sz(p, '2x1'), [checklistBlock('', items, [])], items.join(', ')));
      d.replies.push(L(s, 'I was not sure what you meant, so I made it a checklist.',
        'Nie byłem pewien, o co chodzi, więc zrobiłem z tego listę.'));
    } else {
      d.tiles.push(f.make('note', short(body, 24), L(s, 'Note', 'Notatka'), 'note', 'ink', sz(p, '2x1'),
        [textBlock(short(body, 140))], body));
      d.replies.push(L(s, 'I saved it as a note. Want it to be something else?',
        'Zapisałem to jako notatkę. Zrobić z tego coś innego?'));
    }
    d.addFollow(L(s, 'Remind me: ', 'Przypomnij: ') + short(body, 30) + L(s, ' at 18:00', ' o 18:00'));
    d.addFollow(L(s, 'Checklist: ', 'Lista: ') + short(s.raw, 40));
    if (caregiverOf(p).length > 0) {
      d.addFollow(L(s, 'Call ', 'Zadzwoń: ') + personLabel(caregiverOf(p), s.lang));
    }
  }
}

/** Functional entry point matching docs/TILES_SPEC.md: compose(prompt, profile). */
export function compose(prompt: string, profile: Profile): ComposeResult {
  return Composer.compose(prompt, profile);
}
