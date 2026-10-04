import { Profile, TileAction, TileBlock, TileSpec } from '../model/Tile';
import { TileStore, cloneTile } from '../data/TileStore';
import { profileFor, seedTilesFor } from '../data/SeedTiles';
import { TilesTheme, ThemePalette, TileColors, TypeScale } from '../theme/TilesTheme';
import { tileIcon } from '../components/blocks/BlockStyle';

/** One "Who is this phone for?" choice. */
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

export const PROFILE_CHOICES: ChoiceDef[] = [
  new ChoiceDef('senior', 'Senior', 'Big tiles · read aloud · scam shield', 'coral', 'heart'),
  new ChoiceDef('kid', 'Kid', 'Homework · focus timer · screen time', 'sun', 'star'),
  new ChoiceDef('lowvision', 'Low vision', 'Voice first · extra-large · high contrast', 'grape', 'speaker'),
  new ChoiceDef('everyday', 'Everyday', 'Plans with friends · focus · commute', 'sky', 'sparkle')
];

export function choiceLabel(id: string): string {
  for (const c of PROFILE_CHOICES) {
    if (c.id === id) {
      return c.label;
    }
  }
  return 'Everyday';
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
 * Small, live picture of a generated home (profile picker preview, caregiver before/after). Renders the real
 * TileSpecs with the profile's columns, colors (incl. high contrast), text scale and the app dock, so every
 * adaptation (bigger text, wider tile, tile moved, apps hidden, read aloud) is visible at a glance.
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
    // frame padding 6+6, border 2+2; every tile carries a 4 vp right margin.
    const inner: number = this.frameWidth - 16;
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

  private miniBorder(m: MiniTile): BorderOptions {
    if (this.highlight === m.tile.id) {
      const hl: BorderOptions = { width: 2, color: '#FF2D55', style: BorderStyle.Dashed };
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
          .fontSize(Math.round(9 * this.profile.textScale))
          .fontWeight(FontWeight.Bold)
          .fontColor(TilesTheme.palette(this.dark, this.profile.highContrast).text)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
        if (this.profile.readAloud) {
          SymbolGlyph($r('sys.symbol.speaker_wave_2_fill'))
            .fontSize(10)
            .fontColor([TilesTheme.palette(this.dark, this.profile.highContrast).text])
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
              .backgroundColor(TilesTheme.palette(this.dark, false).border)
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
    .backgroundColor(TilesTheme.palette(this.dark, this.profile.highContrast).bg)
    .border({ width: 2, color: TilesTheme.palette(this.dark, false).text })
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
    .borderRadius(m.tile.size === '2x2' ? 9 : 7)
    .backgroundColor(TilesTheme.tile(m.tile.color, this.profile.highContrast, this.dark).bg)
    .border(this.miniBorder(m))
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.scale({ x: 0.6, y: 0.6 }))
      .animation({ curve: TilesTheme.springIn() }))
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

/**
 * Onboarding (route 'onboarding'): "Who is this phone for?" → four big choices with a live mini-preview of the
 * generated home → name + caregiver → "Building <name>'s home" (tiles spring in) → TileStore.setProfile + seed
 * tiles, then back to Home.
 */
@Component
export struct OnboardingView {
  @Consume('tilesNav') nav: NavPathStack;
  @StorageProp('tiles.dark') dark: boolean = false;
  @State step: number = 0;
  @State selected: string = 'senior';
  @State nameDraft: string = 'Halina';
  @State caregiverDraft: string = 'Kasia';
  @State roleDraft: string = 'daughter';
  @State reveal: number = 0;
  @State buildLine: string = '';
  @State buildDone: boolean = false;
  private timers: number[] = [];

  aboutToAppear(): void {
    const cur: Profile = TileStore.get().profile();
    if (TileStore.get().isOnboarded()) {
      this.pick(cur.id);
    } else {
      this.pick('senior');
    }
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
    this.getUIContext().animateTo({ duration: 300, curve: TilesTheme.springReflow() }, () => {
      this.selected = id;
    });
    this.nameDraft = p.name;
    this.caregiverDraft = p.caregiver;
    this.roleDraft = p.caregiverRole;
  }

  private previewProfile(): Profile {
    const p: Profile = profileFor(this.selected);
    if (this.step >= 1 && this.nameDraft.trim().length > 0) {
      p.name = this.nameDraft.trim();
    }
    return p;
  }

  private previewTiles(): TileSpec[] {
    const def: Profile = profileFor(this.selected);
    const cg: string = this.caregiverDraft.trim();
    const list: TileSpec[] = seedTilesFor(this.selected);
    if (def.caregiver.length === 0 || cg.length === 0 || cg === def.caregiver) {
      return list;
    }
    return list.map((t: TileSpec) => tileMentions(t, def.caregiver) ? personalize(t, def.caregiver, cg) : t);
  }

  /** Commits the profile + a fresh seeded home, then plays the build animation and returns to Home. */
  private commit(): void {
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

    this.step = 2;
    this.reveal = 0;
    this.buildDone = false;
    const lines: string[] = this.buildLines(p);
    const n: number = Math.min(6, st.tiles().length);
    this.buildLine = lines[0];
    for (let i = 1; i <= n; i++) {
      this.timers.push(setTimeout(() => {
        this.getUIContext().animateTo({ duration: 350, curve: TilesTheme.springIn() }, () => {
          this.reveal = i;
        });
        this.buildLine = lines[Math.min(lines.length - 1, i)];
      }, 250 + i * 260));
    }
    this.timers.push(setTimeout(() => {
      this.buildDone = true;
      this.buildLine = p.name + '\'s home is ready';
    }, 450 + (n + 1) * 260));
    this.timers.push(setTimeout(() => {
      this.nav.clear();
    }, 1500 + (n + 1) * 260));
  }

  private buildLines(p: Profile): string[] {
    const out: string[] = ['Choosing ' + (p.columns <= 2 ? 'big, simple tiles' : 'a colorful grid')];
    out.push(p.textScale >= 1.3 ? 'Making text ' + Math.round((p.textScale - 1) * 100).toString() + '% bigger' :
      'Setting comfortable text');
    out.push(p.highContrast ? 'Turning on high contrast' : 'Picking warm colors');
    out.push(p.readAloud ? 'Turning on read aloud' : 'Adding your plans');
    out.push(p.caregiver.length > 0 ? 'Adding Call ' + p.caregiver : 'Adding focus and commute');
    out.push(p.caregiver.length > 0 ? p.caregiver + ' will approve new tiles' : 'You approve new tiles yourself');
    out.push('Almost there');
    return out;
  }

  build() {
    NavDestination() {
      Stack({ alignContent: Alignment.Bottom }) {
        if (this.step === 0) {
          this.stepWho()
        } else if (this.step === 1) {
          this.stepDetails()
        } else {
          this.stepBuilding()
        }
      }
      .width('100%')
      .height('100%')
      .backgroundColor(this.step === 2 ?
        TilesTheme.tile(this.choice().color, false, this.dark).bg : this.pal().bg)
    }
    .hideTitleBar(true)
    .onBackPressed(() => {
      if (this.step === 1) {
        this.step = 0;
        return true;
      }
      return this.step === 2; // the build animation finishes on its own
    })
  }

  private choice(): ChoiceDef {
    for (const c of PROFILE_CHOICES) {
      if (c.id === this.selected) {
        return c;
      }
    }
    return PROFILE_CHOICES[3];
  }

  // ---------- step 0: who ----------

  @Builder
  stepWho() {
    Column() {
      Scroll() {
        Column({ space: TilesTheme.SPACE_L }) {
          Row({ space: 8 }) {
            SymbolGlyph($r('sys.symbol.square_fill_grid_2x2'))
              .fontSize(22)
              .fontColor([this.pal().text])
            Text('Tiles')
              .fontSize(20)
              .fontWeight(FontWeight.Bolder)
              .fontColor(this.pal().text)
              .layoutWeight(1)
            Text('Step 1 of 2')
              .fontSize(this.ty().caption)
              .fontColor(this.pal().textMuted)
          }
          .width('100%')

          Text('Who is this phone for?')
            .fontSize(32)
            .fontWeight(FontWeight.Bolder)
            .fontColor(this.pal().text)
            .width('100%')
            .accessibilityLevel('yes')
          Text('Tiles builds a different home for each person — and keeps adapting it. You can switch any time.')
            .fontSize(this.ty().body)
            .fontColor(this.pal().textMuted)
            .width('100%')

          Row({ space: TilesTheme.GRID_GAP }) {
            this.choiceCard(PROFILE_CHOICES[0])
            this.choiceCard(PROFILE_CHOICES[1])
          }
          .width('100%')

          Row({ space: TilesTheme.GRID_GAP }) {
            this.choiceCard(PROFILE_CHOICES[2])
            this.choiceCard(PROFILE_CHOICES[3])
          }
          .width('100%')

          Column({ space: TilesTheme.SPACE_S }) {
            Row({ space: 6 }) {
              Column()
                .width(8)
                .height(8)
                .borderRadius(4)
                .backgroundColor('#2ED3A0')
              Text('Live preview · ' + profileFor(this.selected).name + '\'s home')
                .fontSize(this.ty().label)
                .fontWeight(FontWeight.Medium)
                .fontColor(this.pal().textMuted)
            }

            MiniHome({
              tiles: this.previewTiles(),
              profile: this.previewProfile(),
              dark: this.dark,
              appsHidden: false,
              maxTiles: 6,
              frameWidth: 230
            })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Center)
          .padding({ top: TilesTheme.SPACE_S })
        }
        .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: 24, bottom: 120 })
      }
      .scrollBar(BarState.Off)
      .width('100%')
      .height('100%')
      .align(Alignment.Top)
    }
    .width('100%')
    .height('100%')

    this.bottomBar('Continue', () => {
      this.step = 1;
    }, '')
  }

  @Builder
  choiceCard(c: ChoiceDef) {
    Column({ space: 6 }) {
      Row() {
        SymbolGlyph(tileIcon(c.icon, ''))
          .fontSize(30)
          .fontColor([TilesTheme.tile(c.color, false, this.dark).on])
        Blank()
        if (this.selected === c.id) {
          SymbolGlyph($r('sys.symbol.checkmark_circle_fill'))
            .fontSize(24)
            .fontColor([TilesTheme.tile(c.color, false, this.dark).on])
            .transition(TransitionEffect.scale({ x: 0.3, y: 0.3 }).combine(TransitionEffect.OPACITY)
              .animation({ curve: TilesTheme.springPress() }))
        }
      }
      .width('100%')

      Blank()
      Text(c.label)
        .fontSize(22)
        .fontWeight(FontWeight.Bolder)
        .fontColor(TilesTheme.tile(c.color, false, this.dark).on)
      Text(c.line)
        .fontSize(13)
        .fontColor(TilesTheme.tile(c.color, false, this.dark).onMuted)
        .maxLines(2)
    }
    .alignItems(HorizontalAlign.Start)
    .layoutWeight(1)
    .height(150)
    .padding(14)
    .borderRadius(TilesTheme.RADIUS_TILE)
    .backgroundColor(TilesTheme.tile(c.color, false, this.dark).bg)
    .border({ width: this.selected === c.id ? 4 : 0, color: this.pal().text })
    .scale({ x: this.selected === c.id ? 1.0 : 0.96, y: this.selected === c.id ? 1.0 : 0.96 })
    .opacity(this.selected === c.id ? 1.0 : 0.82)
    .onClick(() => this.pick(c.id))
    .accessibilityText(c.label + '. ' + c.line + (this.selected === c.id ? '. Selected' : ''))
  }

  // ---------- step 1: details ----------

  @Builder
  stepDetails() {
    Column() {
      Scroll() {
        Column({ space: TilesTheme.SPACE_L }) {
          Row({ space: 8 }) {
            Row() {
              SymbolGlyph($r('sys.symbol.chevron_left'))
                .fontSize(24)
                .fontColor([this.pal().text])
            }
            .width(48)
            .height(48)
            .justifyContent(FlexAlign.Center)
            .borderRadius(24)
            .backgroundColor(this.pal().surface)
            .onClick(() => {
              this.step = 0;
            })
            .accessibilityText('Back')

            Text(this.choice().label)
              .fontSize(this.ty().label)
              .fontWeight(FontWeight.Bold)
              .fontColor(TilesTheme.tile(this.choice().color, false, this.dark).on)
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(999)
              .backgroundColor(TilesTheme.tile(this.choice().color, false, this.dark).bg)
            Blank()
            Text('Step 2 of 2')
              .fontSize(this.ty().caption)
              .fontColor(this.pal().textMuted)
          }
          .width('100%')

          Text(this.selected === 'everyday' ? 'Make it yours' : 'Who uses it, and who helps?')
            .fontSize(30)
            .fontWeight(FontWeight.Bolder)
            .fontColor(this.pal().text)
            .width('100%')

          this.field('Name', 'e.g. Halina', this.nameDraft, (v: string) => {
            this.nameDraft = v;
          })

          Column({ space: TilesTheme.SPACE_S }) {
            Text(this.selected === 'everyday' ? 'Someone who reviews changes (optional)' :
              'Caregiver who approves changes')
              .fontSize(this.ty().label)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.pal().text)
            Row({ space: TilesTheme.SPACE_S }) {
              TextInput({ text: this.caregiverDraft, placeholder: 'Name, e.g. Kasia' })
                .onChange((v: string) => {
                  this.caregiverDraft = v;
                })
                .fontSize(this.ty().body)
                .fontColor(this.pal().text)
                .placeholderColor(this.pal().textMuted)
                .backgroundColor(this.pal().surface)
                .borderRadius(TilesTheme.RADIUS_BUTTON)
                .height(56)
                .layoutWeight(3)
              TextInput({ text: this.roleDraft, placeholder: 'daughter' })
                .onChange((v: string) => {
                  this.roleDraft = v;
                })
                .fontSize(this.ty().body)
                .fontColor(this.pal().text)
                .placeholderColor(this.pal().textMuted)
                .backgroundColor(this.pal().surface)
                .borderRadius(TilesTheme.RADIUS_BUTTON)
                .height(56)
                .layoutWeight(2)
            }
            .width('100%')
          }
          .alignItems(HorizontalAlign.Start)
          .width('100%')

          Row({ space: 10 }) {
            SymbolGlyph($r('sys.symbol.person_2_fill'))
              .fontSize(22)
              .fontColor([this.pal().accent])
            Text(this.caregiverDraft.trim().length > 0 ?
              this.caregiverDraft.trim() + ' gets new tiles and suggested changes on their phone and approves them ' +
                'before anything changes here.' :
              'No caregiver: new tiles and suggested changes are approved on this phone.')
              .fontSize(this.ty().label)
              .fontColor(this.pal().textMuted)
              .layoutWeight(1)
          }
          .width('100%')
          .padding(TilesTheme.SPACE_L)
          .borderRadius(TilesTheme.RADIUS_INNER)
          .backgroundColor(this.pal().surfaceAlt)

          Column({ space: TilesTheme.SPACE_S }) {
            Text('Preview')
              .fontSize(this.ty().label)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.pal().textMuted)
            MiniHome({
              tiles: this.previewTiles(),
              profile: this.previewProfile(),
              dark: this.dark,
              appsHidden: false,
              maxTiles: 4,
              frameWidth: 210
            })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Center)
        }
        .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: 24, bottom: 120 })
      }
      .scrollBar(BarState.Off)
      .width('100%')
      .height('100%')
      .align(Alignment.Top)
    }
    .width('100%')
    .height('100%')

    this.bottomBar('Build ' + (this.nameDraft.trim().length > 0 ? this.nameDraft.trim() + '\'s' : 'my') + ' home',
      () => this.commit(), 'sparkle')
  }

  @Builder
  field(label: string, placeholder: string, value: string, onChange: (v: string) => void) {
    Column({ space: TilesTheme.SPACE_S }) {
      Text(label)
        .fontSize(this.ty().label)
        .fontWeight(FontWeight.Medium)
        .fontColor(this.pal().text)
      TextInput({ text: value, placeholder: placeholder })
        .onChange((v: string) => onChange(v))
        .fontSize(this.ty().body)
        .fontColor(this.pal().text)
        .placeholderColor(this.pal().textMuted)
        .backgroundColor(this.pal().surface)
        .borderRadius(TilesTheme.RADIUS_BUTTON)
        .height(56)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  @Builder
  bottomBar(label: string, onTap: () => void, icon: string) {
    Column() {
      Row({ space: 10 }) {
        if (icon.length > 0) {
          SymbolGlyph(tileIcon(icon, ''))
            .fontSize(22)
            .fontColor([this.pal().dark ? '#1C2230' : '#FFFFFF'])
        }
        Text(label)
          .fontSize(19)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().dark ? '#1C2230' : '#FFFFFF')
      }
      .justifyContent(FlexAlign.Center)
      .width('100%')
      .height(64)
      .borderRadius(32)
      .backgroundColor(this.pal().text)
      .onClick(onTap)
      .accessibilityText(label)
    }
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: 12, bottom: 24 })
    .linearGradient({
      angle: 0,
      colors: [[this.pal().bg, 0.6], [this.pal().dark ? '#0014161C' : '#00F6F3EE', 1.0]]
    })
  }

  // ---------- step 2: building ----------

  @Builder
  stepBuilding() {
    Column({ space: 28 }) {
      Blank()
      Column({ space: 10 }) {
        Text(this.buildDone ? 'Ready!' : 'Building ' + this.previewProfile().name + '\'s home…')
          .fontSize(30)
          .fontWeight(FontWeight.Bolder)
          .fontColor(TilesTheme.tile(this.choice().color, false, this.dark).on)
          .textAlign(TextAlign.Center)
        Text(this.buildLine)
          .fontSize(17)
          .fontColor(TilesTheme.tile(this.choice().color, false, this.dark).onMuted)
          .textAlign(TextAlign.Center)
          .height(26)
      }

      Column() {
        MiniHome({
          tiles: TileStore.get().tiles(),
          profile: TileStore.get().profile(),
          dark: this.dark,
          appsHidden: false,
          reveal: this.reveal,
          maxTiles: 6,
          frameWidth: 260
        })
      }
      .scale({ x: this.buildDone ? 1.04 : 1.0, y: this.buildDone ? 1.04 : 1.0 })
      .animation({ curve: TilesTheme.springIn() })

      Row({ space: 8 }) {
        ForEach([0, 1, 2, 3, 4, 5], (i: number) => {
          Column()
            .width(i < this.reveal ? 22 : 8)
            .height(8)
            .borderRadius(4)
            .backgroundColor(TilesTheme.tile(this.choice().color, false, this.dark).on)
            .opacity(i < this.reveal ? 1.0 : 0.3)
            .animation({ duration: 250, curve: Curve.EaseOut })
        }, (i: number) => 'dot' + i.toString())
      }
      Blank()
      Text('On-device · no account needed')
        .fontSize(13)
        .fontColor(TilesTheme.tile(this.choice().color, false, this.dark).onMuted)
        .margin({ bottom: 32 })
    }
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Center)
    .accessibilityText(this.buildLine)
  }
}
