import { LengthMetrics } from '@kit.ArkUI';
import { Profile, TileAction, TileBlock, TileSpec } from '../model/Tile';
import { TilesTheme, ThemePalette } from '../theme/TilesTheme';
import { TileView } from './TileView';

// Local builders (kept independent of SeedTiles so the gallery always compiles and shows every block kind).
function a(label: string, kind: string, arg: string): TileAction {
  const x: TileAction = new TileAction();
  x.label = label;
  x.kind = kind;
  x.arg = arg;
  return x;
}

function blk(kind: string, text: string, value: string, items: string[], progress: number,
  actions: TileAction[]): TileBlock {
  const b: TileBlock = new TileBlock();
  b.kind = kind;
  b.text = text;
  b.value = value;
  b.items = items;
  b.progress = progress;
  b.actions = actions;
  return b;
}

function chk(text: string, items: string[], checked: boolean[]): TileBlock {
  const b: TileBlock = blk('checklist', text, '', items, 0, []);
  b.checked = checked;
  return b;
}

function t(id: string, title: string, subtitle: string, icon: string, color: string, size: string, source: string,
  blocks: TileBlock[]): TileSpec {
  const s: TileSpec = new TileSpec();
  s.id = id;
  s.type = 'custom';
  s.title = title;
  s.subtitle = subtitle;
  s.icon = icon;
  s.color = color;
  s.size = size;
  s.source = source;
  s.blocks = blocks;
  s.speakText = title + '. ' + subtitle;
  s.createdAt = source === 'assistant' ? Date.now() : 0;
  return s;
}

/** One sample tile per block kind, in every palette color and size. Used for screenshots and renderer QA. */
export function galleryTiles(): TileSpec[] {
  return [
    t('g-pills', 'Pills 8:00', 'Polpril 5 mg + Vitamin D', 'cross_case_fill', 'mint', '2x1', 'seed', [
      blk('big', 'Morning pills', '8:00', [], 0, []),
      blk('buttons', '', '', [], 0, [a('Taken', 'done', 'pills'), a('Remind in 15 min', 'remind', '15')])
    ]),
    t('g-call', 'Call Kasia', 'Your daughter', 'phone_fill', 'sky', '1x1', 'seed', [
      blk('buttons', '', '', [], 0, [a('Call', 'call', 'Kasia')])
    ]),
    t('g-temp', '14°', 'Kraków', 'umbrella', 'peach', '1x1', 'seed', [
      blk('weather', 'Rain until 15:00', '14°', [], 0, [])
    ]),
    t('g-weather', '14° and rain', 'Take the umbrella', 'cloud_sun_fill', 'peach', '2x2', 'seed', [
      blk('weather', 'Rain until 15:00', '14°', ['Umbrella', 'Warm coat', 'Boots'], 0, []),
      blk('text', 'Dry again after 15:00 — good time for the walk in Park Lotników.', '', [], 0, [])
    ]),
    t('g-guardian', 'Guardian', 'Scam shield is on · Demo call', 'exclamationmark_shield_fill', 'coral', '2x2',
      'seed', [
        blk('alert', 'Demo call: "Grandma, it\'s me. I need money right now, don\'t tell anyone."',
          'This looks like a scam. Hang up. Kasia already knows.', ['asks for money', 'pressure: right now'], 0, []),
        blk('buttons', '', '', [], 0, [a('Hang up', 'dismiss', 'demo'), a('Call Kasia', 'call', 'Kasia')])
      ]),
    t('g-homework', 'Homework', '3 of 5 done', 'book_pages_fill', 'sun', '2x2', 'seed', [
      blk('progress', 'Almost there!', '3 of 5', [], 0.6, []),
      chk('', ['Maths p. 42', 'Read 10 pages', 'English words', 'Draw an autumn leaf'], [true, true, true, false])
    ]),
    t('g-focus', 'Focus timer', 'Reading time', 'timer', 'grape', '2x1', 'seed', [
      blk('timer', 'Read, then a break', '15:00', [], 0, [])
    ]),
    t('g-next', 'Next pills', 'Evening dose', 'alarm_fill', 'leaf', '2x1', 'seed', [
      blk('timer', 'Evening pills', 'at:20:00', [], 0, [])
    ]),
    t('g-screen', 'Screen time', '45 of 60 min left', 'hourglass', 'mint', '1x1', 'seed', [
      blk('progress', '', '45 min', [], 0.75, [])
    ]),
    t('g-plan', 'Dinner Fri 19:30', 'Ola, Kuba · vegan · < 80 zł', 'fork_knife', 'grape', '2x2', 'assistant', [
      blk('list', 'Options near Kazimierz', '', ['Veganda · 55 zł', 'Krowarzywa · 40 zł', 'Glonojad · 45 zł'], 0, []),
      blk('chips', 'Vote', '', [], 0, [a('Veganda', 'vote', '0'), a('Krowarzywa', 'vote', '1'), a('Glonojad', 'vote', '2')])
    ]),
    t('g-visit', 'Kasia visits Sunday', 'Lunch at 13:00', 'house_fill', 'sun', '2x1', 'adaptation', [
      blk('list', 'Remember', '', ['Photo album for Ola', 'Pierogi from the freezer'], 0, [])
    ]),
    t('g-sos', 'SOS', 'Hold to call for help', 'phone_sos', 'ink', '1x1', 'seed', [
      blk('buttons', '', '', [], 0, [a('Help', 'sos', 'Kasia')])
    ]),
    t('g-tags', 'Commute', 'Tram 4 · 8 min', 'tram_fill', 'sky', '2x1', 'seed', [
      blk('big', 'Next tram to Rondo Mogilskie', '8 min', [], 0, []),
      blk('chips', '', '', ['On time', 'Line 4', 'Platform B'], 0, [])
    ]),
    t('g-unknown', 'Unknown block', 'Renderer degrades gracefully', 'not_a_symbol', 'coral', '2x1', 'seed', [
      blk('hologram', 'Unknown kinds render as text instead of crashing.', '', [], 0, [])
    ])
  ];
}

class ProfileChip {
  id: string = '';
  label: string = '';
}

const PROFILE_CHIPS: ProfileChip[] = [
  { id: 'everyday', label: 'Everyday' },
  { id: 'senior', label: 'Senior' },
  { id: 'kid', label: 'Kid' }
];

function galleryProfile(id: string): Profile {
  const p: Profile = new Profile();
  p.id = id;
  if (id === 'senior') {
    p.name = 'Halina';
    p.textScale = 1.4;
    p.highContrast = true;
    p.readAloud = true;
    p.columns = 2;
  } else if (id === 'kid') {
    p.name = 'Zosia';
    p.textScale = 1.15;
    p.columns = 4;
  } else {
    p.name = 'Daniel';
  }
  return p;
}

/**
 * Debug gallery: renders every block kind in every size and palette, with a profile switch
 * (everyday / senior high-contrast / kid) and light / dark toggle. Actions are logged in a status line only.
 */
@Component
export struct TileGallery {
  @State profileId: string = 'everyday';
  @State dark: boolean = false;
  @State lastAction: string = 'Tap anything — actions are shown here (no side effects).';
  @State tiles: TileSpec[] = galleryTiles();

  private profile(): Profile {
    return galleryProfile(this.profileId);
  }

  private pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile().highContrast);
  }

  /** 1x1 tiles take half the row, others the full row (2-column preview grid). */
  private widthOf(size: string): string {
    return size === '1x1' ? '48.5%' : '100%';
  }

  build() {
    Column({ space: 12 }) {
      Row({ space: 6 }) {
        ForEach(PROFILE_CHIPS, (c: ProfileChip) => {
          Text(c.label)
            .fontSize(14)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.profileId === c.id ? this.pal().onAccent : this.pal().text)
            .padding({ left: 12, right: 12 })
            .height(40)
            .borderRadius(999)
            .backgroundColor(this.profileId === c.id ? this.pal().accent : this.pal().surfaceAlt)
            .onClick(() => {
              this.profileId = c.id;
            })
        }, (c: ProfileChip) => c.id)
        Blank()
        Text(this.dark ? 'Dark' : 'Light')
          .fontSize(14)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().text)
          .padding({ left: 10, right: 10 })
          .height(40)
          .borderRadius(999)
          .backgroundColor(this.pal().surfaceAlt)
          .onClick(() => {
            this.dark = !this.dark;
          })
        Text('Replay')
          .fontSize(14)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().text)
          .padding({ left: 10, right: 10 })
          .height(40)
          .borderRadius(999)
          .backgroundColor(this.pal().surfaceAlt)
          .onClick(() => {
            this.tiles = [];
            setTimeout(() => {
              this.tiles = galleryTiles();
            }, 50);
          })
      }
      .width('100%')
      .padding({ left: 16, right: 16 })

      Text(this.lastAction)
        .fontSize(12)
        .fontColor(this.pal().textMuted)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .width('100%')
        .padding({ left: 16, right: 16 })

      Scroll() {
        Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween, space: { cross: LengthMetrics.vp(12) } }) {
          ForEach(this.tiles, (tile: TileSpec) => {
            Column() {
              TileView({
                tile: tile,
                profile: this.profile(),
                dark: this.dark,
                onAction: (act: TileAction, ts: TileSpec) => {
                  this.lastAction = ts.title + ' → ' + act.kind + (act.arg.length > 0 ? ' (' + act.arg + ')' : '') +
                    (act.label.length > 0 ? ' "' + act.label + '"' : '');
                },
                onLongPress: (ts: TileSpec) => {
                  this.lastAction = ts.title + ' → long press';
                }
              })
            }
            .width(this.widthOf(tile.size))
          }, (tile: TileSpec) => tile.id + ':' + this.profileId + ':' + this.dark)
        }
        .width('100%')
        .padding({ left: 16, right: 16, bottom: 32 })
      }
      .layoutWeight(1)
      .scrollBar(BarState.Off)
    }
    .width('100%')
    .height('100%')
    .padding({ top: 12 })
    .backgroundColor(this.pal().bg)
  }
}
