import { clockLabel } from '../platform/Clock';
import { Profile, TileAction, TileSpec } from '../model/Tile';
import { K_LIST, K_PROFILE, TileStore } from '../data/TileStore';
import { TileColors, ThemePalette, TilesTheme, TypeScale, withAlpha } from '../theme/TilesTheme';
import { TileView } from '../components/TileView';
import { PlatformKeys } from '../platform/TilesPlatform';
import { TileActions } from '../platform/TileActions';
import { TileHaptics } from '../platform/TileHaptics';
import { K_DARK, K_REDUCE_MOTION, platformAction } from './ShellKeys';

function sourceLabel(t: TileSpec, p: Profile): string {
  if (t.source === 'assistant') {
    return 'Made by the Tiles assistant';
  }
  if (t.source === 'adaptation') {
    return 'Added because Tiles learned from use' + (p.caregiver.length > 0 ? ' · approved by ' + p.caregiver : '');
  }
  return 'Part of ' + (p.name.length > 0 ? p.name + '\'s' : 'your') + ' home';
}

/** Single object-literal @Builder arg (passed by reference, so it stays reactive). */
class BigActionArgs {
  icon: Resource = $r('sys.symbol.speaker_wave_2');
  label: string = '';
  bg: string = '#FFFFFF';
  fg: string = '#000000';
  kind: string = '';
}

function timeLabel(ms: number): string {
  if (ms <= 0) {
    return '';
  }
  const d: Date = new Date(ms);
  return 'Added ' + d.getDate().toString() + '.' + (d.getMonth() + 1).toString() + ' at ' + clockLabel(d);
}

/**
 * Full-screen tile: the same TileSpec rendered in 'detail' mode (all blocks, larger type) on a wash of the tile's
 * color, with shell actions (read aloud, pin to top, remove from home). Route 'detail', param = tile id.
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

  runShellAction(kind: string): void {
    const t: TileSpec | null = this.tile();
    if (t === null) {
      return;
    }
    if (kind === 'speak') {
      this.speak(t);
    } else if (kind === 'remove') {
      this.remove(t);
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
    try {
      this.getUIContext().getPromptAction().showToast({
        message: t.pinned ? 'Unpinned' : 'Pinned to the top of the home',
        duration: 1800
      });
    } catch (e) {
      // best effort
    }
  }

  @Builder
  topBar() {
    Row({ space: TilesTheme.SPACE_S }) {
      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph($r('sys.symbol.chevron_left'))
          .fontSize(24)
          .fontColor([this.pal().text])
      }
      .width(TilesTheme.tapTarget(this.profile))
      .height(TilesTheme.tapTarget(this.profile))
      .backgroundColor(this.pal().surface)
      .border({ width: this.profile.highContrast ? 2 : 0, color: this.pal().border })
      .shadow({ radius: 10, color: this.pal().shadow, offsetY: 2 })
      .accessibilityText('Back to home')
      .onClick(() => this.nav.pop())

      Blank()

      if (this.tile() !== null) {
        Button({ type: ButtonType.Circle, stateEffect: true }) {
          SymbolGlyph(this.cur().pinned ? $r('sys.symbol.pin_fill') : $r('sys.symbol.pin'))
            .fontSize(22)
            .fontColor([this.pal().text])
        }
        .width(TilesTheme.tapTarget(this.profile))
        .height(TilesTheme.tapTarget(this.profile))
        .backgroundColor(this.pal().surface)
        .border({ width: this.profile.highContrast ? 2 : 0, color: this.pal().border })
        .shadow({ radius: 10, color: this.pal().shadow, offsetY: 2 })
        .accessibilityText(this.cur().pinned ? 'Unpin tile' : 'Pin tile to the top')
        .onClick(() => this.togglePin(this.cur()))
      }
    }
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: TilesTheme.SPACE_M })
  }

  @Builder
  bigAction(a: BigActionArgs) {
    Row({ space: TilesTheme.SPACE_M }) {
      SymbolGlyph(a.icon)
        .fontSize(Math.round(24 * Math.min(1.4, this.profile.textScale)))
        .fontColor([a.fg])
      Text(a.label)
        .fontSize(this.ty().body)
        .fontWeight(FontWeight.Bold)
        .fontColor(a.fg)
        .layoutWeight(1)
    }
    .width('100%')
    .constraintSize({ minHeight: TilesTheme.tapTarget(this.profile) + 8 })
    .padding({ left: 18, right: 18 })
    .borderRadius(TilesTheme.RADIUS_BUTTON + 4)
    .backgroundColor(a.bg)
    .border({ width: this.profile.highContrast ? 2 : 0, color: this.pal().border })
    .onClick(() => this.runShellAction(a.kind))
    .accessibilityGroup(true)
    .accessibilityText(a.label)
  }

  @Builder
  body() {
    Column({ space: TilesTheme.SPACE_L }) {
      TileView({
        tile: this.cur(),
        profile: this.profile,
        mode: 'detail',
        dark: this.dark,
        reduceMotion: this.reduceMotion,
        onAction: (a: TileAction, tt: TileSpec) => this.onAction(a, tt)
      })
        .width('100%')

      Row({ space: TilesTheme.SPACE_S }) {
        Circle().width(10).height(10).fill(this.colors(this.cur()).bg)
        Text(sourceLabel(this.cur(), this.profile) + (this.cur().createdAt > 0 && this.cur().source !== 'seed' ?
          ' · ' + timeLabel(this.cur().createdAt) : ''))
          .fontSize(this.ty().caption)
          .fontColor(this.pal().textMuted)
          .layoutWeight(1)
      }
      .width('100%')
      .padding({ left: 4, right: 4 })

      Column({ space: TilesTheme.SPACE_S }) {
        this.bigAction({
          icon: this.speakingTile === this.tileId ? $r('sys.symbol.speaker_wave_2_fill') :
            $r('sys.symbol.speaker_wave_2'),
          label: this.speakingTile === this.tileId ? 'Reading aloud…' : 'Read this aloud',
          bg: TilesTheme.tile('mint', this.profile.highContrast, this.dark).bg,
          fg: TilesTheme.tile('mint', this.profile.highContrast, this.dark).on,
          kind: 'speak'
        })
        this.bigAction({
          icon: $r('sys.symbol.wand_and_stars'),
          label: 'Ask Tiles to change this',
          bg: this.pal().surface,
          fg: this.pal().text,
          kind: 'ask'
        })
        this.bigAction({
          icon: $r('sys.symbol.trash'),
          label: 'Remove from home',
          bg: this.pal().surface,
          fg: this.pal().danger,
          kind: 'remove'
        })
      }
      .width('100%')
    }
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: TilesTheme.SPACE_L, bottom: 40 })
    .opacity(this.shown ? 1 : 0)
    .translate({ y: this.shown ? 0 : 24 })
  }

  @Builder
  gone() {
    Column({ space: TilesTheme.SPACE_M }) {
      SymbolGlyph($r('sys.symbol.square_grid_2x2'))
        .fontSize(48)
        .fontColor([this.pal().textMuted])
      Text('This tile is no longer on the home')
        .fontSize(this.ty().title)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().text)
        .textAlign(TextAlign.Center)
      Button('Back to home')
        .fontSize(this.ty().label)
        .fontColor(this.pal().onAccent)
        .backgroundColor(this.pal().accent)
        .height(TilesTheme.tapTarget(this.profile))
        .onClick(() => this.nav.pop())
    }
    .width('100%')
    .padding(TilesTheme.SPACE_XXL)
  }

  build() {
    NavDestination() {
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
        .align(Alignment.Top)
        .layoutWeight(1)
        .width('100%')
      }
      .width('100%')
      .height('100%')
      .linearGradient({
        angle: 180,
        colors: this.tile() !== null ?
          [[withAlpha(this.colors(this.tile() as TileSpec).bg, this.dark ? 0.32 : 0.42), 0],
            [withAlpha(this.colors(this.tile() as TileSpec).bg, this.dark ? 0.10 : 0.12), 0.45],
            [this.pal().bg, 0.8]] :
          [[this.pal().bg, 0], [this.pal().bg, 1]]
      })
    }
    .hideTitleBar(true)
    .backgroundColor(this.pal().bg)
    .onShown(() => {
      this.getUIContext().animateTo({
        curve: TilesTheme.springSheet(),
        duration: TilesTheme.dur(TilesTheme.DUR_SLOW, this.reduceMotion)
      }, () => {
        this.shown = true;
      });
    })
  }
}
