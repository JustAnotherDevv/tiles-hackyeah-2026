import { curves } from '@kit.ArkUI';
import { Profile, TileAction, TileBlock, TileSpec } from '../model/Tile';
import { TileStore, cloneTile } from '../data/TileStore';
import { profileFor, seedTilesFor } from '../data/SeedTiles';
import {
  LL_FONT_FAMILY,
  ProfileLayout,
  TileColors,
  TilesTheme,
  ThemePalette,
  TypeScale,
  withAlpha
} from '../theme/TilesTheme';
import { tileIcon } from '../components/blocks/BlockStyle';
import { K_REDUCE_MOTION } from './ShellKeys';

/** One "Who is this phone for?" choice (prototype ICPS). */
export class ChoiceDef {
  id: string;
  label: string;
  line: string;
  color: string;
  icon: string;

  constructor(id: string, label: string, line: string, color: string, icon: string) {
    this.id = id;
    this.label = label;
    this.line = line;
    this.color = color;
    this.icon = icon;
  }
}

/** Living Light chooser (Tiles_Stage ICPS): Senior/sun, Kid/leaf, Low vision/ink, Everyday/sky. */
export const PROFILE_CHOICES: ChoiceDef[] = [
  new ChoiceDef('senior', 'Senior', 'Halina, 78 · big, calm, read aloud', 'sun', 'walk'),
  new ChoiceDef('kid', 'Kid', 'Zosia, 8 · playful, parent approves', 'leaf', 'star'),
  new ChoiceDef('lowvision', 'Low vision', 'Michał · voice first, huge targets', 'ink', 'speaker'),
  new ChoiceDef('everyday', 'Everyday', 'Daniel, 29 · dense, expressive', 'sky', 'person')
];

export function choiceLabel(id: string): string {
  for (const c of PROFILE_CHOICES) {
    if (c.id === id) {
      return c.label;
    }
  }
  return 'Everyday';
}

/** Chooser glyph per profile (prototype: elderly, child_care, visibility_off, person). */
function choiceGlyph(id: string): Resource {
  switch (id) {
    case 'senior':
      return $r('sys.symbol.figure_walk');
    case 'kid':
      return $r('sys.symbol.face_smiling_fill');
    case 'lowvision':
      return $r('sys.symbol.eye_slash');
    default:
      return $r('sys.symbol.person_fill');
  }
}

/** One tile inside MiniHome, with its precomputed geometry. */
class MiniTile {
  key: string = '';
  tile: TileSpec = new TileSpec();
  w: number = 0;
  h: number = 0;
  index: number = 0;
}

/**
 * Small, live picture of a generated home (caregiver before/after). Renders the real TileSpecs with the profile's
 * columns, Living Light gradients, text scale and the app dock, so every adaptation is visible at a glance.
 */
@Component
export struct MiniHome {
  @Prop tiles: TileSpec[] = [];
  @Prop profile: Profile = new Profile();
  @Prop dark: boolean = false;
  @Prop appsHidden: boolean = false;
  /** Show only the first `reveal` tiles (building animation); -1 = all. */
  @Prop reveal: number = -1;
  /** Tile id to outline (the tile a suggestion changes). */
  @Prop highlight: string = '';
  @Prop maxTiles: number = 6;
  @Prop frameWidth: number = 160;

  private items(): MiniTile[] {
    const cols: number = Math.max(1, Math.min(4, this.profile.columns));
    const gap: number = 4;
    // frame padding 6+6, border 1+1; every tile carries a 4 vp right margin.
    const inner: number = this.frameWidth - 14;
    const cellW: number = (inner - gap * cols) / cols;
    const baseH: number = cols <= 2 ? cellW * 0.42 : cellW * 0.9;
    const out: MiniTile[] = [];
    const n: number = Math.min(this.tiles.length, this.maxTiles);
    for (let i = 0; i < n; i++) {
      const t: TileSpec = this.tiles[i];
      const span: number = TilesTheme.colSpan(t.size, cols);
      const rows: number = TilesTheme.rowSpan(t.size);
      const m: MiniTile = new MiniTile();
      m.key = t.id + '|' + t.size + '|' + i.toString();
      m.tile = t;
      m.w = span * cellW + (span - 1) * gap - 0.3;
      m.h = rows * baseH + (rows - 1) * gap;
      m.index = i;
      out.push(m);
    }
    return out;
  }

  private pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }

  private miniBorder(m: MiniTile): BorderOptions {
    if (this.highlight === m.tile.id) {
      const hl: BorderOptions = { width: 2, color: this.pal().accent, style: BorderStyle.Dashed };
      return hl;
    }
    const o: BorderOptions = {
      width: this.profile.highContrast ? 1 : 0,
      color: TilesTheme.tile(m.tile.color, this.profile.highContrast, this.dark).border
    };
    return o;
  }

  build() {
    Column({ space: 5 }) {
      // Status line: greeting + read-aloud indicator.
      Row({ space: 4 }) {
        Text('Hi, ' + (this.profile.name.length > 0 ? this.profile.name : 'there'))
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(Math.round(9 * this.profile.textScale))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().text)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
        if (this.profile.readAloud) {
          SymbolGlyph($r('sys.symbol.speaker_wave_2_fill'))
            .fontSize(10)
            .fontColor([this.pal().text])
        }
      }
      .width('100%')
      .padding({ left: 2, right: 2 })

      Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.Start }) {
        ForEach(this.items(), (m: MiniTile) => {
          if (this.reveal < 0 || m.index < this.reveal) {
            this.miniTile(m)
          }
        }, (m: MiniTile) => m.key)
      }
      .width('100%')

      if (!this.appsHidden) {
        Row({ space: 5 }) {
          ForEach([0, 1, 2, 3, 4], (i: number) => {
            Column()
              .width(13)
              .height(13)
              .borderRadius(4)
              .backgroundColor(this.pal().surface2)
          }, (i: number) => 'dock' + i.toString())
        }
        .justifyContent(FlexAlign.Center)
        .width('100%')
        .padding({ top: 2 })
      }
    }
    .width(this.frameWidth)
    .padding(6)
    .borderRadius(18)
    .linearGradient({ angle: this.pal().bgGradient.angle, colors: this.pal().bgGradient.colors })
    .border({ width: 1, color: this.pal().line })
    .shadow(TilesTheme.LL_SHADOW_SOFT)
    .clip(true)
    .accessibilityText('Preview of ' + this.profile.name + '\'s home with ' +
      Math.min(this.tiles.length, this.maxTiles).toString() + ' tiles')
  }

  @Builder
  miniTile(m: MiniTile) {
    // Short, wide tiles (2-column homes) put the icon next to the title; tall tiles stack them.
    Flex({
      direction: m.h < 44 && m.w > m.h * 1.6 ? FlexDirection.Row : FlexDirection.Column,
      alignItems: m.h < 44 && m.w > m.h * 1.6 ? ItemAlign.Center : ItemAlign.Start,
      justifyContent: FlexAlign.Start
    }) {
      SymbolGlyph(tileIcon(m.tile.icon, m.tile.type))
        .fontSize(Math.round(10 * this.profile.textScale))
        .fontColor([TilesTheme.tile(m.tile.color, this.profile.highContrast, this.dark).on])
        .margin({ right: 3, bottom: 2 })
      Text(m.tile.title)
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(Math.max(6, Math.round(7 * this.profile.textScale)))
        .fontWeight(FontWeight.Bold)
        .fontColor(TilesTheme.tile(m.tile.color, this.profile.highContrast, this.dark).on)
        .maxLines(m.h > 40 ? 2 : 1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .flexShrink(1)
    }
    .padding(4)
    .clip(true)
    .width(m.w)
    .height(m.h)
    .margin({ right: 4, bottom: 4 })
    .borderRadius(m.tile.size === '2x2' ? 10 : 8)
    .linearGradient({
      angle: 135,
      colors: TilesTheme.tile(m.tile.color, this.profile.highContrast, this.dark).gradient.colors
    })
    .border(this.miniBorder(m))
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.scale({ x: 0.92, y: 0.92 }))
      .animation({ curve: TilesTheme.ease(), duration: TilesTheme.LL_DUR }))
  }
}

/** Replaces every occurrence of `from` with `to` in a tile's user-visible strings (caregiver personalization). */
function personalize(t: TileSpec, from: string, to: string): TileSpec {
  const r = (v: string): string => v.split(from).join(to);
  const c: TileSpec = cloneTile(t);
  c.title = r(c.title);
  c.subtitle = r(c.subtitle);
  c.speakText = r(c.speakText);
  for (const b of c.blocks) {
    const blk: TileBlock = b;
    blk.text = r(blk.text);
    blk.value = r(blk.value);
    blk.items = blk.items.map((x: string) => r(x));
    for (const a of blk.actions) {
      const act: TileAction = a;
      act.label = r(act.label);
      act.arg = r(act.arg);
    }
  }
  return c;
}

function tileMentions(t: TileSpec, s: string): boolean {
  return JSON.stringify(t).indexOf(s) >= 0;
}

/** Chooser card geometry (prototype: min-height 96, gap 12, side padding 20). */
const CARD_H: number = 96;
const CARD_GAP: number = 12;
const STAGE_PAD_X: number = 20;
const STAGE_TOP: number = 24;
const MAX_SLOTS: number = 8;

/** Rect of one grid tile (prototype layout()). */
class GridRect {
  x: number = 0;
  y: number = 0;
  w: number = 0;
  h: number = 0;
}

/**
 * One morphing slot. Slots 0..3 start life as the four chooser cards; on choosing, every slot resizes, recolors and
 * reflows into a tile of the new home (the chosen card becomes the first tile). Slots 4+ enter from
 * scale(.92) translateY(22) with the Living Light curve.
 */
class Slot {
  key: string = '';
  index: number = 0;
  card: ChoiceDef | undefined = undefined;
  tile: TileSpec | undefined = undefined;
  x: number = 0;
  y: number = 0;
  w: number = 0;
  h: number = 0;
  /** Tile geometry (fixed so the tile content does not reflow while the slot morphs). */
  tw: number = 0;
  th: number = 0;
  visible: boolean = true;
  delay: number = 0;
}

/**
 * Onboarding (route 'onboarding'), Living Light direction C: "Who is this phone for?" with the four ICPS cards.
 * Tapping a card commits the profile + seed tiles and plays the signature MORPH: the cards resize, recolor and
 * reflow into the person's generated home (staggered, cubic-bezier(.22,1,.36,1), 720 ms), then hands over to Home.
 * "Personalize first" opens the name + caregiver step, whose Build button plays the same morph.
 */
@Component
export struct OnboardingView {
  @Consume('tilesNav') nav: NavPathStack;
  @StorageProp('tiles.dark') dark: boolean = false;
  @StorageProp(K_REDUCE_MOTION) reduceMotionPref: boolean = false;
  @State step: number = 0;
  @State selected: string = 'senior';
  @State nameDraft: string = 'Halina';
  @State caregiverDraft: string = 'Kasia';
  @State roleDraft: string = 'daughter';
  @State buildLine: string = '';
  @State buildDone: boolean = false;
  /** false = chooser layout, true = home layout (drives every slot's implicit animation). */
  @State morph: boolean = false;
  @State pressed: string = '';
  @State stageW: number = 360;
  @State stageH: number = 760;
  @State chooserHeadH: number = 150;
  @State greetHeadH: number = 170;
  @State buildTiles: TileSpec[] = [];
  @State buildProfile: Profile = new Profile();
  private timers: number[] = [];
  private busy: boolean = false;

  aboutToAppear(): void {
    const cur: Profile = TileStore.get().profile();
    this.pick(TileStore.get().isOnboarded() ? cur.id : 'senior');
  }

  aboutToDisappear(): void {
    for (const t of this.timers) {
      clearTimeout(t);
    }
    this.timers = [];
  }

  private pal(): ThemePalette {
    return TilesTheme.palette(this.dark, false);
  }

  private ty(): TypeScale {
    return TilesTheme.type(1.0);
  }

  private pick(id: string): void {
    const p: Profile = profileFor(id);
    this.selected = id;
    this.nameDraft = p.name;
    this.caregiverDraft = p.caregiver;
    this.roleDraft = p.caregiverRole;
  }

  private choice(): ChoiceDef {
    for (const c of PROFILE_CHOICES) {
      if (c.id === this.selected) {
        return c;
      }
    }
    return PROFILE_CHOICES[3];
  }

  private reduced(): boolean {
    return this.reduceMotionPref || TilesTheme.layoutForId(this.selected).reducedMotion;
  }

  // ---------- commit + morph ----------

  /** Card tap: press feedback, then commit with the profile defaults and morph. */
  private chooseCard(id: string): void {
    if (this.busy) {
      return;
    }
    this.busy = true;
    this.pick(id);
    this.getUIContext().animateTo({ duration: 250, curve: TilesTheme.ease() }, () => {
      this.pressed = id;
    });
    this.timers.push(setTimeout(() => this.commit(), 180));
  }

  /** Commits the profile + a fresh seeded home, then plays the morph and returns to Home. */
  private commit(): void {
    this.busy = true;
    const st: TileStore = TileStore.get();
    const def: Profile = profileFor(this.selected);
    const p: Profile = profileFor(this.selected);
    const name: string = this.nameDraft.trim();
    const cg: string = this.caregiverDraft.trim();
    p.name = name.length > 0 ? name : def.name;
    p.caregiver = cg;
    p.caregiverRole = cg.length > 0 ? this.roleDraft.trim() : '';
    st.setProfile(p);
    st.resetToSeed();
    if (def.caregiver.length > 0 && cg.length > 0 && cg !== def.caregiver) {
      for (const t of st.tiles()) {
        if (tileMentions(t, def.caregiver)) {
          st.updateTile(personalize(t, def.caregiver, cg));
        }
      }
    }
    st.setOnboarded(true);

    // Mount the new slots in their "from" state (chooser layout), then release to the home layout next frame.
    this.buildProfile = p;
    this.buildTiles = st.tiles().slice(0, MAX_SLOTS);
    this.buildDone = false;
    this.morph = false;
    this.step = 2;
    const lines: string[] = this.buildLines(p);
    this.buildLine = lines[0];
    this.timers.push(setTimeout(() => {
      this.pressed = '';
      this.morph = true;
    }, 60));
    const n: number = this.buildTiles.length;
    for (let i = 1; i < lines.length; i++) {
      this.timers.push(setTimeout(() => {
        this.buildLine = lines[i];
      }, 60 + i * 260));
    }
    const settle: number = 60 + TilesTheme.LL_DUR + n * 45;
    this.timers.push(setTimeout(() => {
      this.buildDone = true;
      this.buildLine = p.name + '\'s home is ready';
    }, Math.max(settle, 60 + lines.length * 260)));
    this.timers.push(setTimeout(() => {
      this.nav.clear(false);
    }, Math.max(settle, 60 + lines.length * 260) + 900));
  }

  private buildLines(p: Profile): string[] {
    const out: string[] = ['Choosing ' + (p.columns <= 2 ? 'big, simple tiles' : 'a dense, colorful grid')];
    out.push(p.textScale >= 1.3 ? 'Making text ' + Math.round((p.textScale - 1) * 100).toString() + '% bigger' :
      'Setting comfortable text');
    out.push(p.readAloud ? 'Turning on read aloud' : 'Adding your plans');
    out.push(p.caregiver.length > 0 ? p.caregiver + ' will approve new tiles' : 'You approve new tiles yourself');
    return out;
  }

  // ---------- geometry ----------

  /** Grid metrics for the chosen person (prototype PROFILES; 4-column homes use the dense Daniel grid). */
  private grid(): ProfileLayout {
    return TilesTheme.layoutForId(this.selected);
  }

  /** Same greeting Home shows (time-aware, Polish vocative for the seeded people). */
  private greeting(): string {
    const h: number = new Date().getHours();
    const raw: string = this.buildProfile.name.length > 0 ? this.buildProfile.name : this.nameDraft.trim();
    const name: string = raw.length > 0 ? raw : 'friend';
    if (this.selected === 'kid') {
      return 'Hej, ' + name + '!';
    }
    if (this.selected === 'senior' || this.selected === 'lowvision') {
      const voc: string = name === 'Halina' ? 'Halino' : (name === 'Michał' ? 'Michale' : name);
      return (h >= 18 || h < 4 ? 'Dobry wieczór, ' : 'Dzień dobry, ') + voc;
    }
    const part: string = h >= 4 && h < 12 ? 'Morning' : (h >= 12 && h < 18 ? 'Afternoon' : 'Evening');
    return part + ', ' + name;
  }

  private greetSize(): number {
    return Math.max(22, Math.round(24 * Math.min(this.grid().fs, 1.2)));
  }

  /** Prototype layout(): first-fit placement of 'WxH' sizes on a `cols` grid (Home uses the same spans). */
  private layout(tiles: TileSpec[], g: ProfileLayout, top: number): GridRect[] {
    const cols: number = g.cols;
    const cellW: number = Math.floor((this.stageW - 2 * g.pad - (cols - 1) * g.gap) / cols);
    const occ: boolean[][] = [];
    const out: GridRect[] = [];
    for (const t of tiles) {
      const cw: number = TilesTheme.colSpan(t.size, cols);
      const ch: number = TilesTheme.rowSpan(t.size);
      let placed: boolean = false;
      for (let r = 0; !placed && r < 60; r++) {
        for (let c = 0; c <= cols - cw && !placed; c++) {
          let ok: boolean = true;
          for (let i = 0; i < ch && ok; i++) {
            for (let j = 0; j < cw && ok; j++) {
              const row: boolean[] | undefined = occ[r + i];
              if (row !== undefined && row[c + j] === true) {
                ok = false;
              }
            }
          }
          if (ok) {
            for (let i = 0; i < ch; i++) {
              if (occ[r + i] === undefined) {
                occ[r + i] = [];
              }
              for (let j = 0; j < cw; j++) {
                occ[r + i][c + j] = true;
              }
            }
            const rect: GridRect = new GridRect();
            rect.x = g.pad + c * (cellW + g.gap);
            rect.y = top + r * (g.rowH + g.gap);
            rect.w = cw * cellW + (cw - 1) * g.gap;
            rect.h = ch * g.rowH + (ch - 1) * g.gap;
            out.push(rect);
            placed = true;
          }
        }
      }
    }
    return out;
  }

  private cardTop(i: number): number {
    return STAGE_TOP + this.chooserHeadH + 8 + i * (CARD_H + CARD_GAP);
  }

  private slots(): Slot[] {
    const g: ProfileLayout = this.grid();
    const tiles: TileSpec[] = this.buildTiles;
    const rects: GridRect[] = this.layout(tiles, g, 10 + this.greetHeadH);
    // The chosen card becomes tile 0; the other cards follow in order.
    const rank: number[] = [];
    let next: number = 1;
    for (let i = 0; i < PROFILE_CHOICES.length; i++) {
      if (PROFILE_CHOICES[i].id === this.selected && tiles.length > 0) {
        rank.push(0);
      } else {
        rank.push(next);
        next++;
      }
    }
    const n: number = Math.max(PROFILE_CHOICES.length, Math.min(MAX_SLOTS, tiles.length));
    const out: Slot[] = [];
    for (let i = 0; i < n; i++) {
      const s: Slot = new Slot();
      s.index = i;
      s.key = 'slot' + i.toString();
      const ti: number = i < PROFILE_CHOICES.length ? rank[i] : i;
      s.tile = ti < tiles.length ? tiles[ti] : undefined;
      s.card = i < PROFILE_CHOICES.length ? PROFILE_CHOICES[i] : undefined;
      const target: GridRect | undefined = ti < rects.length ? rects[ti] : undefined;
      if (target !== undefined) {
        s.tw = target.w;
        s.th = target.h;
      }
      s.delay = this.reduced() ? 0 : ti * 45;
      if (this.morph) {
        if (target !== undefined) {
          s.x = target.x;
          s.y = target.y;
          s.w = target.w;
          s.h = target.h;
          s.visible = true;
        } else {
          // A card with no tile left: fade out where it is.
          s.x = STAGE_PAD_X;
          s.y = this.cardTop(i);
          s.w = this.stageW - 2 * STAGE_PAD_X;
          s.h = CARD_H;
          s.visible = false;
        }
      } else if (s.card !== undefined) {
        s.x = STAGE_PAD_X;
        s.y = this.cardTop(i);
        s.w = this.stageW - 2 * STAGE_PAD_X;
        s.h = CARD_H;
        s.visible = true;
      } else if (target !== undefined) {
        s.x = target.x;
        s.y = target.y;
        s.w = target.w;
        s.h = target.h;
        s.visible = false;
      }
      out.push(s);
    }
    return out;
  }

  private slotIndexes(): number[] {
    const n: number = Math.max(PROFILE_CHOICES.length, Math.min(MAX_SLOTS, this.buildTiles.length));
    const out: number[] = [];
    for (let i = 0; i < n; i++) {
      out.push(i);
    }
    return out;
  }

  private slotAt(i: number): Slot {
    const all: Slot[] = this.slots();
    return i < all.length ? all[i] : new Slot();
  }

  private slotScale(i: number): number {
    const sl: Slot = this.slotAt(i);
    if (!sl.visible) {
      return TilesTheme.LL_ENTER_SCALE;
    }
    const c: ChoiceDef | undefined = sl.card;
    return c !== undefined && this.pressed === c.id ? 0.97 : 1;
  }

  private slotLabel(i: number): string {
    const sl: Slot = this.slotAt(i);
    const c: ChoiceDef | undefined = sl.card;
    const t: TileSpec | undefined = sl.tile;
    if (c !== undefined && !this.morph) {
      return c.label + '. ' + c.line;
    }
    return t !== undefined ? t.title : '';
  }

  private dur(): number {
    return this.reduced() ? 150 : TilesTheme.LL_DUR;
  }

  private curve(): Curve | curves.ICurve {
    return this.reduced() ? Curve.Linear : TilesTheme.ease();
  }

  // ---------- build ----------

  build() {
    NavDestination() {
      Stack({ alignContent: Alignment.TopStart }) {
        // Living Light page gradient, drawn under the system bars too.
        Column()
          .width('100%')
          .height('100%')
          .linearGradient({ angle: this.pal().bgGradient.angle, colors: this.pal().bgGradient.colors })
          .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
        if (this.step === 1) {
          this.stepDetails()
        } else {
          this.stage()
        }
      }
      .width('100%')
      .height('100%')
      .onAreaChange((o: Area, n: Area) => {
        const w: number = Number(n.width);
        const h: number = Number(n.height);
        if (!isNaN(w) && Math.abs(w - this.stageW) > 1) {
          this.stageW = w;
        }
        if (!isNaN(h) && Math.abs(h - this.stageH) > 1) {
          this.stageH = h;
        }
      })
    }
    .hideTitleBar(true)
    .onBackPressed(() => {
      if (this.step === 1) {
        this.step = 0;
        return true;
      }
      return this.step === 2; // the morph finishes on its own
    })
  }

  // ---------- step 0 + 2: chooser that morphs into the home ----------

  @Builder
  stage() {
    Stack({ alignContent: Alignment.TopStart }) {
      // Chooser header (prototype: kicker · 34 px title · 16 px muted line).
      Column({ space: 12 }) {
        Text('TILES · SETUP')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(12)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(1.4)
          .fontColor(this.pal().muted)
        Text('Who is this phone for?')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(34)
          .maxFontSize(34)
          .minFontSize(24)
          .maxLines(1)
          .lineHeight(36)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(TilesTheme.letterSpacing(34) * 1.6)
          .fontColor(this.pal().ink)
          .width('100%')
          .accessibilityLevel('yes')
        Text('The home will shape itself around them. You can change it any time.')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(16)
          .lineHeight(22)
          .fontColor(this.pal().muted)
          .width('100%')
      }
      .alignItems(HorizontalAlign.Start)
      .width(this.stageW - 2 * STAGE_PAD_X)
      .position({ x: STAGE_PAD_X, y: STAGE_TOP })
      .opacity(this.morph ? 0 : 1)
      .translate({ y: this.morph ? -16 : 0 })
      .animation({ duration: this.reduced() ? 150 : 400, curve: this.curve() })
      .onAreaChange((o: Area, n: Area) => {
        const h: number = Number(n.height);
        if (!isNaN(h) && Math.abs(h - this.chooserHeadH) > 1 && !this.morph) {
          this.chooserHeadH = h;
        }
      })

      // Home header the cards grow under: mirrors HomeView.header() (kicker + person pills + greeting) so the
      // hand-over to Home lands on the same layout.
      Column({ space: 8 }) {
        Row({ space: 8 }) {
          Text('WHO IS THIS PHONE FOR?')
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(12)
            .fontWeight(FontWeight.Bold)
            .letterSpacing(1.44)
            .fontColor(this.pal().muted)
            .layoutWeight(1)
            .maxLines(1)
          this.glassDot($r('sys.symbol.person_2'))
          this.glassDot($r('sys.symbol.gearshape'))
        }
        .width('100%')

        Row({ space: 6 }) {
          ForEach(PROFILE_CHOICES, (c: ChoiceDef) => {
            Text(c.label)
              .fontFamily(LL_FONT_FAMILY)
              .fontSize(12.5)
              .fontWeight(FontWeight.Bold)
              .fontColor(c.id === this.selected ? this.pal().onInk : this.pal().ink)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .textAlign(TextAlign.Center)
              .layoutWeight(1)
              .height(44)
              .padding({ left: 4, right: 4 })
              .borderRadius(TilesTheme.LL_RADIUS_PILL)
              .backgroundColor(c.id === this.selected ? this.pal().ink : (this.dark ? Color.Transparent : '#66FFFFFF'))
              .border({ width: 1.5, color: c.id === this.selected ? this.pal().ink : this.pal().line })
          }, (c: ChoiceDef) => 'pill-' + c.id)
        }
        .width('100%')
        .margin({ bottom: 6 })

        Column({ space: 3 }) {
          Text(this.greeting())
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(this.greetSize())
            .lineHeight(Math.round(this.greetSize() * 1.1))
            .fontWeight(FontWeight.Bold)
            .letterSpacing(Math.round(this.greetSize() * -0.02 * 100) / 100)
            .fontColor(this.pal().ink)
            .maxLines(2)
          Row({ space: 6 }) {
            if (this.buildDone) {
              SymbolGlyph($r('sys.symbol.checkmark_circle_fill'))
                .fontSize(15)
                .fontColor([this.pal().ok])
                .transition(TransitionEffect.scale({ x: 0.4, y: 0.4 }).combine(TransitionEffect.OPACITY)
                  .animation({ duration: 300, curve: TilesTheme.ease() }))
            }
            Text(this.buildLine)
              .fontFamily(LL_FONT_FAMILY)
              .fontSize(15)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.buildDone ? this.pal().okInk : this.pal().muted)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .margin({ top: 4, bottom: 16 })
        .accessibilityGroup(true)
        .accessibilityText(this.greeting() + '. ' + this.buildLine)
      }
      .width(this.stageW - 2 * this.grid().pad)
      .position({ x: this.grid().pad, y: 10 })
      .opacity(this.morph ? 1 : 0)
      .translate({ y: this.morph ? 0 : 14 })
      .animation({ duration: this.dur(), curve: this.curve(), delay: this.reduced() ? 0 : 160 })
      .onAreaChange((o: Area, n: Area) => {
        const h: number = Number(n.height);
        if (!isNaN(h) && Math.abs(h - this.greetHeadH) > 1 && !this.morph) {
          this.greetHeadH = h;
        }
      })

      // Index-keyed so each slot persists across the morph; geometry is read from state (ForEach would not
      // re-render an item whose key is unchanged).
      ForEach(this.slotIndexes(), (i: number) => {
        this.slot(i)
      }, (i: number) => 'slot' + i.toString())

      // Secondary path: set the name and caregiver before building.
      Row({ space: 6 }) {
        SymbolGlyph($r('sys.symbol.person_2_fill'))
          .fontSize(18)
          .fontColor([this.pal().accent])
        Text('Personalize name and helper first')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(15)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().accent)
      }
      .height(48)
      .padding({ left: 16, right: 16 })
      .borderRadius(TilesTheme.LL_RADIUS_PILL)
      .backgroundColor(this.pal().surface)
      .backgroundBlurStyle(TilesTheme.LL_BLUR_STYLE)
      .position({ x: STAGE_PAD_X, y: this.cardTop(PROFILE_CHOICES.length) + 4 })
      .opacity(this.morph || this.step === 2 ? 0 : 1)
      .animation({ duration: 250, curve: this.curve() })
      .hitTestBehavior(this.step === 2 ? HitTestMode.None : HitTestMode.Default)
      .onClick(() => {
        if (!this.busy) {
          this.step = 1;
        }
      })
      .accessibilityText('Personalize name and helper first')
    }
    .width('100%')
    .height('100%')
    .clip(true)
  }

  @Builder
  slot(i: number) {
    Stack({ alignContent: Alignment.TopStart }) {
      if (this.slotAt(i).tile !== undefined) {
        this.tileFace(this.slotAt(i).tile as TileSpec, this.slotAt(i).tw, this.slotAt(i).th)
      }
      if (this.slotAt(i).card !== undefined) {
        this.cardFace(this.slotAt(i).card as ChoiceDef)
      }
    }
    .position({ x: this.slotAt(i).x, y: this.slotAt(i).y })
    .width(this.slotAt(i).w)
    .height(this.slotAt(i).h)
    .borderRadius(TilesTheme.LL_RADIUS_L)
    .clip(true)
    .shadow(TilesTheme.LL_SHADOW_TILE)
    .opacity(this.slotAt(i).visible ? 1 : 0)
    .scale({ x: this.slotScale(i), y: this.slotScale(i) })
    .translate({ y: this.slotAt(i).visible ? 0 : TilesTheme.LL_ENTER_TY })
    .animation({ duration: this.morph ? this.dur() : 250, curve: this.curve(), delay: this.morph ? this.slotAt(i).delay : 0 })
    .hitTestBehavior(this.step === 0 && this.slotAt(i).card !== undefined ? HitTestMode.Default : HitTestMode.None)
    .onClick(() => {
      if (this.step === 0 && this.slotAt(i).card !== undefined) {
        this.chooseCard((this.slotAt(i).card as ChoiceDef).id);
      }
    })
    .accessibilityText(this.slotLabel(i))
  }

  @Builder
  glassDot(icon: Resource) {
    Row() {
      SymbolGlyph(icon)
        .fontSize(20)
        .fontColor([this.pal().ink])
    }
    .width(40)
    .height(40)
    .justifyContent(FlexAlign.Center)
    .borderRadius(20)
    .backgroundColor(this.pal().surface)
    .backdropBlur(TilesTheme.LL_BLUR)
    .shadow(TilesTheme.LL_SHADOW_SOFT)
  }

  /** Chooser card face (prototype: 34 px icon · 22 px label · 15 px sub at .85 · arrow). */
  @Builder
  cardFace(c: ChoiceDef) {
    Row({ space: 16 }) {
      SymbolGlyph(choiceGlyph(c.id))
        .fontSize(34)
        .fontColor([TilesTheme.tile(c.color, false, this.dark).on])
      Column({ space: 3 }) {
        Text(c.label)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(22)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(TilesTheme.letterSpacing(22))
          .fontColor(TilesTheme.tile(c.color, false, this.dark).on)
        Text(c.line)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(15)
          .lineHeight(19)
          .fontColor(TilesTheme.tile(c.color, false, this.dark).on)
          .opacity(0.85)
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      SymbolGlyph($r('sys.symbol.arrow_right'))
        .fontSize(24)
        .fontColor([TilesTheme.tile(c.color, false, this.dark).on])
    }
    .width(this.stageW - 2 * STAGE_PAD_X)
    .height(CARD_H)
    .padding({ left: 18, right: 18, top: 16, bottom: 16 })
    .linearGradient({ angle: 135, colors: TilesTheme.tile(c.color, false, this.dark).gradient.colors })
    .opacity(this.morph ? 0 : 1)
    .animation({ duration: this.reduced() ? 150 : Math.round(TilesTheme.LL_DUR * 0.6), curve: Curve.EaseOut })
  }

  /** Tile face at its final size (prototype tile head: icon + title + one body line). */
  @Builder
  tileFace(t: TileSpec, w: number, h: number) {
    Column({ space: w < 120 ? 4 : 8 }) {
      SymbolGlyph(tileIcon(t.icon, t.type))
        .fontSize(Math.round(24 * this.grid().fs * (w < 120 ? 0.85 : 1)))
        .fontColor([this.tileColors(t).on])
      Text(t.title)
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(Math.round(19 * this.grid().fs * (w < 120 ? 0.82 : 1)))
        .fontWeight(FontWeight.Bold)
        .letterSpacing(TilesTheme.letterSpacing(19))
        .fontColor(this.tileColors(t).on)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      if (t.subtitle.length > 0 && h >= 100) {
        Text(t.subtitle)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(Math.round(14 * this.grid().fs * (w < 120 ? 0.9 : 1)))
          .fontColor(this.tileColors(t).on)
          .opacity(0.85)
          .maxLines(h < 120 ? 1 : 2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width(Math.max(1, w))
    .height(Math.max(1, h))
    .padding(w < 120 ? 10 : this.grid().pad)
    .linearGradient({ angle: 135, colors: this.tileColors(t).gradient.colors })
  }

  private tileColors(t: TileSpec): TileColors {
    return TilesTheme.tile(t.color, false, this.dark);
  }

  // ---------- step 1: details (glass) ----------

  @Builder
  stepDetails() {
    Column() {
      Scroll() {
        Column({ space: 14 }) {
          Row({ space: 10 }) {
            Row() {
              SymbolGlyph($r('sys.symbol.chevron_left'))
                .fontSize(22)
                .fontColor([this.pal().ink])
            }
            .width(48)
            .height(48)
            .justifyContent(FlexAlign.Center)
            .borderRadius(24)
            .backgroundColor(this.pal().surface)
            .backgroundBlurStyle(TilesTheme.LL_BLUR_STYLE)
            .shadow(TilesTheme.LL_SHADOW_SOFT)
            .onClick(() => {
              this.step = 0;
            })
            .accessibilityText('Back')

            Text('TILES · SETUP')
              .fontFamily(LL_FONT_FAMILY)
              .fontSize(12)
              .fontWeight(FontWeight.Bold)
              .letterSpacing(1.4)
              .fontColor(this.pal().muted)
          }
          .width('100%')

          Text(this.selected === 'everyday' ? 'Make it yours' : 'Who uses it, and who helps?')
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(30)
            .lineHeight(33)
            .fontWeight(FontWeight.Bold)
            .letterSpacing(TilesTheme.letterSpacing(30) * 1.6)
            .fontColor(this.pal().ink)
            .width('100%')

          // Prototype switcher: "WHO IS THIS PHONE FOR?" + four pills (ink when selected).
          Column({ space: 8 }) {
            Text('WHO IS THIS PHONE FOR?')
              .fontFamily(LL_FONT_FAMILY)
              .fontSize(12)
              .fontWeight(FontWeight.Bold)
              .letterSpacing(1.4)
              .fontColor(this.pal().muted)
            Row({ space: 6 }) {
              ForEach(PROFILE_CHOICES, (c: ChoiceDef) => {
                Text(c.label)
                  .fontFamily(LL_FONT_FAMILY)
                  .fontSize(12.5)
                  .fontWeight(FontWeight.Bold)
                  .fontColor(this.selected === c.id ? this.pal().onInk : this.pal().ink)
                  .textAlign(TextAlign.Center)
                  .maxLines(1)
                  .textOverflow({ overflow: TextOverflow.Ellipsis })
                  .layoutWeight(1)
                  .height(44)
                  .borderRadius(TilesTheme.LL_RADIUS_PILL)
                  .border({ width: 1.5, color: this.selected === c.id ? this.pal().ink : this.pal().line })
                  .backgroundColor(this.selected === c.id ? this.pal().ink : '#00FFFFFF')
                  .animation({ duration: 300, curve: TilesTheme.ease() })
                  .onClick(() => this.pick(c.id))
                  .accessibilityText(c.label + (this.selected === c.id ? ', selected' : ''))
              }, (c: ChoiceDef) => c.id)
            }
            .width('100%')
          }
          .alignItems(HorizontalAlign.Start)
          .width('100%')

          this.field('Name', 'e.g. Halina', this.nameDraft, (v: string) => {
            this.nameDraft = v;
          })

          Column({ space: 8 }) {
            Text(this.selected === 'everyday' ? 'Someone who reviews changes (optional)' :
              'Caregiver who approves changes')
              .fontFamily(LL_FONT_FAMILY)
              .fontSize(15)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.pal().ink)
            Row({ space: 8 }) {
              TextInput({ text: this.caregiverDraft, placeholder: 'Name, e.g. Kasia' })
                .onChange((v: string) => {
                  this.caregiverDraft = v;
                })
                .fontFamily(LL_FONT_FAMILY)
                .fontSize(17)
                .fontColor(this.pal().ink)
                .placeholderColor(this.pal().muted)
                .backgroundColor(this.pal().surface)
                .borderRadius(TilesTheme.LL_RADIUS_M)
                .height(56)
                .layoutWeight(3)
              TextInput({ text: this.roleDraft, placeholder: 'daughter' })
                .onChange((v: string) => {
                  this.roleDraft = v;
                })
                .fontFamily(LL_FONT_FAMILY)
                .fontSize(17)
                .fontColor(this.pal().ink)
                .placeholderColor(this.pal().muted)
                .backgroundColor(this.pal().surface)
                .borderRadius(TilesTheme.LL_RADIUS_M)
                .height(56)
                .layoutWeight(2)
            }
            .width('100%')
          }
          .alignItems(HorizontalAlign.Start)
          .width('100%')

          // Glass info card.
          Row({ space: 12 }) {
            Row() {
              SymbolGlyph($r('sys.symbol.person_2_fill'))
                .fontSize(20)
                .fontColor([TilesTheme.tile(this.choice().color, false, this.dark).on])
            }
            .width(40)
            .height(40)
            .justifyContent(FlexAlign.Center)
            .borderRadius(20)
            .linearGradient({ angle: 135, colors: TilesTheme.tile(this.choice().color, false, this.dark).gradient.colors })
            Text(this.caregiverDraft.trim().length > 0 ?
              this.caregiverDraft.trim() + ' gets new tiles and suggested changes on their phone and approves them ' +
                'before anything changes here.' :
              'No caregiver: new tiles and suggested changes are approved on this phone.')
              .fontFamily(LL_FONT_FAMILY)
              .fontSize(15)
              .lineHeight(20)
              .fontColor(this.pal().muted)
              .layoutWeight(1)
          }
          .alignItems(VerticalAlign.Top)
          .width('100%')
          .padding(16)
          .borderRadius(TilesTheme.LL_RADIUS_M)
          .backgroundColor(this.pal().surface)
          .backgroundBlurStyle(TilesTheme.LL_BLUR_STYLE)
          .shadow(TilesTheme.LL_SHADOW_SOFT)
        }
        .padding({ left: STAGE_PAD_X, right: STAGE_PAD_X, top: STAGE_TOP, bottom: 120 })
      }
      .scrollBar(BarState.Off)
      .width('100%')
      .height('100%')
      .align(Alignment.Top)
    }
    .width('100%')
    .height('100%')

    this.bottomBar('Build ' + (this.nameDraft.trim().length > 0 ? this.nameDraft.trim() + '\'s' : 'my') + ' home',
      () => {
        if (!this.busy) {
          this.commit();
        }
      })
  }

  @Builder
  field(label: string, placeholder: string, value: string, onChange: (v: string) => void) {
    Column({ space: 8 }) {
      Text(label)
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(15)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().ink)
      TextInput({ text: value, placeholder: placeholder })
        .onChange((v: string) => onChange(v))
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(17)
        .fontColor(this.pal().ink)
        .placeholderColor(this.pal().muted)
        .backgroundColor(this.pal().surface)
        .borderRadius(TilesTheme.LL_RADIUS_M)
        .height(56)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  /** Ink pill CTA (prototype cgCall / Done buttons). */
  @Builder
  bottomBar(label: string, onTap: () => void) {
    Column() {
      Row({ space: 10 }) {
        SymbolGlyph($r('sys.symbol.wand_and_stars_fill'))
          .fontSize(22)
          .fontColor([this.pal().onInk])
        Text(label)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(17)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().onInk)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .justifyContent(FlexAlign.Center)
      .width('100%')
      .height(60)
      .borderRadius(TilesTheme.LL_RADIUS_PILL)
      .backgroundColor(this.pal().ink)
      .shadow(TilesTheme.LL_SHADOW_SHEET)
      .onClick(onTap)
      .accessibilityText(label)
    }
    .width('100%')
    .position({ x: 0, y: this.stageH - 96 })
    .padding({ left: 16, right: 16, top: 6, bottom: 30 })
    .linearGradient({
      angle: 180,
      colors: [[withAlpha(this.pal().dark ? '#14162A' : '#FFF3EA', 0), 0.0],
        [withAlpha(this.pal().dark ? '#14162A' : '#FFF3EA', 0.9), 0.5]]
    })
  }
}
