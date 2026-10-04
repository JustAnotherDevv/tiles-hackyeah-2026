import { LengthMetrics } from '@kit.ArkUI';
import { Profile, Suggestion, TileAction, TileSpec } from '../model/Tile';
import { K_LIST, K_PENDING, K_PROFILE, K_SUGGESTIONS, TileStore } from '../data/TileStore';
import { PROFILE_IDS, profileBlurb, profileFor } from '../data/SeedTiles';
import { ThemePalette, TilesTheme, TypeScale, withAlpha } from '../theme/TilesTheme';
import { TileView } from '../components/TileView';
import { AssistantSheet } from './AssistantSheet';
import { Adaptation } from '../ai/Adaptation';
import { PlatformKeys } from '../platform/TilesPlatform';
import { Speech } from '../platform/Speech';
import { TileHaptics } from '../platform/TileHaptics';
import { K_ASSISTANT_SEED, K_DARK, K_REDUCE_MOTION, openTileDetail, platformAction, profileAccent } from './ShellKeys';

const DAYS: string[] = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS: string[] = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December'];

/** Time-of-day header wash: two palette hues blended softly into the warm page background. */
class DayMood {
  greeting: string = 'Hello';
  a: string = '#FFC83D';
  b: string = '#FF9F6B';
}

function moodNow(): DayMood {
  const h: number = new Date().getHours();
  const m: DayMood = new DayMood();
  if (h >= 5 && h < 12) {
    m.greeting = 'Good morning';
    m.a = '#FFC83D';
    m.b = '#FF9F6B';
  } else if (h >= 12 && h < 18) {
    m.greeting = 'Good afternoon';
    m.a = '#3DA5FF';
    m.b = '#2ED3A0';
  } else if (h >= 18 && h < 23) {
    m.greeting = 'Good evening';
    m.a = '#9B7BFF';
    m.b = '#FF6B5A';
  } else {
    m.greeting = 'Good night';
    m.a = '#9B7BFF';
    m.b = '#3DA5FF';
  }
  return m;
}

/** @Builder args are passed as ONE object literal so ArkUI passes them by reference (reactive). */
class ChipArgs {
  text: string = '';
  color: string = 'sky';
}

class IconBtnArgs {
  icon: Resource = $r('sys.symbol.gearshape');
  label: string = '';
  badge: number = 0;
  route: string = '';
}

function dateLine(): string {
  const d: Date = new Date();
  return DAYS[d.getDay()] + ', ' + d.getDate().toString() + ' ' + MONTHS[d.getMonth()];
}

/**
 * Tiles home: warm time-of-day header, profile chip (profile switcher), caregiver badge, adaptation chips,
 * suggestion / approval banners, the adaptive tile grid (columns per profile, 2x1 / 2x2 spans, long-press to
 * edit: drag to reorder, remove) and the pinned "Ask Tiles…" assistant bar that opens the Assistant sheet.
 */
@Component
export struct HomeView {
  @Consume('tilesNav') nav: NavPathStack;
  @StorageLink(K_LIST) tiles: TileSpec[] = [];
  @StorageLink(K_PROFILE) profile: Profile = new Profile();
  @StorageLink(K_SUGGESTIONS) suggestions: Suggestion[] = [];
  @StorageLink(K_PENDING) pending: TileSpec[] = [];
  @StorageProp(K_DARK) dark: boolean = false;
  @StorageProp(K_REDUCE_MOTION) reduceMotion: boolean = false;
  @StorageProp(PlatformKeys.SPEAKING) speaking: string = '';
  @StorageProp(K_ASSISTANT_SEED) @Watch('onAssistantSeed') assistantSeed: string = '';
  @State editing: boolean = false;
  @State showAssistant: boolean = false;
  @State showProfiles: boolean = false;
  @State seed: string = '';
  @State gridW: number = 0;
  @State mood: DayMood = moodNow();
  @State today: string = dateLine();
  @State dragIndex: number = -1;

  aboutToAppear(): void {
    this.mood = moodNow();
    this.today = dateLine();
    if (this.assistantSeed.length > 0) {
      this.onAssistantSeed();
    }
  }

  onAssistantSeed(): void {
    if (this.assistantSeed.length === 0) {
      return;
    }
    const s: string = this.assistantSeed.split('#')[0];
    AppStorage.setOrCreate<string>(K_ASSISTANT_SEED, '');
    this.openAssistant(s === 'open' ? '' : s);
  }

  // ---------- derived ----------

  pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }

  ty(): TypeScale {
    return TilesTheme.type(this.profile.textScale);
  }

  cols(): number {
    const c: number = Math.floor(this.profile.columns);
    return c >= 1 && c <= 6 ? c : 4;
  }

  columnsTemplate(): string {
    const parts: string[] = [];
    for (let i = 0; i < this.cols(); i++) {
      parts.push('1fr');
    }
    return parts.join(' ');
  }

  /** Height of one grid row (vp): wide enough for the profile's type scale, never squashed. */
  rowH(): number {
    const gap: number = TilesTheme.GRID_GAP;
    const w: number = this.gridW > 0 ? this.gridW : 360;
    const cell: number = (w - gap * (this.cols() - 1)) / this.cols();
    const s: number = Math.max(1, Math.min(1.8, this.profile.textScale));
    const byWidth: number = this.cols() <= 2 ? cell * 0.62 : cell * 1.25;
    return Math.round(Math.max(this.cols() <= 2 ? 128 * s : 136 * s, byWidth));
  }

  /** Big-type 2-column homes (senior / low vision): tiles size to their content instead of fixed rows. */
  autoRows(): boolean {
    return this.cols() <= 2;
  }

  rowSpanOf(t: TileSpec): number {
    return this.autoRows() ? 1 : TilesTheme.rowSpan(t.size);
  }

  itemH(t: TileSpec): number {
    return t.size === '2x2' ? this.rowH() * 2 + TilesTheme.GRID_GAP : this.rowH();
  }

  layoutOptions(): GridLayoutOptions {
    const irregular: number[] = [];
    for (let i = 0; i < this.tiles.length; i++) {
      const t: TileSpec = this.tiles[i];
      if (TilesTheme.colSpan(t.size, this.cols()) > 1 || this.rowSpanOf(t) > 1) {
        irregular.push(i);
      }
    }
    const opts: GridLayoutOptions = {
      regularSize: [1, 1],
      irregularIndexes: irregular,
      onGetIrregularSizeByIndex: (index: number): [number, number] => {
        const t: TileSpec | undefined = index < this.tiles.length ? this.tiles[index] : undefined;
        if (t === undefined) {
          return [1, 1];
        }
        return [this.rowSpanOf(t), TilesTheme.colSpan(t.size, this.cols())];
      }
    };
    return opts;
  }

  pendingSuggestion(): Suggestion | null {
    for (const s of this.suggestions) {
      if (s.status === 'pending') {
        return s;
      }
    }
    return null;
  }

  sugg(): Suggestion {
    const s: Suggestion | null = this.pendingSuggestion();
    return s !== null ? s : new Suggestion();
  }

  badgeCount(): number {
    let n: number = this.pending.length;
    for (const s of this.suggestions) {
      if (s.status === 'pending') {
        n++;
      }
    }
    return n;
  }

  caregiverName(): string {
    return this.profile.caregiver.length > 0 ? this.profile.caregiver : 'your family';
  }

  dur(ms: number): number {
    return TilesTheme.dur(ms, this.reduceMotion);
  }

  toast(msg: string): void {
    try {
      this.getUIContext().getPromptAction().showToast({ message: msg, duration: 2000 });
    } catch (e) {
      // toast is best effort
    }
  }

  // ---------- actions ----------

  openAssistant(seed: string): void {
    this.seed = seed;
    this.editing = false;
    this.showAssistant = true;
  }

  onTileAction(a: TileAction, t: TileSpec): void {
    if (this.editing) {
      return;
    }
    if (a.kind === 'open') {
      openTileDetail(this.nav, t);
      return;
    }
    if (a.kind === 'navigate' && a.arg === 'assistant') {
      this.openAssistant('');
      return;
    }
    if (a.kind === 'dismiss' || a.kind === 'toggle') {
      // Removing / checking reflows the grid: animate the store change.
      this.getUIContext().animateTo({ curve: TilesTheme.springReflow(), duration: this.dur(TilesTheme.DUR_SLOW) }, () => {
        platformAction(a, t);
      });
      return;
    }
    platformAction(a, t);
  }

  enterEdit(): void {
    TileHaptics.tap();
    this.getUIContext().animateTo({ curve: TilesTheme.springReflow(), duration: this.dur(TilesTheme.DUR_MED) }, () => {
      this.editing = true;
    });
  }

  exitEdit(): void {
    this.getUIContext().animateTo({ curve: TilesTheme.springReflow(), duration: this.dur(TilesTheme.DUR_MED) }, () => {
      this.editing = false;
    });
  }

  removeTile(t: TileSpec): void {
    TileHaptics.tap();
    this.getUIContext().animateTo({ curve: TilesTheme.springReflow(), duration: this.dur(TilesTheme.DUR_SLOW) }, () => {
      TileStore.get().removeTile(t.id);
    });
    this.toast('Removed "' + t.title + '"');
  }

  moveTile(from: number, to: number): void {
    if (from === to || from < 0 || to < 0) {
      return;
    }
    this.getUIContext().animateTo({ curve: TilesTheme.springReflow(), duration: this.dur(TilesTheme.DUR_SLOW) }, () => {
      TileStore.get().moveTile(from, Math.min(to, this.tiles.length - 1));
    });
  }

  switchProfile(id: string): void {
    this.showProfiles = false;
    if (id === this.profile.id) {
      return;
    }
    TileHaptics.success();
    this.getUIContext().animateTo({ curve: TilesTheme.springReflow(), duration: this.dur(TilesTheme.DUR_SLOW) }, () => {
      TileStore.get().switchProfile(id);
    });
    this.toast('Tiles rebuilt the home for ' + profileFor(id).name);
  }

  decide(s: Suggestion, approve: boolean): void {
    if (approve && this.profile.caregiver.length > 0) {
      this.nav.pushPathByName('caregiver', '', true);
      return;
    }
    this.getUIContext().animateTo({ curve: TilesTheme.springReflow(), duration: this.dur(TilesTheme.DUR_MED) }, () => {
      Adaptation.decide(s.id, approve);
    });
    this.toast(approve ? 'Done: ' + s.title : 'Okay, maybe later');
  }

  // ---------- header ----------

  @Builder
  avatar(p: Profile, size: number) {
    Text(p.name.length > 0 ? p.name.substring(0, 1) : '?')
      .width(size)
      .height(size)
      .borderRadius(size / 2)
      .textAlign(TextAlign.Center)
      .fontSize(Math.round(size * 0.46))
      .fontWeight(FontWeight.Bold)
      .fontColor(TilesTheme.tile(profileAccent(p.id), p.highContrast, this.dark).on)
      .backgroundColor(TilesTheme.tile(profileAccent(p.id), p.highContrast, this.dark).bg)
  }

  @Builder
  headerAvatar() {
    Text(this.profile.name.length > 0 ? this.profile.name.substring(0, 1) : '?')
      .width(36)
      .height(36)
      .borderRadius(18)
      .textAlign(TextAlign.Center)
      .fontSize(17)
      .fontWeight(FontWeight.Bold)
      .fontColor(TilesTheme.tile(profileAccent(this.profile.id), this.profile.highContrast, this.dark).on)
      .backgroundColor(TilesTheme.tile(profileAccent(this.profile.id), this.profile.highContrast, this.dark).bg)
  }

  @Builder
  roundIconButton(a: IconBtnArgs) {
    Stack({ alignContent: Alignment.TopEnd }) {
      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph(a.icon)
          .fontSize(22)
          .fontColor([this.pal().text])
      }
      .width(TilesTheme.TAP_MIN)
      .height(TilesTheme.TAP_MIN)
      .backgroundColor(this.pal().surface)
      .border({ width: this.profile.highContrast ? 2 : 1, color: this.pal().border })
      .onClick(() => {
        this.nav.pushPathByName(a.route, '', true);
      })

      if (a.badge > 0) {
        Text(a.badge > 9 ? '9+' : a.badge.toString())
          .fontSize(11)
          .fontWeight(FontWeight.Bold)
          .fontColor('#FFFFFF')
          .backgroundColor('#E5484D')
          .borderRadius(10)
          .height(20)
          .constraintSize({ minWidth: 20 })
          .padding({ left: 5, right: 5 })
          .textAlign(TextAlign.Center)
          .border({ width: 2, color: this.pal().bg })
          .transition(TransitionEffect.scale({ x: 0, y: 0 }).animation({ curve: TilesTheme.springIn() }))
      }
    }
    .accessibilityGroup(true)
    .accessibilityText(a.label + (a.badge > 0 ? ', ' + a.badge.toString() + ' waiting' : ''))
  }

  @Builder
  chip(a: ChipArgs) {
    Row({ space: 6 }) {
      Circle().width(8).height(8).fill(TilesTheme.tile(a.color, this.profile.highContrast, this.dark).bg)
      Text(a.text)
        .fontSize(Math.round(12 * Math.min(1.4, this.profile.textScale)))
        .fontColor(this.pal().text)
        .fontWeight(FontWeight.Medium)
    }
    .padding({ left: 10, right: 12, top: 6, bottom: 6 })
    .borderRadius(TilesTheme.RADIUS_CHIP)
    .backgroundColor(withAlpha(this.pal().surface, this.dark ? 0.9 : 0.85))
    .border({ width: this.profile.highContrast ? 1.5 : 0, color: this.pal().border })
  }

  @Builder
  header() {
    Column({ space: TilesTheme.SPACE_M }) {
      Row({ space: TilesTheme.SPACE_S }) {
        Row({ space: TilesTheme.SPACE_S }) {
          this.headerAvatar()
          Text(this.profile.name)
            .fontSize(Math.round(16 * Math.min(1.4, this.profile.textScale)))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.pal().text)
            .maxLines(1)
          SymbolGlyph($r('sys.symbol.chevron_down'))
            .fontSize(16)
            .fontColor([this.pal().textMuted])
        }
        .height(TilesTheme.TAP_MIN)
        .padding({ left: 6, right: 14 })
        .borderRadius(TilesTheme.RADIUS_CHIP)
        .backgroundColor(this.pal().surface)
        .border({ width: this.profile.highContrast ? 2 : 1, color: this.pal().border })
        .onClick(() => {
          this.showProfiles = true;
        })
        .accessibilityGroup(true)
        .accessibilityText('Profile ' + this.profile.name + '. Switch person')

        Blank()

        this.roundIconButton({
          icon: $r('sys.symbol.person_2'),
          label: this.profile.caregiver.length > 0 ? this.profile.caregiver + '\'s approvals' : 'Approvals',
          badge: this.badgeCount(),
          route: 'caregiver'
        })
        this.roundIconButton({ icon: $r('sys.symbol.gearshape'), label: 'Settings', badge: 0, route: 'settings' })
      }
      .width('100%')

      Column({ space: 2 }) {
        Text(this.mood.greeting + ',')
          .fontSize(Math.min(this.ty().title, 26))
          .fontColor(this.pal().textMuted)
          .fontWeight(FontWeight.Medium)
        Text(this.profile.name.length > 0 ? this.profile.name : 'friend')
          .fontSize(Math.min(Math.round(this.ty().headline * 1.35), 46))
          .fontWeight(FontWeight.Bolder)
          .fontColor(this.pal().text)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(dateLine())
          .fontSize(Math.min(this.ty().label, 20))
          .fontColor(this.pal().textMuted)
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
      .accessibilityGroup(true)
      .accessibilityText(this.mood.greeting + ', ' + this.profile.name + '. ' + this.today)

      Scroll() {
        Row({ space: TilesTheme.SPACE_S }) {
          if (this.profile.textScale > 1.05) {
            this.chip({ text: 'Text ' + Math.round(this.profile.textScale * 100).toString() + '%', color: 'sun' })
          }
          if (this.profile.readAloud) {
            this.chip({ text: 'Reads aloud', color: 'mint' })
          }
          if (this.profile.highContrast) {
            this.chip({ text: 'High contrast', color: 'ink' })
          }
          if (this.profile.caregiver.length > 0) {
            this.chip({ text: this.profile.caregiver + ' approves changes', color: 'grape' })
          }
          this.chip({ text: this.tiles.length.toString() + ' tiles', color: 'sky' })
        }
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .edgeEffect(EdgeEffect.Spring)
      .width('100%')
      .align(Alignment.Start)
    }
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: TilesTheme.SPACE_M, bottom: TilesTheme.SPACE_L })
  }

  @Builder
  editBar() {
    Row({ space: TilesTheme.SPACE_M }) {
      Column({ space: 2 }) {
        Text('Arrange your home')
          .fontSize(this.ty().title)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().text)
        Text('Drag a tile to move it. Tap the red button to remove.')
          .fontSize(this.ty().caption)
          .fontColor(this.pal().textMuted)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      Button('Done')
        .fontSize(this.ty().label)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().onAccent)
        .backgroundColor(this.pal().accent)
        .height(TilesTheme.TAP_MIN)
        .padding({ left: 22, right: 22 })
        .onClick(() => this.exitEdit())
    }
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: TilesTheme.SPACE_L, bottom: TilesTheme.SPACE_L })
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.move(TransitionEdge.TOP)))
  }

  // ---------- banners ----------

  @Builder
  suggestionBanner() {
    Column({ space: TilesTheme.SPACE_M }) {
      Row({ space: TilesTheme.SPACE_M }) {
        Stack() {
          SymbolGlyph($r('sys.symbol.lightbulb_fill'))
            .fontSize(22)
            .fontColor([TilesTheme.tile('sun', this.profile.highContrast, this.dark).on])
        }
        .width(44)
        .height(44)
        .borderRadius(22)
        .backgroundColor(TilesTheme.tile('sun', this.profile.highContrast, this.dark).bg)

        Column({ space: 2 }) {
          Text('Tiles noticed something')
            .fontSize(this.ty().caption)
            .fontColor(this.pal().textMuted)
            .fontWeight(FontWeight.Medium)
          Text(this.sugg().title)
            .fontSize(this.ty().body)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.pal().text)
          if (this.sugg().reason.length > 0 || this.sugg().detail.length > 0) {
            Text(this.sugg().reason.length > 0 ? this.sugg().reason : this.sugg().detail)
              .fontSize(this.ty().caption)
              .fontColor(this.pal().textMuted)
              .maxLines(2)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)

      Flex({ direction: this.profile.textScale >= 1.3 ? FlexDirection.Column : FlexDirection.Row,
        space: { main: LengthMetrics.vp(TilesTheme.SPACE_S) } }) {
        Button(this.profile.caregiver.length > 0 ? 'Ask ' + this.profile.caregiver : 'Yes, do it')
          .fontSize(this.ty().label)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().onAccent)
          .backgroundColor(this.pal().accent)
          .height(TilesTheme.tapTarget(this.profile))
          .flexGrow(1)
          .flexBasis(this.profile.textScale >= 1.3 ? 'auto' : 0)
          .width('100%')
          .onClick(() => this.decide(this.sugg(), true))
        Button('Not now')
          .fontSize(this.ty().label)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.pal().text)
          .backgroundColor(this.pal().surfaceAlt)
          .height(TilesTheme.tapTarget(this.profile))
          .flexGrow(1)
          .flexBasis(this.profile.textScale >= 1.3 ? 'auto' : 0)
          .width('100%')
          .onClick(() => this.decide(this.sugg(), false))
      }
      .width('100%')
    }
    .padding(TilesTheme.SPACE_L)
    .borderRadius(TilesTheme.RADIUS_TILE)
    .backgroundColor(this.pal().surface)
    .border({ width: this.profile.highContrast ? 2 : 1, color: this.profile.highContrast ? this.pal().border :
      withAlpha('#FFC83D', 0.6) })
    .shadow({ radius: 16, color: this.pal().shadow, offsetY: 4 })
    .margin({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, bottom: TilesTheme.SPACE_M })
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: -16 }))
      .animation({ curve: TilesTheme.springIn() }))
  }

  @Builder
  pendingBanner() {
    Row({ space: TilesTheme.SPACE_M }) {
      Stack() {
        SymbolGlyph($r('sys.symbol.clock_fill'))
          .fontSize(20)
          .fontColor([TilesTheme.tile('grape', this.profile.highContrast, this.dark).on])
      }
      .width(40)
      .height(40)
      .borderRadius(20)
      .backgroundColor(TilesTheme.tile('grape', this.profile.highContrast, this.dark).bg)

      Column({ space: 2 }) {
        Text(this.pending.length.toString() + (this.pending.length === 1 ? ' new tile is' : ' new tiles are') +
          ' waiting for ' + this.caregiverName())
          .fontSize(this.ty().label)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().text)
        Text('They appear here as soon as they are approved.')
          .fontSize(this.ty().caption)
          .fontColor(this.pal().textMuted)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      SymbolGlyph($r('sys.symbol.chevron_right'))
        .fontSize(18)
        .fontColor([this.pal().textMuted])
    }
    .width('100%')
    .constraintSize({ minHeight: TilesTheme.tapTarget(this.profile) })
    .padding(TilesTheme.SPACE_M)
    .borderRadius(TilesTheme.RADIUS_TILE)
    .backgroundColor(withAlpha(TilesTheme.tile('grape', false, this.dark).bg, this.dark ? 0.22 : 0.14))
    .border({ width: this.profile.highContrast ? 2 : 0, color: this.pal().border })
    .margin({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, bottom: TilesTheme.SPACE_M })
    .onClick(() => {
      this.nav.pushPathByName('caregiver', '', true);
    })
    .accessibilityGroup(true)
    .transition(TransitionEffect.OPACITY.animation({ duration: this.dur(TilesTheme.DUR_MED) }))
  }

  // ---------- grid ----------

  @Builder
  dragGhost(t: TileSpec) {
    Column() {
      TileView({ tile: t, profile: this.profile, dark: this.dark, fillHeight: true, reduceMotion: true })
    }
    .width(this.gridW > 0 ? (this.gridW - TilesTheme.GRID_GAP * (this.cols() - 1)) / this.cols() *
      TilesTheme.colSpan(t.size, this.cols()) + TilesTheme.GRID_GAP * (TilesTheme.colSpan(t.size, this.cols()) - 1) :
      160)
    .height(this.itemH(t))
    .opacity(0.92)
    .scale({ x: 1.04, y: 1.04 })
  }

  @Builder
  emptyState() {
    Column({ space: TilesTheme.SPACE_M }) {
      SymbolGlyph($r('sys.symbol.square_grid_2x2'))
        .fontSize(48)
        .fontColor([this.pal().accent])
      Text('Your home is empty')
        .fontSize(this.ty().title)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().text)
      Text('Ask Tiles for anything: "remind me about pills at 8", "call my daughter", "plan dinner on Friday".')
        .fontSize(this.ty().body)
        .fontColor(this.pal().textMuted)
        .textAlign(TextAlign.Center)
      Button('Ask Tiles')
        .fontSize(this.ty().label)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().onAccent)
        .backgroundColor(this.pal().accent)
        .height(TilesTheme.tapTarget(this.profile))
        .padding({ left: 28, right: 28 })
        .onClick(() => this.openAssistant(''))
    }
    .width('100%')
    .padding(TilesTheme.SPACE_XXL)
  }

  @Builder
  tileGrid() {
    Grid(undefined, this.layoutOptions()) {
      ForEach(this.tiles, (t: TileSpec, i: number) => {
        GridItem() {
          Stack({ alignContent: Alignment.TopStart }) {
            TileView({
              tile: t,
              profile: this.profile,
              dark: this.dark,
              fillHeight: !this.autoRows(),
              reduceMotion: this.reduceMotion,
              onAction: (a: TileAction, tt: TileSpec) => this.onTileAction(a, tt),
              onLongPress: (tt: TileSpec) => {
                if (!this.editing) {
                  this.enterEdit();
                }
              }
            })

            if (this.editing) {
              // Catches taps while arranging so tiles do not open; the grid itself still handles the drag.
              Column()
                .width('100%')
                .height('100%')
                .borderRadius(TilesTheme.radiusFor(t.size))
                .border({ width: 2, color: withAlpha(this.pal().text, 0.25), style: BorderStyle.Dashed })
                .backgroundColor(withAlpha(this.pal().bg, 0.08))
                .onClick(() => {
                  this.toast('Hold and drag to move "' + t.title + '"');
                })

              Button({ type: ButtonType.Circle, stateEffect: true }) {
                SymbolGlyph($r('sys.symbol.minus'))
                  .fontSize(20)
                  .fontColor(['#FFFFFF'])
              }
              .width(TilesTheme.TAP_MIN - 8)
              .height(TilesTheme.TAP_MIN - 8)
              .backgroundColor('#E5484D')
              .border({ width: 3, color: this.pal().bg })
              .margin({ left: -6, top: -6 })
              .accessibilityText('Remove ' + t.title)
              .onClick(() => this.removeTile(t))
              .transition(TransitionEffect.scale({ x: 0, y: 0 }).animation({ curve: TilesTheme.springIn() }))
            }
          }
          .width('100%')
          .height(this.autoRows() ? 'auto' : '100%')
          .scale({ x: this.editing ? 0.95 : 1, y: this.editing ? 0.95 : 1 })
          .opacity(this.dragIndex === i ? 0.35 : 1)
        }
        .height(this.autoRows() ? 'auto' : this.itemH(t))
        .transition(TransitionEffect.OPACITY.combine(TransitionEffect.scale({ x: 0.7, y: 0.7 }))
          .animation({ curve: TilesTheme.springIn(), duration: this.dur(TilesTheme.DUR_SLOW) }))
      }, (t: TileSpec) => t.id + '|' + t.size + '|' + t.subtitle + '|' + JSON.stringify(t.blocks))
    }
    .columnsTemplate(this.columnsTemplate())
    .columnsGap(TilesTheme.GRID_GAP)
    .rowsGap(TilesTheme.GRID_GAP)
    .editMode(this.editing)
    .onItemDragStart((event: ItemDragInfo, itemIndex: number) => {
      this.dragIndex = itemIndex;
      TileHaptics.tap();
      return this.dragGhost(this.tiles[itemIndex]);
    })
    .onItemDrop((event: ItemDragInfo, itemIndex: number, insertIndex: number, isSuccess: boolean) => {
      this.dragIndex = -1;
      if (isSuccess && insertIndex >= 0 && insertIndex !== itemIndex) {
        this.moveTile(itemIndex, insertIndex);
      }
    })
    .scrollBar(BarState.Off)
    .edgeEffect(EdgeEffect.None)
    .nestedScroll({ scrollForward: NestedScrollMode.PARENT_FIRST, scrollBackward: NestedScrollMode.SELF_FIRST })
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER })
    .onAreaChange((o: Area, n: Area) => {
      const w: number = Number(n.width) - TilesTheme.GUTTER * 2;
      if (!isNaN(w) && Math.abs(w - this.gridW) > 1) {
        this.gridW = w;
      }
    })
  }

  // ---------- assistant bar + sheets ----------

  @Builder
  assistantBar() {
    Column() {
      Row({ space: TilesTheme.SPACE_M }) {
        SymbolGlyph($r('sys.symbol.wand_and_stars'))
          .fontSize(24)
          .fontColor([this.profile.highContrast ? this.pal().text : '#9B7BFF'])
          .margin({ left: 6 })
        Text('Ask Tiles…')
          .fontSize(this.ty().body)
          .fontColor(this.pal().textMuted)
          .layoutWeight(1)
          .maxLines(1)
        Button({ type: ButtonType.Circle, stateEffect: true }) {
          SymbolGlyph($r('sys.symbol.mic_fill'))
            .fontSize(24)
            .fontColor([this.pal().onAccent])
        }
        .width(TilesTheme.tapTarget(this.profile) - 4)
        .height(TilesTheme.tapTarget(this.profile) - 4)
        .backgroundColor(this.pal().accent)
        .accessibilityText('Speak to Tiles')
        .onClick(() => this.openAssistant('mic'))
      }
      .width('100%')
      .height(TilesTheme.tapTarget(this.profile) + 8)
      .padding({ left: 14, right: 6 })
      .borderRadius(TilesTheme.RADIUS_CHIP)
      .backgroundColor(this.pal().surface)
    }
    .padding(2.5)
    .borderRadius(TilesTheme.RADIUS_CHIP)
    .linearGradient({
      angle: 90,
      colors: this.profile.highContrast ? [[this.pal().border, 0], [this.pal().border, 1]] :
        [['#FFC83D', 0], ['#FF6B5A', 0.33], ['#9B7BFF', 0.66], ['#3DA5FF', 1]]
    })
    .shadow({ radius: 24, color: this.pal().shadow, offsetY: 8 })
    .onClick(() => this.openAssistant(''))
    .accessibilityGroup(true)
    .accessibilityText('Ask Tiles. Type or speak to make a new tile')
  }

  @Builder
  assistantSheet() {
    Column() {
      AssistantSheet({
        seed: this.seed,
        onClose: () => {
          this.showAssistant = false;
        }
      })
    }
    .width('100%')
    .height('100%')
  }

  @Builder
  profileSheet() {
    Column({ space: TilesTheme.SPACE_M }) {
      Text('Who is using this phone?')
        .fontSize(22)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().text)
        .width('100%')
      Text('Tiles rebuilds the whole home for each person.')
        .fontSize(14)
        .fontColor(this.pal().textMuted)
        .width('100%')
      ForEach(PROFILE_IDS, (id: string) => {
        Row({ space: TilesTheme.SPACE_M }) {
          this.avatar(profileFor(id), 48)
          Column({ space: 2 }) {
            Text(profileFor(id).name)
              .fontSize(18)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.pal().text)
            Text(profileBlurb(id))
              .fontSize(13)
              .fontColor(this.pal().textMuted)
              .maxLines(2)
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          if (id === this.profile.id) {
            SymbolGlyph($r('sys.symbol.checkmark_circle_fill'))
              .fontSize(26)
              .fontColor([this.pal().accent])
          }
        }
        .width('100%')
        .constraintSize({ minHeight: 64 })
        .padding(TilesTheme.SPACE_M)
        .borderRadius(TilesTheme.RADIUS_TILE)
        .backgroundColor(id === this.profile.id ?
          withAlpha(TilesTheme.tile(profileAccent(id), false, this.dark).bg, 0.18) : this.pal().surfaceAlt)
        .onClick(() => this.switchProfile(id))
        .accessibilityGroup(true)
        .accessibilityText(profileBlurb(id) + (id === this.profile.id ? ', current' : ''))
      }, (id: string) => id)
    }
    .width('100%')
    .padding({ left: 20, right: 20, top: 8, bottom: 24 })
  }

  @Builder
  speakingPill() {
    Row({ space: TilesTheme.SPACE_S }) {
      SymbolGlyph($r('sys.symbol.speaker_wave_2_fill'))
        .fontSize(18)
        .fontColor([TilesTheme.tile('mint', this.profile.highContrast, this.dark).on])
      Text('Reading aloud')
        .fontSize(this.ty().caption)
        .fontWeight(FontWeight.Bold)
        .fontColor(TilesTheme.tile('mint', this.profile.highContrast, this.dark).on)
      Text('Stop')
        .fontSize(this.ty().caption)
        .fontColor(TilesTheme.tile('mint', this.profile.highContrast, this.dark).on)
        .decoration({ type: TextDecorationType.Underline })
        .padding({ left: 6 })
    }
    .padding({ left: 14, right: 14, top: 8, bottom: 8 })
    .borderRadius(TilesTheme.RADIUS_CHIP)
    .backgroundColor(TilesTheme.tile('mint', this.profile.highContrast, this.dark).bg)
    .shadow({ radius: 12, color: this.pal().shadow, offsetY: 4 })
    .onClick(() => Speech.stop())
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 12 }))
      .animation({ curve: TilesTheme.springIn() }))
  }

  build() {
    Stack({ alignContent: Alignment.Bottom }) {
      Scroll() {
        Column() {
          if (this.editing) {
            this.editBar()
          } else {
            this.header()
          }

          if (!this.editing) {
            if (this.pendingSuggestion() !== null) {
              this.suggestionBanner()
            }
            if (this.pending.length > 0) {
              this.pendingBanner()
            }
          }

          if (this.tiles.length === 0) {
            this.emptyState()
          } else {
            this.tileGrid()
          }

          Blank().height(132)
        }
        .width('100%')
      }
      .scrollBar(BarState.Off)
      .edgeEffect(EdgeEffect.Spring)
      .width('100%')
      .height('100%')
      .align(Alignment.Top)
      .bindSheet(this.showProfiles, this.profileSheet(), {
        height: SheetSize.FIT_CONTENT,
        dragBar: true,
        backgroundColor: this.pal().surface,
        onDisappear: () => {
          this.showProfiles = false;
        }
      })
      .linearGradient({
        angle: 180,
        colors: [[withAlpha(this.mood.a, this.dark ? 0.22 : 0.30), 0],
          [withAlpha(this.mood.b, this.dark ? 0.10 : 0.14), 0.22], [this.pal().bg, 0.42], [this.pal().bg, 1]]
      })

      // Soft fade so tiles slide under the assistant bar.
      Column()
        .width('100%')
        .height(120)
        .linearGradient({ angle: 180, colors: [[withAlpha(this.pal().bg, 0), 0], [this.pal().bg, 0.7]] })
        .hitTestBehavior(HitTestMode.Transparent)

      Column({ space: TilesTheme.SPACE_S }) {
        if (this.speaking.length > 0) {
          this.speakingPill()
        }
        if (!this.editing) {
          this.assistantBar()
        }
      }
      .width('100%')
      .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, bottom: TilesTheme.SPACE_L })
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.pal().bg)
    .bindSheet(this.showAssistant, this.assistantSheet(), {
      height: SheetSize.LARGE,
      dragBar: true,
      showClose: false,
      backgroundColor: this.pal().bg,
      onDisappear: () => {
        this.showAssistant = false;
      }
    })
  }
}
