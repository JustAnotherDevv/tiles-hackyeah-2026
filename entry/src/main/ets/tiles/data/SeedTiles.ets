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
      p.columns = 2;
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
      p.caregiver = 'Ania';
      p.caregiverRole = 'daughter';
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
      return 'Halina, 78 · big, calm, read aloud';
    case 'kid':
      return 'Zosia, 8 · playful, parent approves';
    case 'lowvision':
      return 'Michał · voice first, huge targets';
    default:
      return 'Daniel, 29 · dense, expressive';
  }
}

// ---------- seed homes ----------

// Seed homes mirror the Living Light prototype (design/tiles-motion/source/Tiles_Stage.dc.html, const TILES): same
// tiles, order, sizes, palette and copy. Material Symbols are mapped to the closest SymbolGlyph (BlockStyle aliasOf /
// SymbolTable). Where the prototype makes a tap on the tile act (call / sos / done), the tile carries the same action
// as a button so the behaviour stays reachable from the home grid and the detail view.

function seniorTiles(): TileSpec[] {
  return [
    tile('sr-pills', 'pills', 'Pills 8:00', '', 'pill', 'sun', '2x1', [
      textBlock('Euthyrox 50 µg · tap when taken'),
      buttonsBlock([act('Taken', 'done', 'pills-morning'), act('Later', 'remind', '15')])
    ], 'Pills at eight. Euthyrox. Tap when taken.'),
    tile('sr-call-kasia', 'call', 'Call Kasia', 'Daughter', 'phone', 'leaf', '1x1', [
      buttonsBlock([act('Call', 'call', 'Kasia')])
    ], 'Call Kasia, your daughter.'),
    tile('sr-guardian', 'guardian', 'Guardian', '', 'shield', 'mint', '1x1', [
      textBlock('On · 2 calls blocked')
    ], 'Guardian is on. 2 calls blocked.'),
    tile('sr-weather', 'weather', '14° and rain', '', 'rain', 'sky', '2x1', [
      textBlock('Take the umbrella. Warmer by 3 pm.')
    ], '14 degrees and rain. Take the umbrella. Warmer by three.'),
    tile('sr-sos', 'sos', 'SOS', '', 'sos', 'rose', '1x1', [
      buttonsBlock([act('Hold 2 s', 'sos', 'Kasia')])
    ], 'S O S. Hold for two seconds to call Kasia and send your location.'),
    tile('sr-photos', 'custom', 'Photos', '', 'heart_square_stack', 'sand', '1x1', [
      textBlock('3 new from Zosia')
    ], 'Photos. 3 new from Zosia.'),
    tile('sr-apps', 'apps', 'More apps', '', 'star_folder_fill', 'sand', '2x1', [
      textBlock('Calculator · News · Maps · Wallet · Mail +9')
    ], 'More apps.')
  ];
}

function kidTiles(): TileSpec[] {
  return [
    // Count lives in the subtitle: TileStore.toggleCheck keeps a homework tile's subtitle in sync ('4 of 5 done').
    tile('kd-homework', 'homework', 'Homework', '3 of 5 done', 'book_open_fill', 'sun', '2x2', [
      checklistBlock('', ['Maths p. 42', 'Reading 20 min', 'Spelling list', 'Draw a leaf', 'Pack the bag'],
        [true, true, true, false, false])
    ], 'Homework: 3 of 5 done. Next: draw a leaf.'),
    tile('kd-focus', 'timer', 'Focus', '', 'timer', 'plum', '1x1', [
      timerBlock('with Mo', '15')
    ], 'Focus timer with Mo, 15 minutes.'),
    tile('kd-call-mum', 'call', 'Call Mum', 'Kasia', 'phone', 'leaf', '1x1', [
      buttonsBlock([act('Call', 'call', 'Mum')])
    ], 'Call Mum.'),
    tile('kd-screen', 'screentime', 'Energy today', '', 'bolt_fill', 'mint', '2x1', [
      progressBlock('', '1 h 10 min left · fair share', 70 / 120)
    ], 'Energy today: 1 hour 10 minutes left.'),
    tile('kd-adventure', 'adventure', 'Today\'s adventure', '', 'flag_fill', 'sky', '2x1', [
      textBlock('Find three red leaves on the way home.')
    ], 'Today\'s adventure: find three red leaves on the way home.'),
    tile('kd-weather', 'weather', '14°', '', 'rain', 'peach', '1x1', [
      textBlock('Rain · boots!')
    ], '14 degrees and rain. Wear your boots!'),
    tile('kd-photo', 'custom', 'Send to Babcia', '', 'camera_fill', 'rose', '1x1', [
      textBlock('a photo')
    ], 'Send a photo to Babcia.')
  ];
}

function lowVisionTiles(): TileSpec[] {
  return [
    tile('lv-speak', 'custom', 'Hold to speak', '', 'mic', 'ink', '2x1', [
      textBlock('Ask anything. I will read it back.')
    ], 'Hold to speak. Ask anything. I will read it back.'),
    tile('lv-call-ania', 'call', 'Call Ania', '', 'phone', 'leaf', '1x1', [
      buttonsBlock([act('Call', 'call', 'Ania')])
    ], 'Call Ania.'),
    tile('lv-sos', 'sos', 'SOS', '', 'sos', 'rose', '1x1', [
      buttonsBlock([act('Hold 2 s', 'sos', 'Ania')])
    ], 'S O S. Hold for two seconds.'),
    tile('lv-weather', 'weather', '14°, rain', '', 'rain', 'sky', '2x1', [
      textBlock('Umbrella. Warmer by 3 pm.')
    ], '14 degrees and rain. Take the umbrella. Warmer by three.'),
    tile('lv-messages', 'note', '2 new messages', '', 'mail', 'sun', '2x1', [
      textBlock('Tap to hear them')
    ], 'Two new messages. Ania: dinner at seven? Clinic: appointment Thursday at ten.')
  ];
}

function everydayTiles(): TileSpec[] {
  return [
    tile('ev-tram', 'commute', 'Tram 18 in 6 min', '', 'tram', 'sky', '2x1', [
      textBlock('Kazimierz → Rynek · leave 8:12')
    ], 'Tram 18 in 6 minutes, Kazimierz to Rynek. Leave at 8:12.'),
    tile('ev-weather', 'weather', 'Rain', '', 'rain', 'sand', '1x1', [
      bigBlock('14°', '')
    ], '14 degrees and rain.'),
    tile('ev-focus', 'timer', 'Focus', '', 'timer', 'plum', '1x1', [
      timerBlock('', '25')
    ], 'Focus timer, 25 minutes.'),
    tile('ev-dinner', 'plan', 'Dinner Fri 19:30', '', 'food', 'peach', '2x2', [
      textBlock('Veganda · Kazimierz · ~65 zł'),
      chipsBlock(['Ola ✓', 'Kuba ?', 'You ✓']),
      buttonsBlock([act('Vote', 'vote', 'Veganda'), act('Change', 'open', '')])
    ], 'Dinner on Friday at 7:30 PM at Veganda in Kazimierz, about 65 zloty. Ola is in, Kuba maybe.'),
    tile('ev-friends', 'plan', 'Ola, Kuba free', '', 'people', 'mint', '2x1', [
      textBlock('Tonight · only free/busy shared')
    ], 'Ola and Kuba are free tonight. Only free or busy is shared.'),
    tile('ev-calendar', 'reminder', 'Standup 10:00', '', 'calendar', 'sun', '2x1', [
      textBlock('+2 more today')
    ], 'Standup at 10, and 2 more today.'),
    tile('ev-run', 'custom', 'Run', '', 'figure_run', 'leaf', '1x1', [
      bigBlock('12 km', '')
    ], 'Run, 12 kilometres.'),
    tile('ev-call-ola', 'call', 'Call Ola', '', 'phone', 'rose', '1x1', [
      buttonsBlock([act('Call', 'call', 'Ola')])
    ], 'Call Ola.'),
    tile('ev-music', 'custom', 'Playlist', '', 'music', 'ink', '1x1', [], 'Playlist.'),
    tile('ev-photos', 'custom', 'Photos', '', 'heart_square_stack', 'sky', '1x1', [], 'Photos.'),
    tile('ev-inbox', 'note', '3 unread', '', 'mail', 'plum', '2x1', [
      textBlock('Ola: see you Fri?')
    ], '3 unread messages. Ola: see you Friday?'),
    tile('ev-steps', 'custom', '6 412 steps', '', 'figure_walk', 'sand', '2x1', [
      progressBlock('', '64% of 10 000', 0.6412)
    ], '6412 steps, 64 percent of 10 thousand.')
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
