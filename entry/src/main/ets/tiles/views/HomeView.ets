import { LengthMetrics, window } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';
import { Profile, Suggestion, TileAction, TileSpec } from '../model/Tile';
import { K_LIST, K_PENDING, K_PROFILE, K_SUGGESTIONS, TileStore } from '../data/TileStore';
import { PROFILE_IDS, profileBlurb, profileFor } from '../data/SeedTiles';
import { LL_FONT_FAMILY, ProfileLayout, ThemePalette, TilesTheme, TypeScale, withAlpha } from '../theme/TilesTheme';
import { TileView } from '../components/TileView';
import { AssistantSheet } from './AssistantSheet';
import { AskDock, LLWaveBars } from './AskDock';
import { Adaptation } from '../ai/Adaptation';
import { PlatformKeys } from '../platform/TilesPlatform';
import { Speech } from '../platform/Speech';
import { TileHaptics } from '../platform/TileHaptics';
import { K_ASSISTANT_SEED, K_DARK, K_REDUCE_MOTION, openTileDetail, platformAction } from './ShellKeys';

const DAYS: string[] = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS: string[] = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December'];
/** Tile types that count as "things today" in the everyday sub line. */
const AGENDA_TYPES: string[] = ['plan', 'reminder', 'pills', 'commute', 'timer', 'homework'];
/** Profile chooser chips (prototype ICPS labels), in PROFILE_IDS order. */
const CHIP_LABELS: string[] = ['Senior', 'Kid', 'Low vision', 'Everyday'];
/** Height (vp) of the soft page-coloured fade above the bottom cluster (cards + Ask dock). */
const DOCK_FADE: number = 24;

/** @Builder args are passed as ONE object literal so ArkUI passes them by reference (reactive). */
class IconBtnArgs {
  icon: Resource = $r('sys.symbol.gearshape');
  label: string = '';
  badge: number = 0;
  route: string = '';
}

class ChipArgs {
  id: string = '';
  label: string = '';
}

/** Polish vocative for the seeded people (Halina -> Halino, Michał -> Michale). */
function vocative(name: string): string {
  if (name === 'Halina') {
    return 'Halino';
  }
  if (name === 'Michał') {
    return 'Michale';
  }
  return name;
}

/** "Euthyrox 8:00" -> "Euthyrox at 8:00", keeping the title's own capitalisation (empty if it has no time). */
function atTime(title: string): string {
  const m: RegExpMatchArray | null = title.match(/^(.*?)\s*(\d{1,2}:\d{2})/);
  if (m === null || m.length < 3) {
    return '';
  }
  const what: string = m[1].trim();
  return (what.length > 0 ? what + ' at ' : 'at ') + m[2];
}

/**
 * Tiles home in Living Light (design direction C): full-screen soft gradient, "Who is this phone for?" chooser
 * chips, big Manrope greeting + sub line, the adaptive tile grid (per-profile cols / row height / gap from
 * TilesTheme.layoutFor; long-press to edit: wiggle, drag to reorder, remove), glass suggestion / approval cards,
 * and the pinned Ask dock (AskDock) that opens the Assistant sheet.
 */
@Component
export struct HomeView {
  @Consume('tilesNav') nav: NavPathStack;
  @StorageLink(K_LIST) tiles: TileSpec[] = [];
  @StorageLink(K_PROFILE) profile: Profile = new Profile();
  @StorageLink(K_SUGGESTIONS) @Watch('onSuggestions') suggestions: Suggestion[] = [];
  @StorageLink(K_PENDING) pending: TileSpec[] = [];
  @StorageProp(K_DARK) dark: boolean = false;
  @StorageProp(K_REDUCE_MOTION) reduceMotion: boolean = false;
  @StorageProp(PlatformKeys.SPEAKING) speaking: string = '';
  @StorageProp(K_ASSISTANT_SEED) @Watch('onAssistantSeed') assistantSeed: string = '';
  @State editing: boolean = false;
  @State showAssistant: boolean = false;
  @State seed: string = '';
  @State gridW: number = 0;
  @State dragIndex: number = -1;
  @State wig: number = 0; // edit-mode wiggle phase 0..1 (looping)
  @State staggering: boolean = false; // stagger tile entrances while a profile's home is rebuilt
  /** Immersive window: status-bar / gesture-bar heights (vp) and where our root starts on screen. */
  @State sysTop: number = 0;
  @State sysBottom: number = 0;
  @State rootY: number = 0;
  /** Measured height (vp) of the bottom cluster (speaking / suggestion cards + Ask dock + bottom inset). */
  @State dockH: number = 0;
  /** The "Tiles noticed" card is in the scroll flow above the grid; toggled in animateTo so the tiles slide down / up. */
  @State sugShown: boolean = false;
  /** Last pending suggestion, kept so the card keeps its text while it animates out. */
  private lastSug: Suggestion = new Suggestion();

  aboutToAppear(): void {
    try {
      const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
      window.getLastWindow(ctx).then((win: window.Window) => {
        const sys: window.AvoidArea = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);
        const nav: window.AvoidArea = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_NAVIGATION_INDICATOR);
        this.sysTop = this.getUIContext().px2vp(sys.topRect.height);
        this.sysBottom = this.getUIContext().px2vp(nav.bottomRect.height);
      }).catch(() => {
      });
    } catch (e) {
      // no window (preview)
    }
    if (this.assistantSeed.length > 0) {
      this.onAssistantSeed();
    }
    const p: Suggestion | null = this.pendingSuggestion();
    if (p !== null) {
      this.lastSug = p;
    }
    this.sugShown = p !== null;
  }

  onSuggestions(): void {
    const p: Suggestion | null = this.pendingSuggestion();
    if (p !== null) {
      this.lastSug = p;
    }
    const has: boolean = p !== null;
    if (has !== this.sugShown) {
      this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_SHEET_DUR) }, () => {
        this.sugShown = has;
      });
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

  /** Extra top padding only when the page really lays out under the status bar. */
  topPad(): number {
    return Math.max(0, this.sysTop - this.rootY);
  }

  /** Dock distance from the bottom edge (prototype: 30 vp incl. the gesture bar) when laid out under the bars. */
  bottomPad(): number {
    return this.rootY < 1 && this.sysTop > 0 ? Math.max(30, this.sysBottom + 12) : 16;
  }

  pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }

  ty(): TypeScale {
    return TilesTheme.type(this.profile.textScale);
  }

  lay(): ProfileLayout {
    return TilesTheme.layoutFor(this.profile);
  }

  /** Card text scale: the profile's fs, never below 1 and capped at 1.3. */
  cfs(): number {
    return Math.min(1.3, Math.max(1, this.lay().fs));
  }

  /** Reduced motion: system/app setting, or a profile that asks for it (low vision). */
  rm(): boolean {
    return this.reduceMotion || this.lay().reducedMotion;
  }

  dur(ms: number): number {
    return TilesTheme.dur(ms, this.rm());
  }

  cols(): number {
    const c: number = Math.floor(this.lay().cols);
    return c >= 1 && c <= 6 ? c : 4;
  }

  gap(): number {
    return this.lay().gap;
  }

  pad(): number {
    return this.lay().pad;
  }

  columnsTemplate(): string {
    const parts: string[] = [];
    for (let i = 0; i < this.cols(); i++) {
      parts.push('1fr');
    }
    return parts.join(' ');
  }

  rowH(): number {
    return this.lay().rowH;
  }

  itemH(t: TileSpec): number {
    const span: number = TilesTheme.rowSpan(t.size);
    return this.rowH() * span + this.gap() * (span - 1);
  }

  layoutOptions(): GridLayoutOptions {
    const irregular: number[] = [];
    for (let i = 0; i < this.tiles.length; i++) {
      const t: TileSpec = this.tiles[i];
      if (TilesTheme.colSpan(t.size, this.cols()) > 1 || TilesTheme.rowSpan(t.size) > 1) {
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
        return [TilesTheme.rowSpan(t.size), TilesTheme.colSpan(t.size, this.cols())];
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
    return s !== null ? s : this.lastSug;
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

  /** Prototype greetings ("Dzień dobry, Halino", "Hej, Zosia!", "Morning, Daniel"), aware of the time of day. */
  greeting(): string {
    const h: number = new Date().getHours();
    const name: string = this.profile.name.length > 0 ? this.profile.name : 'friend';
    if (this.profile.id === 'kid') {
      return 'Hej, ' + name + '!';
    }
    if (this.profile.id === 'senior' || this.profile.id === 'lowvision') {
      return (h >= 18 || h < 4 ? 'Dobry wieczór, ' : 'Dzień dobry, ') + vocative(name);
    }
    const part: string = h >= 4 && h < 12 ? 'Morning' : (h >= 12 && h < 18 ? 'Afternoon' : 'Evening');
    return part + ', ' + name;
  }

  firstTimed(types: string[]): string {
    for (const t of this.tiles) {
      if (types.indexOf(t.type) >= 0) {
        const s: string = atTime(t.title);
        if (s.length > 0) {
          return s;
        }
      }
    }
    return '';
  }

  /** Sub line under the greeting: date + the one thing that matters for this person. */
  subLine(): string {
    const d: Date = new Date();
    const id: string = this.profile.id;
    const longDate: string = DAYS[d.getDay()] + ' ' + d.getDate().toString() + ' ' + MONTHS[d.getMonth()];
    if (id === 'senior') {
      const p: string = this.firstTimed(['pills', 'reminder']);
      return p.length > 0 ? longDate + ' · ' + p : longDate;
    }
    if (id === 'kid') {
      const p: string = this.firstTimed(['reminder', 'plan', 'homework']);
      return DAYS[d.getDay()] + ' · ' + (p.length > 0 ? p : this.thingsToday());
    }
    if (id === 'lowvision') {
      return longDate + (this.profile.readAloud ? ' · everything is spoken' : '');
    }
    return DAYS[d.getDay()].substring(0, 3) + ' ' + d.getDate().toString() + ' ' +
      MONTHS[d.getMonth()].substring(0, 3) + ' · ' + this.thingsToday();
  }

  thingsToday(): string {
    let n: number = 0;
    for (const t of this.tiles) {
      if (AGENDA_TYPES.indexOf(t.type) >= 0) {
        n++;
      }
    }
    return n.toString() + (n === 1 ? ' thing today' : ' things today');
  }

  /** Prototype greetSize = round(24 * min(fs, 1.2)), floored at 22 so the dense profile still reads as a title. */
  greetSize(): number {
    return Math.max(22, Math.round(24 * Math.min(this.lay().fs, 1.2)));
  }

  /** Bottom color of the page gradient (fades tiles under the dock). */
  pageEnd(): string {
    const c: Array<[ResourceColor, number]> = this.pal().bgGradient.colors;
    return c.length > 0 ? String(c[c.length - 1][0]) : this.pal().bg;
  }

  /** Top color of the page gradient (status-bar scrim). */
  pageStart(): string {
    const c: Array<[ResourceColor, number]> = this.pal().bgGradient.colors;
    return c.length > 0 ? String(c[0][0]) : this.pal().bg;
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
    if (this.editing) {
      this.exitEdit();
    }
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
      // Removing / checking reflows the grid: animate the store change with the Living Light curve.
      this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_DUR) }, () => {
        platformAction(a, t);
      });
      return;
    }
    platformAction(a, t);
  }

  startWiggle(): void {
    if (this.rm()) {
      return;
    }
    this.wig = 0;
    this.getUIContext().animateTo({
      duration: 320,
      curve: Curve.EaseInOut,
      iterations: -1,
      playMode: PlayMode.Alternate
    }, () => {
      this.wig = 1;
    });
  }

  stopWiggle(): void {
    this.getUIContext().animateTo({ duration: 0 }, () => {
      this.wig = 0.5;
    });
  }

  enterEdit(): void {
    TileHaptics.tap();
    this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.DUR_SLOW) }, () => {
      this.editing = true;
    });
    this.startWiggle();
  }

  exitEdit(): void {
    this.stopWiggle();
    this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.DUR_SLOW) }, () => {
      this.editing = false;
    });
  }

  removeTile(t: TileSpec): void {
    TileHaptics.tap();
    this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_DUR) }, () => {
      TileStore.get().removeTile(t.id);
    });
    this.toast('Removed "' + t.title + '"');
  }

  moveTile(from: number, to: number): void {
    if (from === to || from < 0 || to < 0) {
      return;
    }
    this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_DUR) }, () => {
      TileStore.get().moveTile(from, Math.min(to, this.tiles.length - 1));
    });
  }

  switchProfile(id: string): void {
    if (id === this.profile.id) {
      return;
    }
    TileHaptics.success();
    if (this.editing) {
      this.exitEdit();
    }
    this.staggering = true;
    this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_DUR) }, () => {
      TileStore.get().switchProfile(id);
    });
    setTimeout(() => {
      this.staggering = false;
    }, 1600);
  }

  decide(s: Suggestion, approve: boolean): void {
    if (approve && this.profile.caregiver.length > 0) {
      this.nav.pushPathByName('caregiver', '', true);
      return;
    }
    this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_DUR) }, () => {
      Adaptation.decide(s.id, approve);
    });
    this.toast(approve ? 'Done: ' + s.title : 'Okay, maybe later');
  }

  // ---------- header ----------

  @Builder
  roundIconButton(a: IconBtnArgs) {
    Stack({ alignContent: Alignment.TopEnd }) {
      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph(a.icon)
          .fontSize(20)
          .fontColor([this.pal().ink])
      }
      .width(40)
      .height(40)
      .backgroundColor(this.pal().surface)
      .backdropBlur(TilesTheme.LL_BLUR)
      .border({ width: this.profile.highContrast ? 1.5 : 0, color: this.pal().line })
      .shadow(TilesTheme.LL_SHADOW_SOFT)
      .onClick(() => {
        this.nav.pushPathByName(a.route, '', true);
      })

      if (a.badge > 0) {
        Text(a.badge > 9 ? '9+' : a.badge.toString())
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(11)
          .fontWeight(FontWeight.Bold)
          .fontColor('#FFFFFF')
          .backgroundColor(this.pal().danger)
          .borderRadius(9)
          .height(18)
          .constraintSize({ minWidth: 18 })
          .padding({ left: 5, right: 5 })
          .textAlign(TextAlign.Center)
          .margin({ top: -4, right: -4 })
          .transition(TransitionEffect.scale({ x: 0, y: 0 }).animation({ curve: TilesTheme.ease(), duration: 400 }))
      }
    }
    .accessibilityGroup(true)
    .accessibilityText(a.label + (a.badge > 0 ? ', ' + a.badge.toString() + ' waiting' : ''))
  }

  @Builder
  profileChip(a: ChipArgs) {
    Text(a.label)
      .fontFamily(LL_FONT_FAMILY)
      .fontSize(12.5)
      .fontWeight(FontWeight.Bold)
      .fontColor(a.id === this.profile.id ? this.pal().onInk : this.pal().ink)
      .maxLines(1)
      .textOverflow({ overflow: TextOverflow.Ellipsis })
      .textAlign(TextAlign.Center)
      .layoutWeight(1)
      .height(44)
      .padding({ left: 4, right: 4 })
      .borderRadius(TilesTheme.LL_RADIUS_PILL)
      .backgroundColor(a.id === this.profile.id ? this.pal().ink : (this.dark ? Color.Transparent : '#66FFFFFF'))
      .border({ width: 1.5, color: a.id === this.profile.id ? this.pal().ink : this.pal().line })
      .animation({ curve: TilesTheme.ease(), duration: this.dur(300) })
      .onClick(() => this.switchProfile(a.id))
      .accessibilityText(profileBlurb(a.id) + (a.id === this.profile.id ? ', current' : ''))
  }

  @Builder
  header() {
    Column({ space: 8 }) {
      // "Who is this phone for?" eyebrow + caregiver / settings shortcuts
      Row({ space: 8 }) {
        Text('WHO IS THIS PHONE FOR?')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(12)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(1.44)
          .fontColor(this.pal().muted)
          .layoutWeight(1)
          .maxLines(1)
        this.roundIconButton({
          icon: $r('sys.symbol.person_2'),
          label: this.profile.caregiver.length > 0 ? this.profile.caregiver + '\'s approvals' : 'Approvals',
          badge: this.badgeCount(),
          route: 'caregiver'
        })
        this.roundIconButton({ icon: $r('sys.symbol.gearshape'), label: 'Settings', badge: 0, route: 'settings' })
      }
      .width('100%')

      Row({ space: 6 }) {
        ForEach(PROFILE_IDS, (id: string, i: number) => {
          this.profileChip({ id: id, label: i < CHIP_LABELS.length ? CHIP_LABELS[i] : profileFor(id).name })
        }, (id: string) => id)
      }
      .width('100%')
      .margin({ bottom: 6 })

      Row({ space: 10 }) {
        Column({ space: 3 }) {
          Text(this.greeting())
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(this.greetSize())
            .fontWeight(FontWeight.Bold)
            .letterSpacing(Math.round(this.greetSize() * -0.02 * 100) / 100)
            .lineHeight(Math.round(this.greetSize() * 1.1))
            .fontColor(this.pal().ink)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(this.editing ? 'Drag a tile to move it · tap × to remove' : this.subLine())
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(15)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.pal().muted)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        .accessibilityGroup(true)
        .accessibilityText(this.greeting() + '. ' + this.subLine())

        if (this.editing) {
          Button('Done')
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(15)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.pal().onInk)
            .backgroundColor(this.pal().ink)
            .height(44)
            .padding({ left: 18, right: 18 })
            .onClick(() => this.exitEdit())
            .transition(TransitionEffect.OPACITY.combine(TransitionEffect.scale({ x: 0.8, y: 0.8 }))
              .animation({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.DUR_SLOW) }))
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Bottom)
      .margin({ top: 4, bottom: 16 })
    }
    .width('100%')
    .padding({ left: this.pad(), right: this.pad(), top: 10 + this.topPad() })
  }

  // ---------- glass cards ----------

  @Builder
  sugYes(inRow: boolean) {
    Button(this.profile.caregiver.length > 0 ? 'Ask ' + this.profile.caregiver : 'Yes, do it')
      .fontFamily(LL_FONT_FAMILY)
      .fontSize(Math.round(15 * this.cfs()))
      .fontWeight(FontWeight.Bold)
      .fontColor(this.pal().onInk)
      .backgroundColor(this.pal().ink)
      .height(Math.max(48, TilesTheme.tapTarget(this.profile)))
      .width(inRow ? 'auto' : '100%')
      .layoutWeight(inRow ? 1.4 : 0)
      .onClick(() => this.decide(this.sugg(), true))
  }

  @Builder
  sugNo(inRow: boolean) {
    Button('Not now')
      .fontFamily(LL_FONT_FAMILY)
      .fontSize(Math.round(15 * this.cfs()))
      .fontWeight(FontWeight.Medium)
      .fontColor(this.pal().ink)
      .backgroundColor(Color.Transparent)
      .border({ width: 1.5, color: this.pal().line })
      .height(Math.max(48, TilesTheme.tapTarget(this.profile)))
      .width(inRow ? 'auto' : '100%')
      .layoutWeight(inRow ? 1 : 0)
      .onClick(() => this.decide(this.sugg(), false))
  }

  @Builder
  suggestionCard() {
    Column({ space: 10 }) {
      Row({ space: 8 }) {
        SymbolGlyph($r('sys.symbol.wand_and_stars_fill'))
          .fontSize(18)
          .fontColor([this.pal().accent])
        Text('TILES NOTICED')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(12)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(0.96)
          .fontColor(this.pal().accent)
          .layoutWeight(1)
        Button({ type: ButtonType.Circle, stateEffect: true }) {
          SymbolGlyph($r('sys.symbol.xmark'))
            .fontSize(18)
            .fontColor([this.pal().muted])
        }
        .width(36)
        .height(36)
        .backgroundColor(Color.Transparent)
        .accessibilityText('Dismiss')
        .onClick(() => this.decide(this.sugg(), false))
      }
      .width('100%')
      .height(36)

      Text(this.sugg().title)
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(Math.round(20 * this.cfs()))
        .fontWeight(FontWeight.Bold)
        .letterSpacing(-0.2)
        .lineHeight(Math.round(23 * this.cfs()))
        .fontColor(this.pal().ink)
        .width('100%')
      if (this.sugg().reason.length > 0 || this.sugg().detail.length > 0) {
        Text(this.sugg().reason.length > 0 ? this.sugg().reason : this.sugg().detail)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(Math.round(14 * this.cfs()))
          .lineHeight(Math.round(20 * this.cfs()))
          .fontColor(this.pal().muted)
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%')
      }

      if (this.profile.textScale >= 1.7) {
        // each button in its own Row: layoutWeight inside a Column stretches height (huge buttons)
        Column({ space: 8 }) {
          Row() { this.sugYes(true) }.width('100%')
          Row() { this.sugNo(true) }.width('100%')
        }
        .width('100%')
        .margin({ top: 2 })
      } else {
        Row({ space: 8 }) {
          this.sugYes(true)
          this.sugNo(true)
        }
        .width('100%')
        .margin({ top: 2 })
      }
    }
    .width('100%')
    .padding({ left: 16, right: 12, top: 12, bottom: 16 })
    .borderRadius(TilesTheme.LL_RADIUS_L)
    .backgroundColor(this.pal().surface)
    .backdropBlur(TilesTheme.LL_BLUR)
    .border({ width: this.profile.highContrast ? 1.5 : 0, color: this.pal().line })
    .shadow(TilesTheme.LL_SHADOW_TILE)
  }

  @Builder
  pendingCard() {
    Row({ space: 12 }) {
      Stack() {
        SymbolGlyph($r('sys.symbol.clock_fill'))
          .fontSize(20)
          .fontColor([this.pal().onAccent])
      }
      .width(40)
      .height(40)
      .borderRadius(20)
      .backgroundColor(this.pal().accent)

      Column({ space: 2 }) {
        Text(this.pending.length.toString() + (this.pending.length === 1 ? ' new tile is' : ' new tiles are') +
          ' waiting for ' + this.caregiverName())
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(Math.round(15 * this.cfs()))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().ink)
        Text('They appear here as soon as they are approved.')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(Math.round(13 * this.cfs()))
          .fontColor(this.pal().muted)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      Circle()
        .width(10)
        .height(10)
        .fill(this.pal().accent)
    }
    .width('100%')
    .constraintSize({ minHeight: TilesTheme.tapTarget(this.profile) })
    .padding({ left: 12, right: 16, top: 10, bottom: 10 })
    .borderRadius(TilesTheme.LL_RADIUS_M)
    .backgroundColor(this.pal().surface)
    .backdropBlur(TilesTheme.LL_BLUR)
    .border({ width: this.profile.highContrast ? 1.5 : 0, color: this.pal().line })
    .shadow(TilesTheme.LL_SHADOW_TILE)
    .margin({ bottom: 14 })
    .onClick(() => {
      this.nav.pushPathByName('caregiver', '', true);
    })
    .accessibilityGroup(true)
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: -12 }))
      .animation({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_DUR) }))
  }

  @Builder
  speakingCard() {
    Row({ space: 12 }) {
      LLWaveBars({ color: this.pal().accent, reduced: this.rm() })
      Text('Reading aloud…')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
        .fontColor(this.pal().ink)
        .layoutWeight(1)
        .maxLines(1)
      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph($r('sys.symbol.pause_fill'))
          .fontSize(20)
          .fontColor([this.pal().onInk])
      }
      .width(44)
      .height(44)
      .backgroundColor(this.pal().ink)
      .accessibilityText('Stop reading')
      .onClick(() => Speech.stop())
    }
    .width('100%')
    .padding({ left: 16, right: 14, top: 12, bottom: 12 })
    .margin({ left: -4, right: -4 })
    .borderRadius(TilesTheme.LL_RADIUS_L)
    .backgroundColor(this.pal().surface)
    .backdropBlur(TilesTheme.LL_BLUR)
    .shadow(TilesTheme.LL_SHADOW_SHEET)
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 16 }))
      .animation({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_SHEET_DUR) }))
  }

  // ---------- grid ----------

  @Builder
  dragGhost(t: TileSpec) {
    Column() {
      TileView({ tile: t, profile: this.profile, dark: this.dark, fillHeight: true, reduceMotion: true })
    }
    .width(this.gridW > 0 ? (this.gridW - this.gap() * (this.cols() - 1)) / this.cols() *
      TilesTheme.colSpan(t.size, this.cols()) + this.gap() * (TilesTheme.colSpan(t.size, this.cols()) - 1) :
      160)
    .height(this.itemH(t))
    .opacity(0.95)
    .scale({ x: 1.05, y: 1.05 })
    .shadow(TilesTheme.LL_SHADOW_SHEET)
  }

  @Builder
  emptyState() {
    Column({ space: 12 }) {
      SymbolGlyph($r('sys.symbol.square_grid_2x2'))
        .fontSize(48)
        .fontColor([this.pal().accent])
      Text('Your home is empty')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().title)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().ink)
      Text('Ask Tiles for anything: "remind me about pills at 8", "call my daughter", "plan dinner on Friday".')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().body)
        .fontColor(this.pal().muted)
        .textAlign(TextAlign.Center)
      Button('Ask Tiles')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().label)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().onInk)
        .backgroundColor(this.pal().ink)
        .height(TilesTheme.tapTarget(this.profile))
        .padding({ left: 28, right: 28 })
        .onClick(() => this.openAssistant(''))
    }
    .width('100%')
    .padding(32)
    .borderRadius(TilesTheme.LL_RADIUS_L)
    .backgroundColor(this.pal().surface)
    .margin({ left: this.pad(), right: this.pad() })
  }

  /** Edit-mode wiggle: ±1.1° alternating per tile (prototype keyframes `wiggle`). */
  wiggleAngle(i: number): number {
    if (!this.editing || this.dragIndex === i || this.rm()) {
      return 0;
    }
    const a: number = -1.1 + 2.2 * this.wig;
    return i % 2 === 0 ? a : -a;
  }

  enterDelay(i: number): number {
    return this.staggering && !this.rm() ? Math.min(i, 9) * TilesTheme.STAGGER : 0;
  }

  @Builder
  tileGrid() {
    Grid(undefined, this.layoutOptions()) {
      ForEach(this.tiles, (t: TileSpec, i: number) => {
        GridItem() {
          Stack({ alignContent: Alignment.TopStart }) {
            Stack() {
              TileView({
                tile: t,
                profile: this.profile,
                dark: this.dark,
                fillHeight: true,
                reduceMotion: this.rm(),
                onAction: (a: TileAction, tt: TileSpec) => this.onTileAction(a, tt),
                onLongPress: (tt: TileSpec) => {
                  if (!this.editing) {
                    this.enterEdit();
                  }
                }
              })
            }
            .width('100%')
            .height('100%')
            .rotate({ angle: this.wiggleAngle(i) })

            if (this.editing) {
              // Catches taps while arranging so tiles do not open; the grid itself still handles the drag.
              Column()
                .width('100%')
                .height('100%')
                .onClick(() => {
                  this.toast('Hold and drag to move "' + t.title + '"');
                })

              Button({ type: ButtonType.Circle, stateEffect: true }) {
                SymbolGlyph($r('sys.symbol.xmark'))
                  .fontSize(13)
                  .fontWeight(FontWeight.Bold)
                  .fontColor([this.pal().onInk])
              }
              .width(26)
              .height(26)
              .backgroundColor(this.pal().ink)
              .shadow({ radius: 8, color: '#40000000', offsetY: 2 })
              .margin({ left: -14, top: -14 }) // outside the corner: never covers the tile's glyph
              .responseRegion({ x: -11, y: -11, width: 48, height: 48 })
              .accessibilityText('Remove ' + t.title)
              .onClick(() => this.removeTile(t))
              .transition(TransitionEffect.OPACITY.combine(TransitionEffect.scale({ x: 0.4, y: 0.4 }))
                .animation({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.DUR_SLOW) }))
            }
          }
          .width('100%')
          .height('100%')
          .opacity(this.dragIndex === i ? 0.35 : 1)
        }
        .height(this.itemH(t))
        .transition(TransitionEffect.OPACITY
          .combine(TransitionEffect.scale({ x: TilesTheme.LL_ENTER_SCALE, y: TilesTheme.LL_ENTER_SCALE }))
          .combine(TransitionEffect.translate({ y: TilesTheme.LL_ENTER_TY }))
          .animation({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_DUR), delay: this.enterDelay(i) }))
      }, (t: TileSpec) => t.id + '|' + t.size + '|' + t.subtitle + '|' + JSON.stringify(t.blocks))
    }
    .columnsTemplate(this.columnsTemplate())
    .columnsGap(this.gap())
    .rowsGap(this.gap())
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
    .clip(false)
    .width('100%')
    .padding({ left: this.pad(), right: this.pad() })
    .onAreaChange((o: Area, n: Area) => {
      const w: number = Number(n.width) - this.pad() * 2;
      if (!isNaN(w) && Math.abs(w - this.gridW) > 1) {
        this.gridW = w;
      }
    })
  }

  // ---------- sheets ----------

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

  /** Height of the bottom cluster (cards + dock + bottom inset); estimated until the first measurement. */
  clusterH(): number {
    return this.dockH > 0 ? this.dockH : this.lay().askH + this.bottomPad();
  }

  /** Space kept free under the grid: bottom cluster (dock + safe area + speaking card) + a margin of at least 30 vp
   * that also clears the soft fade, so the last tile always scrolls fully into view above the dock. */
  bottomSpace(): number {
    return this.clusterH() + Math.max(30, DOCK_FADE);
  }

  build() {
    Stack({ alignContent: Alignment.Bottom }) {
      // Full-screen Living Light page gradient (drawn under the status / navigation bars too).
      Column()
        .width('100%')
        .height('100%')
        .linearGradient({ angle: this.pal().bgGradient.angle, colors: this.pal().bgGradient.colors })
        .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])

      Scroll() {
        Column() {
          this.header()

          if (!this.editing && this.pending.length > 0) {
            Column() {
              this.pendingCard()
            }
            .padding({ left: this.pad(), right: this.pad() })
          }

          // "Tiles noticed": an in-flow card between the greeting and the grid (never floats over tiles); the
          // grid slides down when it arrives and back up when it is answered (sugShown toggles in animateTo).
          if (!this.editing && this.sugShown) {
            Column() {
              this.suggestionCard()
            }
            .width('100%')
            .padding({ left: this.pad(), right: this.pad(), bottom: Math.max(12, this.gap()) })
            .transition(TransitionEffect.OPACITY
              .combine(TransitionEffect.scale({ x: 0.96, y: 0.96 }))
              .combine(TransitionEffect.translate({ y: -16 }))
              .animation({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_SHEET_DUR) }))
          }

          if (this.tiles.length === 0) {
            this.emptyState()
          } else {
            this.tileGrid()
          }

          Blank().height(this.bottomSpace())
        }
        .width('100%')
      }
      .scrollBar(BarState.Off)
      .edgeEffect(EdgeEffect.Spring)
      .width('100%')
      .height('100%')
      .align(Alignment.Top)

      // Top scrim: tiles scrolled up fade out just under the status bar instead of being cut by a hard edge.
      Column()
        .width('100%')
        .height(this.topPad() + 18)
        .linearGradient({
          angle: 180,
          colors: [[this.pageStart(), 0], [withAlpha(this.pageStart(), 0.9), this.topPad() / (this.topPad() + 18)],
            [withAlpha(this.pageStart(), 0), 1]]
        })
        .position({ x: 0, y: 0 })
        .hitTestBehavior(HitTestMode.Transparent)

      // Page-coloured backing for the bottom cluster: tiles fade out FADE vp above the topmost card / dock and are
      // fully hidden behind it, so the suggestion sheet never floats over a clipped sliver of a tile.
      Column()
        .width('100%')
        .height(this.clusterH() + DOCK_FADE)
        .linearGradient({
          angle: 180,
          colors: [[withAlpha(this.pageEnd(), 0), 0],
            [withAlpha(this.pageEnd(), 0.6), DOCK_FADE * 0.5 / (this.clusterH() + DOCK_FADE)],
            [this.pageEnd(), DOCK_FADE / (this.clusterH() + DOCK_FADE)], [this.pageEnd(), 1]]
        })
        .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.BOTTOM])
        .hitTestBehavior(HitTestMode.Transparent)

      Column({ space: 10 }) {
        if (this.speaking.length > 0) {
          this.speakingCard()
        }
        if (!this.editing) {
          AskDock({ onOpen: (seed: string) => this.openAssistant(seed) })
            .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 40 }))
              .animation({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_SHEET_DUR) }))
        }
      }
      .width('100%')
      .padding({ left: this.pad(), right: this.pad(), bottom: this.bottomPad() })
      .onAreaChange((o: Area, n: Area) => {
        const h: number = Number(n.height);
        if (!isNaN(h) && Math.abs(h - this.dockH) > 1) {
          // grow / shrink the fade + scroll space together with the card's own enter / exit transition
          this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: this.dur(TilesTheme.LL_SHEET_DUR) },
            () => {
              this.dockH = h;
            });
        }
      })
    }
    .width('100%')
    .height('100%')
    .onAreaChange((o: Area, n: Area) => {
      const y: number = Number(n.globalPosition.y);
      if (!isNaN(y) && Math.abs(y - this.rootY) > 0.5) {
        this.rootY = y;
      }
    })
    .bindSheet(this.showAssistant, this.assistantSheet(), {
      height: SheetSize.LARGE,
      dragBar: true,
      showClose: false,
      // AssistantSheet paints its own frosted sheetBg + blur + top radius.
      backgroundColor: Color.Transparent,
      blurStyle: BlurStyle.NONE,
      radius: LengthMetrics.vp(TilesTheme.LL_RADIUS_L),
      shadow: TilesTheme.LL_SHADOW_SHEET,
      onDisappear: () => {
        this.showAssistant = false;
      }
    })
  }
}
