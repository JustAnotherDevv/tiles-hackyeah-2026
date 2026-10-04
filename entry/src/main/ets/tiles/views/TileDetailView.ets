import { clockLabel } from '../platform/Clock';
import { Profile, TileAction, TileSpec } from '../model/Tile';
import { K_LIST, K_PROFILE, TileStore } from '../data/TileStore';
import { LL_FONT_FAMILY, TileColors, ThemePalette, TilesTheme, TypeScale, withAlpha } from '../theme/TilesTheme';
import { TileView } from '../components/TileView';
import { PlatformKeys } from '../platform/TilesPlatform';
import { TileActions } from '../platform/TileActions';
import { TileHaptics } from '../platform/TileHaptics';
import { Speech } from '../platform/Speech';
import { K_DARK, K_REDUCE_MOTION, LLPageMotion, llToast, platformAction } from './ShellKeys';
import { LengthMetrics, window } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';

function sourceLabel(t: TileSpec, p: Profile): string {
  if (t.source === 'assistant') {
    return 'Made by the Tiles assistant';
  }
  if (t.source === 'adaptation') {
    return 'Added because Tiles learned from use' + (p.caregiver.length > 0 ? ' · approved by ' + p.caregiver : '');
  }
  return 'Part of ' + (p.name.length > 0 ? p.name + '\'s' : 'your') + ' home';
}

function timeLabel(ms: number): string {
  if (ms <= 0) {
    return '';
  }
  const d: Date = new Date(ms);
  return 'Added ' + d.getDate().toString() + '.' + (d.getMonth() + 1).toString() + ' at ' + clockLabel(d);
}

/** Single object-literal @Builder arg (passed by reference, so it stays reactive). */
class ListRowArgs {
  icon: Resource = $r('sys.symbol.chevron_right');
  label: string = '';
  sub: string = '';
  iconBg: string = '#121D2140';
  iconFg: string = '#1D2140';
  fg: string = '#1D2140';
  kind: string = '';
  chevron: boolean = true;
}

/**
 * Living Light voice wave: 5 rounded bars (4 x 28 vp) pulsing scaleY .3 -> 1 with a 110 ms stagger
 * (prototype keyframes `wave .9s ease-in-out infinite`). Reduced motion shows static bars.
 */
@Component
export struct WaveBars {
  @Prop color: string = '#4F5BD5';
  @Prop reduceMotion: boolean = false;
  @Prop barH: number = 28;
  @State on: boolean = false;
  private readonly bars: number[] = [0, 1, 2, 3, 4];
  private readonly still: number[] = [0.45, 0.8, 1.0, 0.7, 0.4];

  build() {
    Row({ space: 3 }) {
      ForEach(this.bars, (i: number) => {
        Column()
          .width(4)
          .height(this.barH)
          .borderRadius(2)
          .backgroundColor(this.color)
          .scale({ y: this.reduceMotion ? this.still[i] : (this.on ? 1.0 : 0.3) })
          .animation({
            duration: TilesTheme.LL_WAVE_MS / 2,
            curve: Curve.EaseInOut,
            delay: i * 110,
            iterations: this.reduceMotion ? 1 : -1,
            playMode: PlayMode.Alternate
          })
      }, (i: number) => i.toString())
    }
    .height(this.barH)
    .alignItems(VerticalAlign.Center)
    .onAppear(() => {
      if (!this.reduceMotion) {
        setTimeout(() => {
          this.on = true;
        }, 16);
      }
    })
    .accessibilityLevel('no')
  }
}

/**
 * Full-screen tile (route 'detail', param = tile id), Living Light: the tile itself as a large hero card on the
 * page gradient (palette gradient, radius 26, soft indigo shadow), pill actions (read aloud shows the voice
 * wave while speaking) and a frosted-glass action list.
 */
@Component
export struct TileDetailView {
  @Consume('tilesNav') nav: NavPathStack;
  @Prop tileId: string = '';
  @StorageLink(K_LIST) tiles: TileSpec[] = [];
  @StorageLink(K_PROFILE) profile: Profile = new Profile();
  @StorageProp(K_DARK) dark: boolean = false;
  @StorageProp(K_REDUCE_MOTION) reduceMotion: boolean = false;
  @StorageProp(PlatformKeys.SPEAKING_TILE) speakingTile: string = '';
  @State shown: boolean = false;
  @State actionsShown: boolean = false;
  @State llMotion: LLPageMotion = new LLPageMotion();
  /** Status-bar height (vp) and where our root actually starts: the window is full-screen (immersive). */
  @State sysTop: number = 0;
  @State rootY: number = 0;

  aboutToAppear(): void {
    try {
      const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
      window.getLastWindow(ctx).then((win: window.Window) => {
        const area: window.AvoidArea = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);
        this.sysTop = this.getUIContext().px2vp(area.topRect.height);
      }).catch(() => {
      });
    } catch (e) {
      // no window (preview)
    }
  }

  /** Extra top padding only when the page really lays out under the status bar. */
  topPad(): number {
    return Math.max(0, this.sysTop - this.rootY);
  }

  tile(): TileSpec | null {
    for (const t of this.tiles) {
      if (t.id === this.tileId) {
        return t;
      }
    }
    return null;
  }

  /** Current tile (or an empty spec once it was removed). */
  cur(): TileSpec {
    const t: TileSpec | null = this.tile();
    return t !== null ? t : new TileSpec();
  }

  speaking(): boolean {
    return this.speakingTile.length > 0 && this.speakingTile === this.tileId;
  }

  runShellAction(kind: string): void {
    const t: TileSpec | null = this.tile();
    if (t === null) {
      return;
    }
    if (kind === 'speak') {
      if (this.speaking()) {
        Speech.stop();
      } else {
        this.speak(t);
      }
    } else if (kind === 'remove') {
      this.remove(t);
    } else if (kind === 'pin') {
      this.togglePin(t);
    } else if (kind === 'ask') {
      this.nav.pop();
      AppStorage.setOrCreate<string>('tiles.assistantSeed', 'Change "' + t.title + '": #' + Date.now().toString());
    }
  }

  pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }

  ty(): TypeScale {
    return TilesTheme.type(this.profile.textScale);
  }

  colors(t: TileSpec): TileColors {
    return TilesTheme.tile(t.color, this.profile.highContrast, this.dark);
  }

  tap(): number {
    return TilesTheme.tapTarget(this.profile);
  }

  onAction(a: TileAction, t: TileSpec): void {
    if (a.kind === 'open') {
      return; // already open
    }
    if (a.kind === 'navigate' && a.arg === 'assistant') {
      this.nav.pop();
      AppStorage.setOrCreate<string>('tiles.assistantSeed', 'open#' + Date.now().toString());
      return;
    }
    if (a.kind === 'dismiss' && t.type !== 'guardian') {
      this.nav.pop();
    }
    platformAction(a, t);
  }

  speak(t: TileSpec): void {
    const a: TileAction = new TileAction();
    a.kind = 'speak';
    a.label = 'Read aloud';
    a.arg = TileActions.speakTextFor(t);
    platformAction(a, t);
  }

  remove(t: TileSpec): void {
    this.getUIContext().showAlertDialog({
      title: 'Remove this tile?',
      message: '"' + t.title + '" will disappear from the home. You can ask Tiles to make it again any time.',
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: 'Keep',
        action: () => {
        }
      },
      secondaryButton: {
        value: 'Remove',
        fontColor: this.pal().danger,
        action: () => {
          this.nav.pop();
          const a: TileAction = new TileAction();
          a.kind = 'dismiss';
          a.label = 'Remove';
          platformAction(a, t);
        }
      }
    });
  }

  togglePin(t: TileSpec): void {
    TileHaptics.tap();
    TileStore.get().togglePin(t.id);
    const idx: number = this.tiles.findIndex((x: TileSpec) => x.id === t.id);
    if (!t.pinned && idx > 0) {
      TileStore.get().moveTile(idx, 0);
    }
    llToast(this.getUIContext(), t.pinned ? 'Unpinned' : 'Pinned to the top of the home', 1800);
  }

  /** Frosted round icon button (glass surface + blur + soft shadow). */
  @Builder
  glassCircle(icon: Resource, label: string, kind: string) {
    Row() {
      SymbolGlyph(icon)
        .fontSize(24)
        .fontColor([this.pal().ink])
    }
    .width(this.tap())
    .height(this.tap())
    .justifyContent(FlexAlign.Center)
    .borderRadius(this.tap() / 2)
    .backgroundColor(this.pal().surface)
    .backdropBlur(TilesTheme.LL_BLUR)
    .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().line })
    .shadow(TilesTheme.LL_SHADOW_SOFT)
    .accessibilityText(label)
    .onClick(() => {
      if (kind === 'back') {
        this.nav.pop();
      } else {
        this.runShellAction(kind);
      }
    })
  }

  @Builder
  topBar() {
    Row({ space: TilesTheme.SPACE_S }) {
      this.glassCircle($r('sys.symbol.chevron_left'), 'Back to home', 'back')
      Blank()
      if (this.tile() !== null) {
        this.glassCircle(this.cur().pinned ? $r('sys.symbol.pin_fill') : $r('sys.symbol.pin'),
          this.cur().pinned ? 'Unpin tile' : 'Pin tile to the top', 'pin')
      }
    }
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: TilesTheme.SPACE_M + this.topPad() })
  }

  /** Primary pill: Read aloud (ink) -> while speaking a glass pill with the accent voice wave + Stop. */
  @Builder
  speakPill() {
    Row({ space: 10 }) {
      if (this.speaking()) {
        WaveBars({ color: this.pal().accent, reduceMotion: this.reduceMotion, barH: 24 })
        Text('Reading aloud…')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(this.ty().label)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().ink)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
        Row() {
          SymbolGlyph($r('sys.symbol.square_fill'))
            .fontSize(18)
            .fontColor([this.pal().onInk])
        }
        .width(36)
        .height(36)
        .justifyContent(FlexAlign.Center)
        .borderRadius(18)
        .backgroundColor(this.pal().ink)
      } else {
        SymbolGlyph($r('sys.symbol.speaker_wave_2_fill'))
          .fontSize(Math.round(22 * Math.min(1.4, this.profile.textScale)))
          .fontColor([this.pal().onInk])
        Text('Read aloud')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(this.ty().label)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(TilesTheme.letterSpacing(this.ty().label))
          .fontColor(this.pal().onInk)
          .maxLines(1)
      }
    }
    .layoutWeight(1)
    .height(this.tap() + 4)
    .padding({ left: 18, right: this.speaking() ? 8 : 18 })
    .justifyContent(FlexAlign.Center)
    .borderRadius(TilesTheme.LL_RADIUS_PILL)
    .backgroundColor(this.speaking() ? this.pal().surface : this.pal().ink)
    .backdropBlur(this.speaking() ? TilesTheme.LL_BLUR : 0)
    .border({ width: this.speaking() || this.profile.highContrast ? 1 : 0, color: this.pal().line })
    .shadow(TilesTheme.LL_SHADOW_SOFT)
    .animation({ duration: TilesTheme.dur(TilesTheme.DUR_MED, this.reduceMotion), curve: TilesTheme.ease() })
    .onClick(() => this.runShellAction('speak'))
    .accessibilityGroup(true)
    .accessibilityText(this.speaking() ? 'Reading aloud. Tap to stop' : 'Read this tile aloud')
  }

  /** Secondary pill: Ask Tiles to change this (glass, accent sparkle). */
  @Builder
  askPill() {
    Row({ space: 8 }) {
      SymbolGlyph($r('sys.symbol.wand_and_stars'))
        .fontSize(Math.round(22 * Math.min(1.4, this.profile.textScale)))
        .fontColor([this.pal().accent])
      Text('Change')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().label)
        .fontWeight(FontWeight.Bold)
        .letterSpacing(TilesTheme.letterSpacing(this.ty().label))
        .fontColor(this.pal().ink)
        .maxLines(1)
    }
    .height(this.tap() + 4)
    .padding({ left: 18, right: 20 })
    .justifyContent(FlexAlign.Center)
    .borderRadius(TilesTheme.LL_RADIUS_PILL)
    .backgroundColor(this.pal().surface)
    .backdropBlur(TilesTheme.LL_BLUR)
    .border({ width: 1, color: this.pal().line })
    .shadow(TilesTheme.LL_SHADOW_SOFT)
    .onClick(() => this.runShellAction('ask'))
    .accessibilityGroup(true)
    .accessibilityText('Ask Tiles to change this tile')
  }

  @Builder
  listRow(a: ListRowArgs) {
    Row({ space: 12 }) {
      Row() {
        SymbolGlyph(a.icon)
          .fontSize(20)
          .fontColor([a.iconFg])
      }
      .width(36)
      .height(36)
      .justifyContent(FlexAlign.Center)
      .borderRadius(18)
      .backgroundColor(a.iconBg)

      Column({ space: 2 }) {
        Text(a.label)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(this.ty().body)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(TilesTheme.letterSpacing(this.ty().body))
          .fontColor(a.fg)
        if (a.sub.length > 0) {
          Text(a.sub)
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(this.ty().caption)
            .fontColor(this.pal().muted)
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      if (a.chevron) {
        SymbolGlyph($r('sys.symbol.chevron_right'))
          .fontSize(18)
          .fontColor([this.pal().muted])
      }
    }
    .width('100%')
    .constraintSize({ minHeight: Math.max(56, this.tap()) })
    .padding({ left: 16, right: 14, top: 8, bottom: 8 })
    .onClick(() => {
      if (a.kind.length > 0) {
        this.runShellAction(a.kind);
      }
    })
    .accessibilityGroup(true)
    .accessibilityText(a.label + (a.sub.length > 0 ? '. ' + a.sub : ''))
  }

  @Builder
  sep() {
    Divider()
      .strokeWidth(1)
      .color(this.pal().line)
      .margin({ left: 16, right: 16 })
  }

  @Builder
  body() {
    Column({ space: TilesTheme.SPACE_L }) {
      // ----- hero: the tile itself, palette gradient, radius 26, Living Light shadow -----
      Column() {
        TileView({
          tile: this.cur(),
          profile: this.profile,
          mode: 'detail',
          dark: this.dark,
          reduceMotion: this.reduceMotion,
          onAction: (a: TileAction, tt: TileSpec) => this.onAction(a, tt)
        })
          .width('100%')
      }
      .width('100%')
      .borderRadius(TilesTheme.LL_RADIUS_L)
      .linearGradient({
        angle: this.colors(this.cur()).gradient.angle,
        colors: this.colors(this.cur()).gradient.colors
      })
      .shadow(TilesTheme.LL_SHADOW_TILE)
      .clip(false)

      Column({ space: TilesTheme.SPACE_L }) {
        // ----- pill actions -----
        Row({ space: TilesTheme.SPACE_S }) {
          this.speakPill()
          if (!this.speaking()) {
            this.askPill()
          }
        }
        .width('100%')

        // ----- glass action list -----
        Column() {
          this.listRow({
            icon: this.cur().pinned ? $r('sys.symbol.pin_fill') : $r('sys.symbol.pin'),
            label: this.cur().pinned ? 'Unpin from the top' : 'Pin to the top',
            sub: this.cur().pinned ? 'Stays first on the home' : 'Keep it first on the home',
            iconBg: this.pal().surface2,
            iconFg: this.pal().accent,
            fg: this.pal().ink,
            kind: 'pin',
            chevron: false
          })
          this.sep()
          this.listRow({
            icon: $r('sys.symbol.wand_and_stars'),
            label: 'Change with Tiles',
            sub: 'Bigger, simpler, new time',
            iconBg: this.pal().surface2,
            iconFg: this.pal().accent,
            fg: this.pal().ink,
            kind: 'ask',
            chevron: true
          })
          this.sep()
          this.listRow({
            icon: $r('sys.symbol.trash'),
            label: 'Remove from home',
            sub: '',
            iconBg: this.pal().dangerSoft,
            iconFg: this.pal().danger,
            fg: this.pal().danger,
            kind: 'remove',
            chevron: false
          })
        }
        .width('100%')
        .padding({ top: 4, bottom: 4 })
        .borderRadius(TilesTheme.LL_RADIUS_L)
        .backgroundColor(this.pal().surface)
        .backdropBlur(TilesTheme.LL_BLUR)
        .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().line })
        .shadow(TilesTheme.LL_SHADOW_SOFT)

        // ----- provenance -----
        Row({ space: TilesTheme.SPACE_S }) {
          Circle()
            .width(10)
            .height(10)
            .fill(this.colors(this.cur()).bg2)
          Text(sourceLabel(this.cur(), this.profile) + (this.cur().createdAt > 0 && this.cur().source !== 'seed' ?
            ' · ' + timeLabel(this.cur().createdAt) : ''))
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(this.ty().caption)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.pal().muted)
            .layoutWeight(1)
        }
        .width('100%')
        .padding({ left: 8, right: 8 })
      }
      .width('100%')
      .opacity(this.actionsShown ? 1 : 0)
      .translate({ y: this.actionsShown ? 0 : TilesTheme.LL_ENTER_TY })
    }
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: TilesTheme.SPACE_L, bottom: 64 })
  }

  @Builder
  gone() {
    Column({ space: TilesTheme.SPACE_M }) {
      SymbolGlyph($r('sys.symbol.square_grid_2x2'))
        .fontSize(48)
        .fontColor([this.pal().muted])
      Text('This tile is no longer on the home')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().title)
        .fontWeight(FontWeight.Bold)
        .letterSpacing(TilesTheme.letterSpacing(this.ty().title))
        .fontColor(this.pal().ink)
        .textAlign(TextAlign.Center)
      Row() {
        Text('Back to home')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(this.ty().label)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().onInk)
      }
      .height(this.tap())
      .padding({ left: 24, right: 24 })
      .borderRadius(TilesTheme.LL_RADIUS_PILL)
      .backgroundColor(this.pal().ink)
      .onClick(() => this.nav.pop())
    }
    .width('100%')
    .padding(TilesTheme.SPACE_XXL)
  }

  build() {
    NavDestination() {
      Stack({ alignContent: Alignment.Top }) {
        // soft wash of the tile's palette behind the hero
        Column()
          .width('100%')
          .height(360)
          .linearGradient({
            angle: 180,
            // Ramps in from transparent: the window is not full screen, so a wash that starts at full strength
            // draws a hard edge against the plain status bar.
            colors: [[withAlpha(this.colors(this.cur()).bg2, 0.0), 0.0],
              [withAlpha(this.colors(this.cur()).bg2, this.dark ? 0.22 : 0.38), 0.4],
              [withAlpha(this.colors(this.cur()).bg1, 0.0), 1.0]]
          })
          .hitTestBehavior(HitTestMode.Transparent)

        Column() {
          this.topBar()
          Scroll() {
            if (this.tile() !== null) {
              this.body()
            } else {
              this.gone()
            }
          }
          .scrollBar(BarState.Off)
          .edgeEffect(EdgeEffect.Spring)
          .fadingEdge(true, { fadingEdgeLength: LengthMetrics.vp(28) })
          .align(Alignment.Top)
          .layoutWeight(1)
          .width('100%')
        }
        .width('100%')
        .height('100%')
        .onAreaChange((o: Area, n: Area) => {
          const y: number = Number(n.globalPosition.y);
          if (!isNaN(y) && Math.abs(y - this.rootY) > 0.5) {
            this.rootY = y;
          }
        })
      }
      .width('100%')
      .height('100%')
      .linearGradient({ angle: this.pal().bgGradient.angle, colors: this.pal().bgGradient.colors })
      .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
    }
    .hideTitleBar(true)
    .backgroundColor(this.pal().bg)
    .opacity(this.llMotion.opacity)
    .scale({ x: this.llMotion.scale, y: this.llMotion.scale })
    .translate({ y: this.llMotion.ty })
    .customTransition((op: NavigationOperation, isEnter: boolean) =>
      this.llMotion.transitions(this.getUIContext(), op, isEnter))
    .onShown(() => {
      const d: number = TilesTheme.dur(TilesTheme.LL_DUR, this.reduceMotion);
      this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: d }, () => {
        this.shown = true;
      });
      this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: d, delay: this.reduceMotion ? 0 : 90 },
        () => {
          this.actionsShown = true;
        });
    })
  }
}
