import { Profile, Suggestion, TileAction, TileBlock, TileSpec } from '../model/Tile';

/**
 * Seed homes for the four ICPs (docs/TILES_SPEC.md). Fictional people and places in Kraków; no real personal
 * data. Guardian scam examples are labelled "Demo call" / "Demo SMS" (simulated input).
 * Icons are TileView ICON keys (see scratchpad REQUESTS.md / TileView); block conventions follow T-RENDER's TileView.
 */

export const PROFILE_IDS: string[] = ['senior', 'kid', 'lowvision', 'everyday'];

// ---------- builders (also used by Composer / Adaptation) ----------

export function act(label: string, kind: string, arg: string): TileAction {
  const a: TileAction = new TileAction();
  a.label = label;
  a.kind = kind;
  a.arg = arg;
  return a;
}

export function textBlock(text: string): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = 'text';
  b.text = text;
  return b;
}

/** Big hero value (e.g. '8:00', '14°', '4 min') with a short caption. */
export function bigBlock(value: string, text: string): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = 'big';
  b.value = value;
  b.text = text;
  return b;
}

export function listBlock(text: string, items: string[]): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = 'list';
  b.text = text;
  b.items = items;
  return b;
}

export function checklistBlock(text: string, items: string[], checked: boolean[]): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = 'checklist';
  b.text = text;
  b.items = items;
  const c: boolean[] = [];
  for (let i = 0; i < items.length; i++) {
    c.push(i < checked.length ? checked[i] : false);
  }
  b.checked = c;
  return b;
}

/** progress 0..1; value is the human label ('3 of 5'). */
export function progressBlock(text: string, value: string, progress: number): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = 'progress';
  b.text = text;
  b.value = value;
  b.progress = Math.max(0, Math.min(1, progress));
  return b;
}

export function buttonsBlock(actions: TileAction[]): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = 'buttons';
  b.actions = actions;
  return b;
}

/** value = focus minutes ('25'), or 'at:08:00' for a live countdown to a clock time; text = label. */
export function timerBlock(text: string, value: string): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = 'timer';
  b.text = text;
  b.value = value;
  return b;
}

export function chipsBlock(items: string[]): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = 'chips';
  b.items = items;
  return b;
}

/** text = message, level = 'danger' | 'warn' | 'info', flags = red flags shown as chips. */
export function alertBlock(text: string, level: string, flags: string[]): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = 'alert';
  b.text = text;
  b.value = level;
  b.items = flags;
  return b;
}

/** Tappable chips (e.g. vote options with kind 'vote'). */
export function actionChipsBlock(actions: TileAction[]): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = 'chips';
  b.actions = actions;
  return b;
}

/** value = temperature ('14°'), text = condition ('Rain, 9-16°'; keyword picks the icon), items = what-to-wear hints. */
export function weatherBlock(value: string, text: string, items: string[]): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = 'weather';
  b.value = value;
  b.text = text;
  b.items = items;
  return b;
}

export function tile(id: string, type: string, title: string, subtitle: string, icon: string, color: string,
  size: string, blocks: TileBlock[], speakText: string): TileSpec {
  const t: TileSpec = new TileSpec();
  t.id = id;
  t.type = type;
  t.title = title;
  t.subtitle = subtitle;
  t.icon = icon;
  t.color = color;
  t.size = size;
  t.blocks = blocks;
  t.source = 'seed';
  t.speakText = speakText.length > 0 ? speakText : (subtitle.length > 0 ? title + '. ' + subtitle : title);
  t.createdAt = 0;
  return t;
}

// ---------- profiles ----------

export function profileFor(id: string): Profile {
  const p: Profile = new Profile();
  switch (id) {
    case 'senior':
      p.id = 'senior';
      p.name = 'Halina';
      p.textScale = 1.4;
      p.highContrast = true;
      p.readAloud = true;
      p.columns = 2;
      p.caregiver = 'Kasia';
      p.caregiverRole = 'daughter';
      break;
    case 'kid':
      p.id = 'kid';
      p.name = 'Zosia';
      p.textScale = 1.15;
      p.highContrast = false;
      p.readAloud = false;
      p.columns = 4;
      p.caregiver = 'Mum';
      p.caregiverRole = 'parent';
      break;
    case 'lowvision':
      p.id = 'lowvision';
      p.name = 'Michał';
      p.textScale = 1.6;
      p.highContrast = true;
      p.readAloud = true;
      p.columns = 2;
      p.caregiver = 'Tomek';
      p.caregiverRole = 'brother';
      break;
    default:
      p.id = 'everyday';
      p.name = 'Daniel';
      p.textScale = 1.0;
      p.highContrast = false;
      p.readAloud = false;
      p.columns = 4;
      p.caregiver = '';
      p.caregiverRole = '';
      break;
  }
  return p;
}

/** One-line description for the profile picker. */
export function profileBlurb(id: string): string {
  switch (id) {
    case 'senior':
      return 'Halina, 78 · big tiles, read aloud, scam shield. Kasia approves changes.';
    case 'kid':
      return 'Zosia, 8 · homework, focus timer, screen time. Mum approves new tiles.';
    case 'lowvision':
      return 'Michał · voice first, extra-large targets, high contrast.';
    default:
      return 'Daniel, 29 · plans with friends, focus, commute.';
  }
}

// ---------- seed homes ----------

function seniorTiles(): TileSpec[] {
  return [
    tile('sr-pills', 'pills', 'Pills 8:00', 'Polpril 5 mg + Vitamin D', 'pill', 'mint', '2x1', [
      bigBlock('8:00', 'Morning pills'),
      checklistBlock('', ['Polpril 5 mg', 'Vitamin D 2000'], [false, false]),
      buttonsBlock([act('Taken', 'done', 'pills-morning'), act('Remind in 15 min', 'remind', '15')])
    ], 'Time for your morning pills: Polpril and vitamin D. Tap Taken when you have taken them.'),
    tile('sr-call-kasia', 'call', 'Call Kasia', 'Your daughter', 'phone', 'sky', '2x1', [
      textBlock('Usually free after 17:00'),
      buttonsBlock([act('Call', 'call', 'Kasia')])
    ], 'Call Kasia, your daughter.'),
    tile('sr-weather', 'weather', '14° and rain', 'Kraków, Nowa Huta', 'rain', 'peach', '2x1', [
      weatherBlock('14°', 'Rain until 15:00, 9-16°', ['Take the umbrella', 'Warm coat', 'Waterproof shoes'])
    ], 'It is 14 degrees and raining until 3 PM. Take the umbrella and the warm coat.'),
    tile('sr-guardian', 'guardian', 'Guardian', 'Scam shield is on', 'shield', 'coral', '2x2', [
      alertBlock('Demo call: "Grandma, it\'s me. I need money right now, don\'t tell anyone."', 'danger',
        ['asks for money', 'pressure: right now', 'keep it secret']),
      textBlock('This looks like a scam. Hang up. Kasia already knows.'),
      buttonsBlock([act('Hang up', 'dismiss', 'guardian-demo'), act('Call Kasia', 'call', 'Kasia')])
    ], 'Warning. This looks like a scam. Hang up. Kasia already knows.'),
    tile('sr-doctor', 'reminder', 'Doctor Wed 10:30', 'Dr Nowak · Przychodnia Bieńczyce', 'calendar', 'grape',
      '2x1', [
        textBlock('Bring the blood test results and your ID card.'),
        buttonsBlock([act('Remind me Tuesday', 'remind', 'tue-18:00'), act('Read aloud', 'speak', '')])
      ], 'Doctor appointment on Wednesday at 10:30 with doctor Nowak. Bring the blood test results.'),
    tile('sr-walk', 'reminder', 'Walk at 17:00', 'Park Lotników · 20 min', 'walk', 'leaf', '1x1', [
      textBlock('Dry after 15:00')
    ], 'Evening walk at 5 PM in Park Lotników, about 20 minutes.'),
    tile('sr-sos', 'sos', 'SOS', 'Hold to call for help', 'sos', 'ink', '1x1', [
      buttonsBlock([act('Hold for help', 'sos', 'Kasia')])
    ], 'S O S. Hold the button to call Kasia and send your location.'),
    tile('sr-visit', 'note', 'Kasia visits Sunday', 'Lunch at 13:00', 'house', 'sun', '2x1', [
      listBlock('Remember', ['Photo album for Ola', 'Pierogi from the freezer'])
    ], 'Kasia visits on Sunday for lunch at 1 PM.')
  ];
}

function kidTiles(): TileSpec[] {
  return [
    tile('kd-homework', 'homework', 'Homework', '3 of 5 done', 'book', 'sun', '2x2', [
      progressBlock('Almost there!', '3 of 5', 0.6),
      checklistBlock('', ['Maths p. 42', 'Read 10 pages', 'English words', 'Draw an autumn leaf', 'Pack school bag'],
        [true, true, true, false, false])
    ], 'Homework: 3 of 5 done. Next: draw an autumn leaf.'),
    tile('kd-focus', 'timer', 'Focus timer', 'Reading time', 'timer', 'grape', '2x1', [
      timerBlock('Read your book, then a break', '15')
    ], 'Focus timer, 15 minutes of reading.'),
    tile('kd-call-mum', 'call', 'Call Mum', 'Mum', 'phone', 'coral', '1x1', [
      buttonsBlock([act('Call', 'call', 'Mum')])
    ], 'Call Mum.'),
    tile('kd-grandma', 'call', 'Call Grandma', 'Babcia Halina', 'heart', 'peach', '1x1', [
      buttonsBlock([act('Call', 'call', 'Babcia Halina')])
    ], 'Call Grandma Halina.'),
    tile('kd-screen', 'screentime', 'Screen time', '45 of 60 min left', 'game', 'mint', '2x1', [
      progressBlock('Plenty left for today', '45 min', 0.75)
    ], 'You have 45 of 60 minutes of screen time left today.'),
    tile('kd-adventure', 'adventure', "Today's adventure", 'Planty park after school', 'leaf', 'leaf', '2x1', [
      checklistBlock('Find 3 things', ['A red leaf', 'A chestnut', 'A pigeon feather'], [false, false, false])
    ], "Today's adventure: find a red leaf, a chestnut and a pigeon feather in the park."),
    tile('kd-swim', 'reminder', 'Swimming 16:30', 'Pack goggles + towel', 'bell', 'sky', '2x1', [
      checklistBlock('', ['Goggles', 'Towel', 'Swim cap'], [false, false, false])
    ], 'Swimming at 4:30. Pack goggles, towel and swim cap.'),
    tile('kd-pickup', 'note', 'Tata picks you up', '15:00 at the school gate', 'people', 'ink', '2x1', [
      textBlock('Wait inside if it rains.')
    ], 'Dad picks you up at 3 PM at the school gate.')
  ];
}

function lowVisionTiles(): TileSpec[] {
  return [
    tile('lv-call-tomek', 'call', 'Call Tomek', 'Your brother', 'phone', 'sky', '2x1', [
      buttonsBlock([act('Call', 'call', 'Tomek')])
    ], 'Call Tomek, your brother.'),
    tile('lv-drops', 'pills', 'Eye drops 9:00', 'Both eyes, 1 drop', 'pill', 'mint', '2x1', [
      bigBlock('9:00', 'Next dose'),
      buttonsBlock([act('Done', 'done', 'drops'), act('Read aloud', 'speak', '')])
    ], 'Eye drops at 9 o clock, one drop in each eye.'),
    tile('lv-bus', 'commute', 'Bus 179 in 6 min', 'Stop: Rondo Mogilskie', 'bus', 'sun', '2x1', [
      bigBlock('6 min', 'to Rondo Mogilskie'),
      buttonsBlock([act('Guide me to the stop', 'navigate', 'Rondo Mogilskie')])
    ], 'Bus 179 leaves in 6 minutes from Rondo Mogilskie.'),
    tile('lv-weather', 'weather', '11° cloudy', 'Kraków', 'weather', 'peach', '2x1', [
      weatherBlock('11°', 'Cloudy, dry, 8-12°', ['A light jacket is enough'])
    ], 'It is 11 degrees and cloudy. A light jacket is enough.'),
    tile('lv-messages', 'note', 'Read my messages', '2 new from Tomek', 'speaker', 'grape', '2x1', [
      buttonsBlock([act('Read aloud', 'speak', 'messages')])
    ], 'You have 2 new messages from Tomek. Tap to hear them.'),
    tile('lv-sos', 'sos', 'SOS', 'Hold to call for help', 'sos', 'ink', '2x1', [
      buttonsBlock([act('Hold for help', 'sos', 'Tomek')])
    ], 'S O S. Hold to call Tomek and share your location.')
  ];
}

function everydayTiles(): TileSpec[] {
  return [
    tile('ev-dinner', 'plan', 'Dinner Fri 19:30', 'Kazimierz · Ola, Kuba + you', 'food', 'grape', '2x2', [
      chipsBlock(['vegan', 'Kazimierz', 'under 80 zł']),
      listBlock('Options', ['Veganda · ~62 zł · 2 votes', 'Krowarzywa · ~45 zł · 1 vote', 'Glonojad · ~55 zł']),
      actionChipsBlock([act('Veganda', 'vote', 'Veganda'), act('Krowarzywa', 'vote', 'Krowarzywa'),
        act('Glonojad', 'vote', 'Glonojad')])
    ], 'Dinner on Friday at 7:30 PM in Kazimierz with Ola and Kuba. Veganda leads with 2 votes.'),
    tile('ev-focus', 'timer', 'Focus 25:00', 'Deep work: pitch deck', 'timer', 'sky', '2x1', [
      timerBlock('Phone on silent while it runs', '25')
    ], 'Focus timer, 25 minutes for the pitch deck.'),
    tile('ev-tram', 'commute', 'Tram 52 in 4 min', 'Rondo Grzegórzeckie → Rynek', 'tram', 'sun', '2x1', [
      bigBlock('4 min', 'then 12 min ride'),
      buttonsBlock([act('Directions', 'navigate', 'Rondo Grzegórzeckie')])
    ], 'Tram 52 in 4 minutes from Rondo Grzegórzeckie.'),
    tile('ev-weather', 'weather', '14° rain', 'Kraków', 'rain', 'peach', '1x1', [
      weatherBlock('14°', 'Rain, 9-16°', ['Umbrella'])
    ], '14 degrees, rain until 3 PM.'),
    tile('ev-gym', 'reminder', 'Gym 7:30', 'Legs day', 'walk', 'mint', '1x1', [
      textBlock('Tomorrow')
    ], 'Gym tomorrow at 7:30.'),
    tile('ev-mum', 'call', 'Call Mum', 'Sunday ritual', 'phone', 'coral', '1x1', [
      buttonsBlock([act('Call', 'call', 'Mum')])
    ], 'Call Mum.'),
    tile('ev-guardian', 'guardian', 'Guardian', '2 spam calls blocked', 'shield', 'ink', '1x1', [
      textBlock('Demo data')
    ], 'Guardian blocked 2 spam calls today. Demo data.'),
    tile('ev-groceries', 'note', 'Groceries', 'Biedronka on the way home', 'check', 'leaf', '2x1', [
      checklistBlock('', ['Oat milk', 'Tofu', 'Sourdough bread', 'Apples'], [false, true, false, false])
    ], 'Groceries: oat milk, tofu, sourdough bread, apples.'),
    tile('ev-demo', 'reminder', 'HackYeah demo 09:00', 'Tauron Arena · stage B', 'flag', 'coral', '2x1', [
      progressBlock('Slides ready', '4 of 5', 0.8),
      buttonsBlock([act('Remind 30 min before', 'remind', '08:30')])
    ], 'HackYeah demo at 9 AM. Slides 4 of 5 ready.')
  ];
}

/** Fresh seed home for a profile id (new objects every call). */
export function seedTilesFor(profileId: string): TileSpec[] {
  switch (profileId) {
    case 'senior':
      return seniorTiles();
    case 'kid':
      return kidTiles();
    case 'lowvision':
      return lowVisionTiles();
    default:
      return everydayTiles();
  }
}

function suggestion(id: string, title: string, detail: string, change: string, reason: string): Suggestion {
  const s: Suggestion = new Suggestion();
  s.id = id;
  s.title = title;
  s.detail = detail;
  s.change = change;
  s.reason = reason;
  s.status = 'pending';
  return s;
}

/** Starting adaptation suggestions (Adaptation.ets adds more from live usage signals). */
export function seedSuggestionsFor(profileId: string): Suggestion[] {
  switch (profileId) {
    case 'senior':
      return [
        suggestion('sg-sr-text', 'Make text 40% bigger', 'Tiles text grows from 1.4x to 1.8x.', 'textScale:1.8',
          '11 missed taps today, mostly on small buttons'),
        suggestion('sg-sr-hide', 'Hide 14 unused apps', 'Only the tiles Halina uses stay on the home screen.',
          'hide:apps', 'Not opened in 30 days')
      ];
    case 'kid':
      return [
        suggestion('sg-kd-focus', 'Longer focus timer', 'Reading timer goes from 15 to 20 minutes.', 'timer:20',
          'Zosia finished 3 timers in a row')
      ];
    case 'lowvision':
      return [
        suggestion('sg-lv-read', 'Read every tile aloud on open', 'Tiles speaks each tile when the home opens.',
          'readAloud:on', 'Most tiles were opened with the screen reader')
      ];
    default:
      return [
        suggestion('sg-ev-commute', 'Hide the commute tile', 'You work from home this week; the tram tile goes away.',
          'hide:commute', 'Not opened for 6 days')
      ];
  }
}
