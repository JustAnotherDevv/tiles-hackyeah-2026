import { curves } from '@kit.ArkUI';
import { ComposeResult, Profile, TileAction, TileBlock, TileSpec } from '../model/Tile';
import { K_PROFILE, TileStore } from '../data/TileStore';
import {
  LL_FONT_FAMILY, ProfileLayout, ThemePalette, TileColors, TilesTheme, TypeScale, withAlpha
} from '../theme/TilesTheme';
import { TileView } from '../components/TileView';
import { tileIcon } from '../components/blocks/BlockStyle';
import { percentOf } from '../components/blocks/ProgressBlock';
import { Composer } from '../ai/Composer';
import { PlatformKeys } from '../platform/TilesPlatform';
import { TileHaptics } from '../platform/TileHaptics';
import { K_DARK, K_REDUCE_MOTION, platformAction } from './ShellKeys';

/** One transcript entry. Replaced (never mutated) so @State arrays re-render. */
class ChatMsg {
  id: string = '';
  role: string = 'user'; // user | assistant
  text: string = '';
  result: ComposeResult = new ComposeResult();
  status: string = 'none'; // none | proposed | added | sent | dismissed
}

// ---------------------------------------------------------------- Living Light motion (prototype Tiles_Stage, dir C)

const DOT_IDX: number[] = [0, 1, 2];

function easeInOut(x: number): number {
  return 0.5 - 0.5 * Math.cos(Math.PI * Math.max(0, Math.min(1, x)));
}

/** `@keyframes dots {0%,80%,100% {translateY(0)} 40% {translateY(-6px)}}` as a curve (0 -> 1 -> 0 -> rest). */
const DOTS_CURVE: curves.ICurve = curves.customCurve((t: number): number => {
  if (t < 0.4) {
    return easeInOut(t / 0.4);
  }
  if (t < 0.8) {
    return 1 - easeInOut((t - 0.4) / 0.4);
  }
  return 0;
});

/** Color-flood clip-path transition: 680 ms cubic-bezier(.3,.7,.2,1). */
const FLOOD_MS: number = 680;
const FLOOD_CURVE: curves.ICurve = curves.cubicBezierCurve(0.3, 0.7, 0.2, 1);
/** Tile birth: one block every 420 ms, flood 500 ms after the last, settle 850 ms later (prototype sendAsk). */
const BIRTH_FIRST_MS: number = 380;
const BIRTH_STEP_MS: number = 420;
const BIRTH_FLOOD_PAUSE_MS: number = 500;
const BIRTH_SETTLE_MS: number = 850;
const BIRTH_MAX_BLOCKS: number = 4;

/** Typing dots: three 7 vp accent dots, gap 4, `dots 1s ease-in-out infinite`, delays 0/140/280 ms. */
@Component
struct LLTypingDots {
  @Prop color: string = '#4F5BD5';
  @Prop reduced: boolean = false;
  @State private up: boolean = false;

  build() {
    Row({ space: 4 }) {
      ForEach(DOT_IDX, (i: number) => {
        Circle()
          .width(7)
          .height(7)
          .fill(this.color)
          .translate({ y: this.up ? -TilesTheme.LL_DOTS_TY : 0 })
          .animation({
            duration: TilesTheme.LL_DOTS_MS,
            delay: i * 140,
            curve: DOTS_CURVE,
            iterations: this.reduced ? 1 : -1
          })
      }, (i: number) => 'dot' + i)
    }
    .height(14)
    .alignItems(VerticalAlign.Bottom)
    .padding({ bottom: 2 })
    .onAppear(() => {
      if (!this.reduced) {
        this.up = true;
      }
    })
  }
}

/**
 * The tile birth (prototype "Ask Tiles" flow): a skeleton tile with the `shimmer` gradient sweep enters
 * (scale .92 -> 1, translateY 22 -> 0), assembles block by block (header first, then each block fades up 12 vp),
 * color floods in from 84%/80% (circle clip, 680 ms), then the live natively-rendered TileView settles in
 * (scale .92 -> 1, translateY 22 -> 0, LL ease 720 ms). Already-born tiles (revealed = true) render the TileView
 * directly. The hidden TileView underneath sizes the skeleton so nothing jumps when it is revealed.
 */
@Component
struct LLTileBirth {
  @Prop tile: TileSpec = new TileSpec();
  @Prop profile: Profile = new Profile();
  @Prop dark: boolean = false;
  @Prop reduceMotion: boolean = false;
  /** Revealed skeleton parts: 1 = header, 1 + i = block i. */
  @Prop built: number = 99;
  @Prop @Watch('onFlood') flooded: boolean = true;
  @Prop @Watch('onReveal') revealed: boolean = true;
  onAction: (a: TileAction, t: TileSpec) => void = (a: TileAction, t: TileSpec) => {
  };
  @State private w: number = 0;
  @State private h: number = 0;
  @State private overlayOn: boolean = false;
  @State private overlayOp: number = 1;
  @State private enterS: number = 1;
  @State private enterY: number = 0;
  @State private enterOp: number = 1;
  @State private floodS: number = 0;
  @State private tileOp: number = 1;
  @State private tileS: number = 1;
  @State private tileY: number = 0;
  @State private sweep: boolean = false;

  aboutToAppear(): void {
    if (!this.revealed) {
      this.overlayOn = true;
      this.overlayOp = 1;
      this.enterS = TilesTheme.LL_ENTER_SCALE;
      this.enterY = TilesTheme.LL_ENTER_TY;
      this.enterOp = 0;
      this.floodS = this.flooded ? 1 : 0;
      this.tileOp = 0;
      this.tileS = TilesTheme.LL_ENTER_SCALE;
      this.tileY = TilesTheme.LL_ENTER_TY;
    }
  }

  private pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }

  private col(): TileColors {
    return TilesTheme.tile(this.tile.color, this.profile.highContrast, this.dark);
  }

  private lay(): ProfileLayout {
    return TilesTheme.layoutFor(this.profile);
  }

  private small(): boolean {
    return this.tile.size === '1x1';
  }

  private titleSize(): number {
    const t: number = Math.round(19 * this.lay().fs);
    return this.small() ? Math.round(t * 0.82) : t;
  }

  private bodySize(): number {
    return Math.round(14 * this.lay().fs);
  }

  private iconSize(): number {
    return Math.round(24 * this.lay().fs);
  }

  /** Skeleton ink: muted until the color floods in, then the tile's on-color. */
  private fg(): string {
    return this.flooded ? this.col().on : this.pal().muted;
  }

  private floodR(): number {
    return Math.sqrt(Math.pow(this.w * 0.84, 2) + Math.pow(this.h * 0.8, 2));
  }

  /** Skeleton sweep on the sheet: transparent -> white .98 band -> transparent (prototype stops 35/50/65 %). */
  private shimmerStops(): Array<[ResourceColor, number]> {
    return this.dark ? this.pal().skeleton.colors :
      [['#00FFFFFF', 0.35], ['#FAFFFFFF', 0.5], ['#00FFFFFF', 0.65]];
  }

  private skeletonBlocks(): TileBlock[] {
    return this.tile.blocks.slice(0, BIRTH_MAX_BLOCKS);
  }

  private blockLabel(b: TileBlock): string {
    if (b.text.length > 0) {
      return b.text;
    }
    if (b.value.length > 0) {
      return b.value;
    }
    return b.items.length > 0 ? b.items[0] : '';
  }

  private pills(b: TileBlock): string[] {
    if (b.kind === 'buttons' && b.actions.length > 0) {
      const out: string[] = [];
      for (const a of b.actions) {
        out.push(a.label);
      }
      return out.slice(0, 3);
    }
    return b.items.slice(0, 3);
  }

  onFlood(): void {
    if (!this.flooded) {
      return;
    }
    this.getUIContext().animateTo({ duration: TilesTheme.dur(FLOOD_MS, this.reduceMotion), curve: FLOOD_CURVE },
      () => {
        this.floodS = 1;
      });
  }

  onReveal(): void {
    if (!this.revealed || !this.overlayOn) {
      return;
    }
    this.getUIContext().animateTo({
      duration: TilesTheme.dur(TilesTheme.LL_DUR, this.reduceMotion),
      curve: TilesTheme.ease(),
      onFinish: () => {
        this.overlayOn = false;
      }
    }, () => {
      this.tileOp = 1;
      this.tileS = 1;
      this.tileY = 0;
      this.overlayOp = 0;
    });
  }

  @Builder
  skeletonContent() {
    Column({ space: this.small() ? 4 : 8 }) {
      // header: icon + title
      Flex({
        direction: this.small() ? FlexDirection.Column : FlexDirection.Row,
        alignItems: this.small() ? ItemAlign.Start : ItemAlign.Center
      }) {
        SymbolGlyph(tileIcon(this.tile.icon, this.tile.type))
          .fontSize(this.iconSize())
          .fontColor([this.fg()])
          .margin({ right: this.small() ? 0 : 8, bottom: this.small() ? 4 : 0 })
        Text(this.tile.title)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(this.titleSize())
          .fontWeight(FontWeight.Bold)
          .letterSpacing(TilesTheme.letterSpacing(this.titleSize()))
          .fontColor(this.fg())
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .flexShrink(1)
      }
      .width('100%')
      .opacity(this.built >= 1 ? 1 : 0)
      .translate({ y: this.built >= 1 ? 0 : 12 })
      .animation({ duration: TilesTheme.dur(450, this.reduceMotion), curve: TilesTheme.ease() })

      if (this.tile.subtitle.length > 0 && !this.small()) {
        Text(this.tile.subtitle)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(this.bodySize())
          .fontColor(this.fg())
          .opacity(this.built >= 1 ? 0.92 : 0)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .translate({ y: this.built >= 1 ? 0 : 12 })
          .animation({ duration: TilesTheme.dur(450, this.reduceMotion), curve: TilesTheme.ease() })
      }

      ForEach(this.skeletonBlocks(), (b: TileBlock, i: number) => {
        Column() {
          if (b.kind === 'buttons' || b.kind === 'chips') {
            Row({ space: 8 }) {
              ForEach(this.pills(b), (p: string, k: number) => {
                Text(p)
                  .fontFamily(LL_FONT_FAMILY)
                  .fontSize(this.bodySize())
                  .fontWeight(FontWeight.Bold)
                  .fontColor(b.kind === 'buttons' && k === 0 ? (this.flooded ? this.col().bg1 : '#FFFFFF') :
                  this.fg())
                  .maxLines(1)
                  .padding({ left: 12, right: 12 })
                  .height(b.kind === 'buttons' ? Math.max(36, Math.round(this.bodySize() * 2.4)) : 28)
                  .borderRadius(999)
                  .backgroundColor(b.kind === 'buttons' && k === 0 ? this.fg() : '#1A000000')
              }, (p: string, k: number) => k.toString() + p)
            }
          } else if (b.kind === 'progress') {
            Stack({ alignContent: Alignment.Start }) {
              Column()
                .width(Math.max(8, percentOf(b.progress)).toString() + '%')
                .height(12)
                .borderRadius(6)
                .backgroundColor(this.fg())
            }
            .width('100%')
            .height(12)
            .borderRadius(6)
            .backgroundColor('#24000000')
          } else if (b.kind === 'list' || b.kind === 'checklist') {
            Column({ space: 4 }) {
              ForEach(b.items.slice(0, 2), (it: string, k: number) => {
                Row({ space: 10 }) {
                  Circle()
                    .width(18)
                    .height(18)
                    .fillOpacity(0)
                    .stroke(this.fg())
                    .strokeWidth(2.5)
                  Text(it)
                    .fontFamily(LL_FONT_FAMILY)
                    .fontSize(this.bodySize())
                    .fontColor(this.fg())
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                    .layoutWeight(1)
                }
              }, (it: string, k: number) => k.toString() + it)
            }
          } else if (b.kind === 'big' || b.kind === 'timer' || b.kind === 'weather') {
            Text(b.value.length > 0 ? b.value : this.blockLabel(b))
              .fontFamily(LL_FONT_FAMILY)
              .fontSize(Math.round(30 * this.lay().fs))
              .fontWeight(800)
              .fontColor(this.fg())
              .maxLines(1)
          } else {
            Text(this.blockLabel(b))
              .fontFamily(LL_FONT_FAMILY)
              .fontSize(this.bodySize())
              .fontColor(this.fg())
              .opacity(0.92)
              .maxLines(this.small() ? 1 : 2)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .opacity(this.built >= i + 2 ? 1 : 0)
        .translate({ y: this.built >= i + 2 ? 0 : 12 })
        .animation({ duration: TilesTheme.dur(450, this.reduceMotion), curve: TilesTheme.ease() })
      }, (b: TileBlock, i: number) => i.toString() + b.kind)
    }
    .width('100%')
    .height('100%')
    .padding(this.small() ? 12 : this.lay().pad)
    .alignItems(HorizontalAlign.Start)
  }

  build() {
    Stack({ alignContent: Alignment.TopStart }) {
      Column() {
        TileView({
          tile: this.tile,
          profile: this.profile,
          dark: this.dark,
          reduceMotion: this.reduceMotion,
          onAction: (a: TileAction, t: TileSpec) => this.onAction(a, t)
        })
      }
      .width('100%')
      .opacity(this.tileOp)
      .scale({ x: this.tileS, y: this.tileS })
      .translate({ y: this.tileY })
      .hitTestBehavior(this.overlayOn ? HitTestMode.None : HitTestMode.Default)
      .onAreaChange((o: Area, n: Area) => {
        const nw: number = Number(n.width);
        const nh: number = Number(n.height);
        if (!isNaN(nw) && !isNaN(nh)) {
          this.w = nw;
          this.h = nh;
        }
      })

      if (this.overlayOn && this.w > 0) {
        Stack({ alignContent: Alignment.TopStart }) {
          // Base tint: the prototype skeleton (white .55 -> .98 -> .55) sits on the tinted home; on the white
          // sheet it needs a faint ink wash underneath to read as a tile.
          Column()
            .width(this.w)
            .height(this.h)
            .backgroundColor(this.dark ? '#14FFFFFF' : '#141D2140')
            .position({ x: 0, y: 0 })
          // shimmer: background 250% wide, position 130% -> -130%, 1.4 s linear infinite
          Column()
            .width(this.w * 2.5)
            .height(this.h)
            .linearGradient({ angle: this.pal().skeleton.angle, colors: this.shimmerStops() })
            .translate({ x: this.sweep ? this.w * 1.95 : -this.w * 1.95 })
            .animation({
              duration: TilesTheme.LL_SHIMMER_MS,
              curve: Curve.Linear,
              iterations: this.reduceMotion ? 1 : -1
            })
            .position({ x: 0, y: 0 })
            .onAppear(() => {
              if (!this.reduceMotion) {
                this.sweep = true;
              }
            })

          // color flood: circle growing from 84% / 80%
          Column()
            .width(this.floodR() * 2)
            .height(this.floodR() * 2)
            .borderRadius(this.floodR())
            .linearGradient({ angle: this.col().gradient.angle, colors: this.col().gradient.colors })
            .scale({ x: this.floodS, y: this.floodS })
            .position({ x: this.w * 0.84 - this.floodR(), y: this.h * 0.8 - this.floodR() })

          this.skeletonContent()
        }
        .width(this.w)
        .height(this.h)
        .borderRadius(TilesTheme.radiusFor(this.tile.size))
        .clip(true)
        .border({ width: this.flooded ? 0 : 1, color: this.pal().line })
        .shadow(TilesTheme.LL_SHADOW_TILE)
        .opacity(this.overlayOp * this.enterOp)
        .scale({ x: this.enterS, y: this.enterS })
        .translate({ y: this.enterY })
        .hitTestBehavior(HitTestMode.None)
        .accessibilityText('Tiles is making your tile')
        .onAppear(() => {
          this.getUIContext().animateTo({
            duration: TilesTheme.dur(TilesTheme.LL_DUR, this.reduceMotion),
            curve: TilesTheme.ease()
          }, () => {
            this.enterS = 1;
            this.enterY = 0;
            this.enterOp = 1;
          });
        })
      }
    }
    .width('100%')
  }
}

/**
 * Assistant sheet ("Ask Tiles…"), Living Light (direction C): frosted sheet (sheetBg .84 + blur 26, radius 26 top),
 * header with accent sparkle + close, chat bubbles, quick-chip rows, typing dots, the tile birth (skeleton shimmer
 * -> block-by-block -> color flood -> tile settles in), ink-pill "Add to home" / "Ask Kasia to approve", and the
 * input row (pill input + mic + accent send). Generation logic is unchanged: Composer → TileSpec → TileView.
 * Senior / kid proposals go to the caregiver for approval (TileStore.propose); others are added (TileStore.addTiles).
 *
 * Voice: Core Speech Kit speech recognition is not part of the OpenHarmony SDK this app builds with, so the mic
 * button is a clearly labelled placeholder and requests are typed (or picked from chips).
 *
 * Shown by HomeView via bindSheet: AssistantSheet({ seed, onClose }). seed = '' (empty), 'mic' (voice tapped) or a
 * prompt to run immediately.
 */
@Component
export struct AssistantSheet {
  @Prop seed: string = '';
  onClose: () => void = () => {
  };
  @StorageLink(K_PROFILE) profile: Profile = new Profile();
  @StorageProp(K_DARK) dark: boolean = false;
  @StorageProp(K_REDUCE_MOTION) reduceMotion: boolean = false;
  @State messages: ChatMsg[] = [];
  @State input: string = '';
  @State thinking: boolean = false;
  @State phase: number = 0;
  @State micNote: boolean = false;
  /** Tile birth in progress for this assistant message ('' = none). Visual only. */
  @State birthId: string = '';
  @State birthBuilt: number = 0;
  @State birthFlooded: boolean = false;
  private scroller: Scroller = new Scroller();
  private ticker: number = -1;
  private genTimer: number = -1;
  private birthTimers: number[] = [];
  private seq: number = 0;

  aboutToAppear(): void {
    const s: string = this.seed.trim();
    if (s === 'mic') {
      this.micNote = true;
    } else if (s.length > 0 && s !== 'open') {
      this.send(s);
    }
  }

  aboutToDisappear(): void {
    this.stopTimers();
  }

  private stopTimers(): void {
    if (this.ticker >= 0) {
      clearInterval(this.ticker);
      this.ticker = -1;
    }
    if (this.genTimer >= 0) {
      clearTimeout(this.genTimer);
      this.genTimer = -1;
    }
    this.clearBirthTimers();
  }

  private clearBirthTimers(): void {
    for (const t of this.birthTimers) {
      clearTimeout(t);
    }
    this.birthTimers = [];
  }

  private pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }

  private ty(): TypeScale {
    return TilesTheme.type(Math.min(this.profile.textScale, 1.5));
  }

  private lay(): ProfileLayout {
    return TilesTheme.layoutFor(this.profile);
  }

  private tap(): number {
    return TilesTheme.tapTarget(this.profile);
  }

  /** Prototype askH per person (52..72 vp), never below the profile's tap target. */
  private askH(): number {
    return Math.max(this.lay().askH, TilesTheme.TAP_MIN);
  }

  private motion(): boolean {
    return !this.reduceMotion && !this.lay().reducedMotion;
  }

  private caregiverLabel(): string {
    return this.profile.caregiver.length > 0 ? this.profile.caregiver : (this.profile.id === 'kid' ? 'Mum' : 'family');
  }

  private nextId(): string {
    this.seq++;
    return 'm' + Date.now().toString(36) + '-' + this.seq.toString();
  }

  private scrollToEnd(): void {
    setTimeout(() => {
      try {
        this.scroller.scrollEdge(Edge.Bottom);
      } catch (e) {
        // layout not ready
      }
    }, 80);
  }

  private toast(msg: string): void {
    try {
      this.getUIContext().getPromptAction().showToast({ message: msg, duration: 2000 });
    } catch (e) {
      // best effort
    }
  }

  send(raw: string): void {
    const text: string = raw.trim();
    if (text.length === 0 || this.thinking) {
      return;
    }
    TileHaptics.tap();
    const u: ChatMsg = new ChatMsg();
    u.id = this.nextId();
    u.role = 'user';
    u.text = text;
    this.messages = this.messages.concat([u]);
    this.input = '';
    this.micNote = false;
    this.thinking = true;
    this.phase = 0;
    this.scrollToEnd();
    if (!this.reduceMotion) {
      this.ticker = setInterval(() => {
        this.phase = this.phase + 1;
      }, 320);
    }
    // Composer is instant and on-device; the short pause is only for the "Tiles is thinking…" moment.
    this.genTimer = setTimeout(() => {
      this.genTimer = -1;
      this.finish(text);
    }, this.reduceMotion ? 150 : 1300);
  }

  private finish(text: string): void {
    let r: ComposeResult = new ComposeResult();
    try {
      r = Composer.compose(text, this.profile);
    } catch (e) {
      r.reply = 'Sorry, I could not make a tile from that. Try one of the suggestions.';
      r.followUps = Composer.quickChips(this.profile);
    }
    if (this.ticker >= 0) {
      clearInterval(this.ticker);
      this.ticker = -1;
    }
    const a: ChatMsg = new ChatMsg();
    a.id = this.nextId();
    a.role = 'assistant';
    a.text = r.reply;
    a.result = r;
    a.status = r.tiles.length > 0 ? 'proposed' : 'none';
    const birth: boolean = r.tiles.length > 0 && this.motion();
    if (birth) {
      this.startBirth(a);
    }
    this.thinking = false;
    this.messages = this.messages.concat([a]);
    if (r.tiles.length > 0 && !birth) {
      TileHaptics.success();
    }
    this.scrollToEnd();
  }

  /** Visual tile birth timeline (prototype sendAsk): header, blocks every 420 ms, flood, settle. */
  private startBirth(a: ChatMsg): void {
    this.clearBirthTimers();
    this.birthId = a.id;
    this.birthBuilt = 0;
    this.birthFlooded = false;
    let maxBlocks: number = 0;
    for (const t of a.result.tiles) {
      maxBlocks = Math.max(maxBlocks, Math.min(BIRTH_MAX_BLOCKS, t.blocks.length));
    }
    const n: number = maxBlocks + 1;
    for (let i = 1; i <= n; i++) {
      const step: number = i;
      this.birthTimers.push(setTimeout(() => {
        if (this.birthId === a.id) {
          this.birthBuilt = step;
        }
      }, BIRTH_FIRST_MS + step * BIRTH_STEP_MS));
    }
    const tFlood: number = BIRTH_FIRST_MS + n * BIRTH_STEP_MS + BIRTH_FLOOD_PAUSE_MS;
    this.birthTimers.push(setTimeout(() => {
      if (this.birthId === a.id) {
        this.birthFlooded = true;
        TileHaptics.success();
      }
    }, tFlood));
    this.birthTimers.push(setTimeout(() => {
      if (this.birthId === a.id) {
        this.birthId = '';
        this.scrollToEnd();
      }
    }, tFlood + BIRTH_SETTLE_MS));
  }

  private setStatus(id: string, status: string): void {
    const next: ChatMsg[] = [];
    for (const m of this.messages) {
      if (m.id === id) {
        const c: ChatMsg = new ChatMsg();
        c.id = m.id;
        c.role = m.role;
        c.text = m.text;
        c.result = m.result;
        c.status = status;
        next.push(c);
      } else {
        next.push(m);
      }
    }
    this.messages = next;
  }

  private addToHome(m: ChatMsg): void {
    TileStore.get().addTiles(m.result.tiles);
    this.setStatus(m.id, 'added');
    TileHaptics.success();
    const n: number = m.result.tiles.length;
    this.toast(n === 1 ? 'Added to your home' : n.toString() + ' tiles added to your home');
  }

  private askApproval(m: ChatMsg): void {
    TileStore.get().propose(m.result);
    this.setStatus(m.id, 'sent');
    TileHaptics.success();
    this.toast('Sent to ' + this.caregiverLabel() + ' for approval');
  }

  private openCaregiver(): void {
    AppStorage.setOrCreate<string>(PlatformKeys.NAVIGATE, 'caregiver');
    this.onClose();
  }

  /** Tile previews are live renders; only read-aloud does something before the tile is added. */
  private onPreviewAction(a: TileAction, t: TileSpec): void {
    if (a.kind === 'speak') {
      platformAction(a, t);
    }
  }

  /** Chip leading icon (prototype: alarm / restaurant …, muted 20 vp). */
  private chipIcon(c: string): Resource {
    const s: string = c.toLowerCase();
    let k: string = 'star';
    if (/remind|pill|drops|aspirin|euthyrox|lek|przypomnij/.test(s)) {
      k = 'alarm';
    } else if (/dinner|kolacja|lunch|pizza|eat|food/.test(s)) {
      k = 'dinner';
    } else if (/call|zadzwo/.test(s)) {
      k = 'phone';
    } else if (/scam|oszust/.test(s)) {
      k = 'shield';
    } else if (/weather|wear|pogoda|rain/.test(s)) {
      k = 'weather';
    } else if (/timer|focus/.test(s)) {
      k = 'focus';
    } else if (/homework|shopping|list|note|batter/.test(s)) {
      k = 'list';
    } else if (/bus|tram|rondo/.test(s)) {
      k = 'bus';
    } else if (/screen time/.test(s)) {
      k = 'screentime';
    } else if (/bill|zł|pln/.test(s)) {
      k = 'calendar';
    }
    return tileIcon(k, '');
  }

  // ---------------------------------------------------------------- UI

  build() {
    Column() {
      this.header()
      Scroll(this.scroller) {
        Column({ space: 14 }) {
          if (this.messages.length === 0) {
            this.intro()
          }
          ForEach(this.messages, (m: ChatMsg) => {
            if (m.role === 'user') {
              this.userBubble(m)
            } else {
              this.assistantTurn(m)
            }
          }, (m: ChatMsg) => m.id + ':' + m.status)
          if (this.thinking) {
            this.statusRow('Tiles is thinking…')
          }
        }
        .width('100%')
        .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: 4, bottom: TilesTheme.SPACE_XL })
      }
      .layoutWeight(1)
      .width('100%')
      .align(Alignment.Top)
      .scrollBar(BarState.Off)
      .edgeEffect(EdgeEffect.Spring)

      if (this.micNote) {
        this.micBanner()
      }
      this.inputBar()
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.pal().sheetBg)
    .backdropBlur(TilesTheme.LL_BLUR)
    .borderRadius({ topLeft: TilesTheme.LL_RADIUS_L, topRight: TilesTheme.LL_RADIUS_L })
  }

  @Builder
  header() {
    Row({ space: 10 }) {
      SymbolGlyph($r('sys.symbol.wand_and_stars_fill'))
        .fontSize(24)
        .fontColor([this.pal().accent])
        .accessibilityText('Tiles assistant')
      Column({ space: 1 }) {
        Text('Ask Tiles')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(TilesTheme.letterSpacing(20))
          .fontColor(this.pal().ink)
        Text('On-device · makes tiles, not chat')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(12)
          .fontWeight(500)
          .fontColor(this.pal().muted)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph($r('sys.symbol.xmark'))
          .fontSize(22)
          .fontColor([this.pal().ink])
      }
      .width(44)
      .height(44)
      .backgroundColor(this.pal().surface2)
      .accessibilityText('Close assistant')
      .onClick(() => this.onClose())
    }
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: 6, bottom: 10 })
    .alignItems(VerticalAlign.Center)
  }

  @Builder
  intro() {
    Column({ space: 8 }) {
      Text('Hi ' + (this.profile.name.length > 0 ? this.profile.name : 'there') + '! What should Tiles make?')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().title)
        .fontWeight(FontWeight.Bold)
        .letterSpacing(TilesTheme.letterSpacing(this.ty().title))
        .fontColor(this.pal().ink)
        .width('100%')
      Text(this.profile.id === 'senior' || this.profile.id === 'kid' ?
        'Say it in your own words, in English or Polish. New tiles go to ' + this.caregiverLabel() +
          ' to approve first.' :
        'Say it in your own words, in English or Polish. Tiles turns it into a tile on your home.')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().label)
        .fontWeight(500)
        .fontColor(this.pal().muted)
        .width('100%')
        .margin({ bottom: 6 })
      this.chipRows(Composer.quickChips(this.profile))
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding({ top: 4 })
  }

  /** Quick chips (prototype): full-width rows, min 48, radius 18, 1.5 line border, muted icon + 15 px text. */
  @Builder
  chipRows(items: string[]) {
    Column({ space: 8 }) {
      ForEach(items, (c: string, i: number) => {
        Row({ space: 10 }) {
          SymbolGlyph(this.chipIcon(c))
            .fontSize(20)
            .fontColor([this.pal().muted])
          Text(c)
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(this.ty().label)
            .fontWeight(500)
            .lineHeight(Math.round(this.ty().label * 1.3))
            .fontColor(this.pal().ink)
            .maxLines(3)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
        }
        .width('100%')
        .constraintSize({ minHeight: Math.max(48, this.tap()) })
        .padding({ left: 14, right: 14, top: 10, bottom: 10 })
        .borderRadius(TilesTheme.LL_RADIUS_M)
        .border({ width: 1.5, color: this.pal().line })
        .alignItems(VerticalAlign.Center)
        .accessibilityGroup(true)
        .accessibilityText('Ask: ' + c)
        .onClick(() => this.send(c))
      }, (c: string, i: number) => i.toString() + c)
    }
    .width('100%')
  }

  /** Follow-up chips after a turn: translucent pills that wrap. */
  @Builder
  chipPills(items: string[]) {
    Flex({ wrap: FlexWrap.Wrap }) {
      ForEach(items, (c: string, i: number) => {
        Text(c)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(this.ty().label)
          .fontWeight(600)
          .fontColor(this.pal().ink)
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .padding({ left: 14, right: 14, top: 10, bottom: 10 })
          .constraintSize({ minHeight: TilesTheme.TAP_MIN, maxWidth: '100%' })
          .borderRadius(TilesTheme.LL_RADIUS_PILL)
          .backgroundColor(this.pal().surface)
          .border({ width: 1.5, color: this.pal().line })
          .margin({ right: 8, bottom: 8 })
          .accessibilityText('Ask: ' + c)
          .onClick(() => this.send(c))
      }, (c: string, i: number) => i.toString() + c)
    }
    .width('100%')
  }

  @Builder
  userBubble(m: ChatMsg) {
    Row() {
      Blank()
      Text(m.text)
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().body)
        .fontWeight(600)
        .lineHeight(Math.round(this.ty().body * 1.3))
        .fontColor(this.pal().onAccent)
        .padding({ left: 16, right: 16, top: 11, bottom: 11 })
        .borderRadius({ topLeft: 20, topRight: 20, bottomLeft: 20, bottomRight: 6 })
        .backgroundColor(this.pal().accent)
        .shadow(TilesTheme.LL_SHADOW_SOFT)
        .constraintSize({ maxWidth: '82%' })
    }
    .width('100%')
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 12 }))
      .animation({ duration: TilesTheme.dur(TilesTheme.LL_DUR / 2, !this.motion()), curve: TilesTheme.ease() }))
  }

  @Builder
  statusRow(label: string) {
    Row({ space: 10 }) {
      LLTypingDots({ color: this.pal().accent, reduced: !this.motion() })
      Text(label)
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(15)
        .fontWeight(600)
        .fontColor(this.pal().muted)
    }
    .alignItems(VerticalAlign.Center)
    .padding({ top: 2, bottom: 2 })
    .accessibilityGroup(true)
    .accessibilityText(label)
  }

  @Builder
  assistantBubble(m: ChatMsg) {
    Row({ space: 8 }) {
      Stack() {
        SymbolGlyph($r('sys.symbol.wand_and_stars_fill'))
          .fontSize(15)
          .fontColor(['#2B1A5E'])
      }
      .width(28)
      .height(28)
      .borderRadius(14)
      .linearGradient({ angle: this.pal().creature.angle, colors: this.pal().creature.colors })
      .margin({ top: 4 })
      .accessibilityLevel('no')

      Text(m.text)
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().body)
        .fontWeight(500)
        .lineHeight(Math.round(this.ty().body * 1.35))
        .fontColor(this.pal().ink)
        .padding({ left: 16, right: 16, top: 11, bottom: 11 })
        .borderRadius({ topLeft: 6, topRight: 20, bottomLeft: 20, bottomRight: 20 })
        .backgroundColor(this.pal().surface)
        .border({ width: this.profile.highContrast ? 1.5 : 1, color: this.pal().line })
        .shadow(TilesTheme.LL_SHADOW_SOFT)
        .constraintSize({ maxWidth: '86%' })
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
  }

  @Builder
  assistantTurn(m: ChatMsg) {
    Column({ space: 12 }) {
      if (m.id === this.birthId) {
        this.statusRow(this.birthFlooded ? 'Almost ready…' : 'Making your tile…')
      } else {
        this.assistantBubble(m)
      }

      if (m.result.tiles.length > 0) {
        Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
          ForEach(m.result.tiles, (t: TileSpec) => {
            Column() {
              LLTileBirth({
                tile: t,
                profile: this.profile,
                dark: this.dark,
                reduceMotion: !this.motion(),
                built: m.id === this.birthId ? this.birthBuilt : 99,
                flooded: m.id !== this.birthId || this.birthFlooded,
                revealed: m.id !== this.birthId,
                onAction: (a: TileAction, tt: TileSpec) => this.onPreviewAction(a, tt)
              })
            }
            .width(t.size === '1x1' && this.profile.columns > 2 ? '48.5%' : '100%')
            .margin({ bottom: this.lay().gap })
            .opacity(m.status === 'dismissed' ? 0.4 : 1)
          }, (t: TileSpec) => t.id)
        }
        .width('100%')

        if (m.id !== this.birthId) {
          this.proposalActions(m)
        }
      }

      if (m.result.followUps.length > 0 && m.status !== 'proposed' && m.id !== this.birthId) {
        this.chipPills(m.result.followUps)
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: TilesTheme.LL_ENTER_TY }))
      .animation({ duration: TilesTheme.dur(TilesTheme.LL_DUR, !this.motion()), curve: TilesTheme.ease() }))
  }

  /** Primary LL action: ink pill (like the ask dock), sheet shadow. */
  @Builder
  inkPill(icon: Resource, label: string, a11y: string, action: () => void) {
    Button({ type: ButtonType.Capsule, stateEffect: true }) {
      Row({ space: 10 }) {
        SymbolGlyph(icon)
          .fontSize(22)
          .fontColor([this.pal().onInk])
        Text(label)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(Math.round(17 * Math.min(Math.max(this.lay().fs, 1), 1.2)))
          .fontWeight(FontWeight.Bold)
          .letterSpacing(TilesTheme.letterSpacing(17))
          .fontColor(this.pal().onInk)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .flexShrink(1)
      }
      .padding({ left: 20, right: 20 })
    }
    .width('100%')
    .height(Math.max(this.askH(), this.tap()))
    .backgroundColor(this.pal().ink)
    .shadow(TilesTheme.LL_SHADOW_SHEET)
    .accessibilityText(a11y)
    .onClick(() => action())
  }

  @Builder
  softPill(label: string, a11y: string, action: () => void) {
    Button({ type: ButtonType.Capsule, stateEffect: true }) {
      Text(label)
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().label)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().ink)
        .maxLines(1)
    }
    .height(TilesTheme.TAP_MIN)
    .layoutWeight(1)
    .backgroundColor(this.pal().surface2)
    .accessibilityText(a11y)
    .onClick(() => action())
  }

  @Builder
  proposalActions(m: ChatMsg) {
    if (m.status === 'proposed') {
      Column({ space: 10 }) {
        if (m.result.needsApproval) {
          this.inkPill($r('sys.symbol.person_2_fill'), 'Ask ' + this.caregiverLabel() + ' to approve',
            'Ask ' + this.caregiverLabel() + ' to approve the new tile', () => this.askApproval(m))
        } else {
          this.inkPill($r('sys.symbol.plus'),
            m.result.tiles.length > 1 ? 'Add ' + m.result.tiles.length.toString() + ' tiles to home' : 'Add to home',
            'Add the new tile to your home screen', () => this.addToHome(m))
        }
        Row({ space: 8 }) {
          this.softPill('Not now', 'Not now', () => this.setStatus(m.id, 'dismissed'))
          if (m.result.followUps.length > 0) {
            this.softPill('Change it', 'Show ways to change this tile', () => this.setStatus(m.id, 'none'))
          }
        }
        .width('100%')
      }
      .width('100%')
      .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: TilesTheme.LL_ENTER_TY }))
        .animation({ duration: TilesTheme.dur(TilesTheme.LL_DUR, !this.motion()), curve: TilesTheme.ease() }))
    } else if (m.status === 'added' || m.status === 'sent') {
      Column({ space: 2 }) {
        Row({ space: 12 }) {
          SymbolGlyph($r('sys.symbol.checkmark_circle_fill'))
            .fontSize(26)
            .fontColor([this.pal().okInk])
          Text(m.status === 'added' ? 'Added to your home' :
            'Waiting for ' + this.caregiverLabel() + ' to approve')
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(15)
            .fontWeight(FontWeight.Bold)
            .lineHeight(20)
            .fontColor(this.pal().okInk)
            .layoutWeight(1)
        }
        .width('100%')
        .constraintSize({ minHeight: 30 })

        if (m.status === 'sent') {
          Text('See ' + this.caregiverLabel() + '\'s phone →')
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(this.ty().label)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.pal().okInk)
            .decoration({ type: TextDecorationType.Underline, color: this.pal().okInk })
            .constraintSize({ minHeight: TilesTheme.TAP_MIN })
            .padding({ left: 38 })
            .accessibilityText('Open ' + this.caregiverLabel() + '\'s approval screen')
            .onClick(() => this.openCaregiver())
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .borderRadius(TilesTheme.LL_RADIUS_M)
      .backgroundColor(this.pal().okSoft)
      .transition(TransitionEffect.OPACITY.combine(TransitionEffect.scale({ x: 0.96, y: 0.96 }))
        .animation({ duration: TilesTheme.dur(500, !this.motion()), curve: curves.cubicBezierCurve(0.34, 1.4, 0.5, 1) }))
    }
  }

  @Builder
  micBanner() {
    Row({ space: 10 }) {
      SymbolGlyph($r('sys.symbol.mic_fill'))
        .fontSize(20)
        .fontColor([this.pal().accent])
      Text('Voice input is a placeholder in this build (speech recognition is not in the OpenHarmony SDK). ' +
        'Type, or tap a suggestion.')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().caption)
        .fontWeight(500)
        .fontColor(this.pal().ink)
        .layoutWeight(1)
      Button({ type: ButtonType.Circle }) {
        SymbolGlyph($r('sys.symbol.xmark'))
          .fontSize(16)
          .fontColor([this.pal().muted])
      }
      .width(TilesTheme.TAP_MIN)
      .height(TilesTheme.TAP_MIN)
      .backgroundColor(Color.Transparent)
      .accessibilityText('Hide voice note')
      .onClick(() => {
        this.micNote = false;
      })
    }
    .width('100%')
    .padding({ left: 14, right: 4, top: 4, bottom: 4 })
    .margin({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, bottom: 8 })
    .constraintSize({ maxWidth: '100%' })
    .borderRadius(TilesTheme.LL_RADIUS_M)
    .backgroundColor(this.pal().surface2)
    .alignItems(VerticalAlign.Center)
  }

  @Builder
  inputBar() {
    Row({ space: 8 }) {
      TextInput({ text: this.input, placeholder: 'Remind me, plan, call…' })
        .layoutWeight(1)
        .height(this.askH())
        .padding({ left: 18, right: 18 })
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(17)
        .fontColor(this.pal().ink)
        .placeholderColor(withAlpha(this.pal().muted, 0.85))
        .placeholderFont({ size: 17, family: LL_FONT_FAMILY })
        .caretColor(this.pal().accent)
        .backgroundColor(this.pal().inputBg)
        .border({ width: 1.5, color: this.pal().line })
        .borderRadius(TilesTheme.LL_RADIUS_PILL)
        .enterKeyType(EnterKeyType.Send)
        .maxLength(400)
        .id('assistantInput')
        .accessibilityText('Type a request for Tiles')
        .onChange((v: string) => {
          this.input = v;
        })
        .onSubmit(() => this.send(this.input))

      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph($r('sys.symbol.mic_fill'))
          .fontSize(24)
          .fontColor([this.pal().ink])
      }
      .width(this.askH())
      .height(this.askH())
      .backgroundColor(this.pal().surface2)
      .accessibilityText('Voice input (placeholder in this build)')
      .onClick(() => {
        this.micNote = true;
        TileHaptics.tap();
      })

      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph($r('sys.symbol.arrow_up'))
          .fontSize(24)
          .fontColor([this.pal().onAccent])
      }
      .width(this.askH())
      .height(this.askH())
      .backgroundColor(this.input.trim().length > 0 && !this.thinking ? this.pal().accent :
        withAlpha(this.pal().accent, 0.45))
      .animation({ duration: 200, curve: Curve.Linear })
      .enabled(this.input.trim().length > 0 && !this.thinking)
      .id('assistantSend')
      .accessibilityText('Make the tile')
      .onClick(() => this.send(this.input))
    }
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: 8, bottom: 20 })
    .alignItems(VerticalAlign.Center)
  }
}
