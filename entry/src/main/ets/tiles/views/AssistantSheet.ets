import { ComposeResult, Profile, TileAction, TileSpec } from '../model/Tile';
import { K_PROFILE, TileStore } from '../data/TileStore';
import { ThemePalette, TilesTheme, TypeScale, withAlpha } from '../theme/TilesTheme';
import { TileView } from '../components/TileView';
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

const DOT_COLORS: string[] = ['#FFC83D', '#FF6B5A', '#9B7BFF'];
const GEN_STEPS_EN: string[] = ['Reading your request…', 'Picking a layout…', 'Choosing colors…', 'Adding buttons…'];

/**
 * Assistant sheet ("Ask Tiles…"): chat transcript, quick chips per profile, typed input with a labelled voice
 * placeholder, the "Tiles is making your tile…" generation animation and natively rendered tile proposals
 * (generative UI via Composer → TileSpec → TileView). Senior / kid proposals go to the caregiver for approval
 * (TileStore.propose); others are added directly (TileStore.addTiles).
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
  private scroller: Scroller = new Scroller();
  private ticker: number = -1;
  private genTimer: number = -1;
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
  }

  private pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }

  private ty(): TypeScale {
    return TilesTheme.type(Math.min(this.profile.textScale, 1.5));
  }

  private tap(): number {
    return TilesTheme.tapTarget(this.profile);
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
    // Composer is instant and on-device; the short pause is only for the "making your tile" moment.
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
    this.thinking = false;
    this.messages = this.messages.concat([a]);
    if (r.tiles.length > 0) {
      TileHaptics.success();
    }
    this.scrollToEnd();
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

  // ---------------------------------------------------------------- UI

  build() {
    Column() {
      this.header()
      Scroll(this.scroller) {
        Column({ space: TilesTheme.SPACE_M }) {
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
            this.generating()
          }
        }
        .width('100%')
        .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: TilesTheme.SPACE_S,
          bottom: TilesTheme.SPACE_XL })
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
    .backgroundColor(this.pal().bg)
  }

  @Builder
  header() {
    Row({ space: TilesTheme.SPACE_M }) {
      Stack() {
        SymbolGlyph($r('sys.symbol.wand_and_stars_fill'))
          .fontSize(24)
          .fontColor(['#FFFFFF'])
      }
      .width(44)
      .height(44)
      .borderRadius(22)
      .linearGradient({
        angle: 135,
        colors: this.profile.highContrast ? [[this.pal().accent, 0], [this.pal().accent, 1]] :
          [['#FFC83D', 0], ['#FF6B5A', 0.4], ['#9B7BFF', 1]]
      })
      .accessibilityText('Tiles assistant')

      Column({ space: 2 }) {
        Text('Ask Tiles')
          .fontSize(this.ty().title)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().text)
        Text('On-device generator · makes tiles, not chat')
          .fontSize(this.ty().caption)
          .fontColor(this.pal().textMuted)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph($r('sys.symbol.xmark'))
          .fontSize(22)
          .fontColor([this.pal().text])
      }
      .width(TilesTheme.TAP_MIN)
      .height(TilesTheme.TAP_MIN)
      .backgroundColor(this.pal().surfaceAlt)
      .accessibilityText('Close assistant')
      .onClick(() => this.onClose())
    }
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: TilesTheme.SPACE_L, bottom: TilesTheme.SPACE_S })
  }

  @Builder
  intro() {
    Column({ space: TilesTheme.SPACE_M }) {
      Text('Hi ' + (this.profile.name.length > 0 ? this.profile.name : 'there') + '! What should Tiles make?')
        .fontSize(this.ty().headline)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().text)
        .width('100%')
      Text(this.profile.id === 'senior' || this.profile.id === 'kid' ?
        'Say it in your own words, in English or Polish. New tiles go to ' + this.caregiverLabel() +
          ' to approve first.' :
        'Say it in your own words, in English or Polish. Tiles turns it into a tile on your home.')
        .fontSize(this.ty().body)
        .fontColor(this.pal().textMuted)
        .width('100%')
      Text('Try one')
        .fontSize(this.ty().caption)
        .fontWeight(FontWeight.Medium)
        .fontColor(this.pal().textMuted)
        .margin({ top: TilesTheme.SPACE_S })
      this.chips(Composer.quickChips(this.profile), true)
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding({ top: TilesTheme.SPACE_S })
  }

  @Builder
  chips(items: string[], big: boolean) {
    Flex({ wrap: FlexWrap.Wrap }) {
      ForEach(items, (c: string, i: number) => {
        Text(c)
          .fontSize(this.ty().label)
          .fontColor(this.pal().text)
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .padding({ left: 14, right: 14, top: 10, bottom: 10 })
          .constraintSize({ minHeight: TilesTheme.TAP_MIN, maxWidth: '100%' })
          .borderRadius(big ? 18 : TilesTheme.RADIUS_CHIP)
          .backgroundColor(this.pal().surface)
          .border({ width: 1.5, color: withAlpha(this.chipColor(i), this.profile.highContrast ? 1 : 0.55) })
          .margin({ right: TilesTheme.SPACE_S, bottom: TilesTheme.SPACE_S })
          .accessibilityText('Ask: ' + c)
          .onClick(() => this.send(c))
      }, (c: string, i: number) => i.toString() + c)
    }
    .width('100%')
  }

  private chipColor(i: number): string {
    if (this.profile.highContrast) {
      return this.pal().border;
    }
    const cs: string[] = ['#FFC83D', '#FF6B5A', '#9B7BFF', '#3DA5FF', '#2ED3A0'];
    return cs[i % cs.length];
  }

  @Builder
  userBubble(m: ChatMsg) {
    Row() {
      Blank()
      Text(m.text)
        .fontSize(this.ty().body)
        .fontColor(this.pal().onAccent)
        .padding({ left: 16, right: 16, top: 12, bottom: 12 })
        .borderRadius({ topLeft: 22, topRight: 22, bottomLeft: 22, bottomRight: 6 })
        .backgroundColor(this.pal().accent)
        .constraintSize({ maxWidth: '82%' })
    }
    .width('100%')
  }

  @Builder
  assistantTurn(m: ChatMsg) {
    Column({ space: TilesTheme.SPACE_M }) {
      Row({ space: TilesTheme.SPACE_S }) {
        SymbolGlyph($r('sys.symbol.wand_and_stars_fill'))
          .fontSize(18)
          .fontColor([this.pal().accent])
          .margin({ top: 12 })
        Text(m.text)
          .fontSize(this.ty().body)
          .fontColor(this.pal().text)
          .padding({ left: 16, right: 16, top: 12, bottom: 12 })
          .borderRadius({ topLeft: 6, topRight: 22, bottomLeft: 22, bottomRight: 22 })
          .backgroundColor(this.pal().surface)
          .border({ width: this.profile.highContrast ? 1.5 : 0, color: this.pal().border })
          .constraintSize({ maxWidth: '88%' })
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)

      if (m.result.tiles.length > 0) {
        Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
          ForEach(m.result.tiles, (t: TileSpec) => {
            Column() {
              TileView({
                tile: t,
                profile: this.profile,
                dark: this.dark,
                reduceMotion: this.reduceMotion,
                onAction: (a: TileAction, tt: TileSpec) => this.onPreviewAction(a, tt)
              })
            }
            .width(t.size === '1x1' && this.profile.columns > 2 ? '48.5%' : '100%')
            .margin({ bottom: TilesTheme.GRID_GAP })
            .opacity(m.status === 'dismissed' ? 0.4 : 1)
          }, (t: TileSpec) => t.id)
        }
        .width('100%')

        this.proposalActions(m)
      }

      if (m.result.followUps.length > 0 && m.status !== 'proposed') {
        this.chips(m.result.followUps, false)
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 24 }))
      .animation({ duration: TilesTheme.dur(TilesTheme.DUR_MED, this.reduceMotion) }))
  }

  @Builder
  proposalActions(m: ChatMsg) {
    if (m.status === 'proposed') {
      Column({ space: TilesTheme.SPACE_S }) {
        if (m.result.needsApproval) {
          Button() {
            Row({ space: TilesTheme.SPACE_S }) {
              SymbolGlyph($r('sys.symbol.person_2_fill'))
                .fontSize(20)
                .fontColor([this.pal().onAccent])
              Text('Ask ' + this.caregiverLabel() + ' to approve')
                .fontSize(this.ty().label + 1)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.pal().onAccent)
            }
          }
          .width('100%')
          .height(this.tap())
          .backgroundColor(this.pal().accent)
          .borderRadius(TilesTheme.RADIUS_BUTTON)
          .accessibilityText('Ask ' + this.caregiverLabel() + ' to approve the new tile')
          .onClick(() => this.askApproval(m))
        } else {
          Button() {
            Row({ space: TilesTheme.SPACE_S }) {
              SymbolGlyph($r('sys.symbol.plus'))
                .fontSize(20)
                .fontColor([this.pal().onAccent])
              Text(m.result.tiles.length > 1 ? 'Add ' + m.result.tiles.length.toString() + ' tiles to home' :
                'Add to home')
                .fontSize(this.ty().label + 1)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.pal().onAccent)
            }
          }
          .width('100%')
          .height(this.tap())
          .backgroundColor(this.pal().accent)
          .borderRadius(TilesTheme.RADIUS_BUTTON)
          .accessibilityText('Add the new tile to your home screen')
          .onClick(() => this.addToHome(m))
        }
        Row({ space: TilesTheme.SPACE_S }) {
          Button('Not now')
            .fontSize(this.ty().label)
            .fontColor(this.pal().text)
            .backgroundColor(this.pal().surfaceAlt)
            .height(TilesTheme.TAP_MIN)
            .layoutWeight(1)
            .borderRadius(TilesTheme.RADIUS_BUTTON)
            .onClick(() => this.setStatus(m.id, 'dismissed'))
          if (m.result.followUps.length > 0) {
            Button('Change it')
              .fontSize(this.ty().label)
              .fontColor(this.pal().text)
              .backgroundColor(this.pal().surfaceAlt)
              .height(TilesTheme.TAP_MIN)
              .layoutWeight(1)
              .borderRadius(TilesTheme.RADIUS_BUTTON)
              .accessibilityText('Show ways to change this tile')
              .onClick(() => this.setStatus(m.id, 'none'))
          }
        }
        .width('100%')
      }
      .width('100%')
    } else if (m.status === 'added' || m.status === 'sent') {
      Column({ space: 2 }) {
        Row({ space: TilesTheme.SPACE_S }) {
          SymbolGlyph($r('sys.symbol.checkmark'))
            .fontSize(18)
            .fontColor([this.pal().onSuccess])
          Text(m.status === 'added' ? 'Added to your home' :
            'Waiting for ' + this.caregiverLabel() + ' to approve')
            .fontSize(this.ty().label)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.pal().onSuccess)
            .layoutWeight(1)
        }
        .width('100%')
        .constraintSize({ minHeight: TilesTheme.TAP_MIN })

        if (m.status === 'sent') {
          Text('See ' + this.caregiverLabel() + '\'s phone →')
            .fontSize(this.ty().label)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.pal().onSuccess)
            .decoration({ type: TextDecorationType.Underline })
            .constraintSize({ minHeight: TilesTheme.TAP_MIN })
            .padding({ left: 26 })
            .accessibilityText('Open ' + this.caregiverLabel() + '\'s approval screen')
            .onClick(() => this.openCaregiver())
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
      .padding({ left: 14, right: 10, top: 4, bottom: 4 })
      .borderRadius(TilesTheme.RADIUS_BUTTON)
      .backgroundColor(this.pal().success)
    }
  }

  @Builder
  generating() {
    Column({ space: TilesTheme.SPACE_M }) {
      Row({ space: TilesTheme.SPACE_S }) {
        ForEach([0, 1, 2], (i: number) => {
          Circle()
            .width(10)
            .height(10)
            .fill(DOT_COLORS[i % DOT_COLORS.length])
            .scale({ x: this.phase % 3 === i ? 1.5 : 0.85, y: this.phase % 3 === i ? 1.5 : 0.85 })
            .animation({ duration: 300, curve: Curve.EaseInOut })
        }, (i: number) => i.toString())
        Text('Tiles is making your tile…')
          .fontSize(this.ty().body)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.pal().text)
          .margin({ left: 6 })
      }
      .alignItems(VerticalAlign.Center)

      // Skeleton tile that "fills in" while the generator runs.
      Column({ space: 10 }) {
        Row({ space: 10 }) {
          Circle()
            .width(32)
            .height(32)
            .fill('#66FFFFFF')
          Column()
            .width('46%')
            .height(18)
            .borderRadius(9)
            .backgroundColor('#66FFFFFF')
        }
        Column()
          .width(this.phase % 2 === 0 ? '70%' : '86%')
          .height(14)
          .borderRadius(7)
          .backgroundColor('#4DFFFFFF')
          .animation({ duration: 300, curve: Curve.EaseInOut })
        Column()
          .width(this.phase % 2 === 0 ? '52%' : '40%')
          .height(14)
          .borderRadius(7)
          .backgroundColor('#4DFFFFFF')
          .animation({ duration: 300, curve: Curve.EaseInOut })
        Text(GEN_STEPS_EN[Math.floor(this.phase / 2) % GEN_STEPS_EN.length])
          .fontSize(this.ty().caption)
          .fontColor('#FFFFFF')
          .opacity(0.9)
      }
      .width('100%')
      .height(132)
      .padding(TilesTheme.TILE_PAD)
      .alignItems(HorizontalAlign.Start)
      .justifyContent(FlexAlign.Center)
      .borderRadius(TilesTheme.RADIUS_TILE)
      .linearGradient({
        angle: 100 + (this.phase % 6) * 12,
        colors: this.profile.highContrast ? [[this.pal().accent, 0], [this.pal().accent, 1]] :
          [['#FFC83D', 0], ['#FF6B5A', 0.35], ['#9B7BFF', 0.7], ['#3DA5FF', 1]]
      })
      .opacity(this.phase % 2 === 0 ? 0.92 : 0.78)
      .animation({ duration: 300, curve: Curve.EaseInOut })
      .accessibilityText('Tiles is making your tile')
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  @Builder
  micBanner() {
    Row({ space: TilesTheme.SPACE_S }) {
      SymbolGlyph($r('sys.symbol.mic_fill'))
        .fontSize(20)
        .fontColor([this.pal().text])
      Text('Voice input is a placeholder in this build (speech recognition is not in the OpenHarmony SDK). ' +
        'Type, or tap a suggestion.')
        .fontSize(this.ty().caption)
        .fontColor(this.pal().text)
        .layoutWeight(1)
      Button({ type: ButtonType.Circle }) {
        SymbolGlyph($r('sys.symbol.xmark'))
          .fontSize(16)
          .fontColor([this.pal().textMuted])
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
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.SPACE_S, top: 6, bottom: 6 })
    .backgroundColor(this.pal().surfaceAlt)
  }

  @Builder
  inputBar() {
    Row({ space: TilesTheme.SPACE_S }) {
      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph($r('sys.symbol.mic_fill'))
          .fontSize(22)
          .fontColor([this.pal().text])
      }
      .width(this.tap() - 4)
      .height(this.tap() - 4)
      .backgroundColor(this.pal().surfaceAlt)
      .accessibilityText('Voice input (placeholder in this build)')
      .onClick(() => {
        this.micNote = true;
        TileHaptics.tap();
      })

      TextInput({ text: this.input, placeholder: 'Ask Tiles… e.g. “Pills at 8:00”' })
        .layoutWeight(1)
        .height(this.tap() - 4)
        .fontSize(this.ty().body)
        .fontColor(this.pal().text)
        .placeholderColor(this.pal().textMuted)
        .backgroundColor(this.pal().surfaceAlt)
        .borderRadius(TilesTheme.RADIUS_CHIP)
        .enterKeyType(EnterKeyType.Send)
        .maxLength(400)
        .id('assistantInput')
        .accessibilityText('Type a request for Tiles')
        .onChange((v: string) => {
          this.input = v;
        })
        .onSubmit(() => this.send(this.input))

      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph($r('sys.symbol.arrow_up'))
          .fontSize(24)
          .fontColor([this.pal().onAccent])
      }
      .width(this.tap() - 4)
      .height(this.tap() - 4)
      .backgroundColor(this.input.trim().length > 0 && !this.thinking ? this.pal().accent :
        withAlpha(this.pal().accent, 0.45))
      .enabled(this.input.trim().length > 0 && !this.thinking)
      .id('assistantSend')
      .accessibilityText('Make the tile')
      .onClick(() => this.send(this.input))
    }
    .width('100%')
    .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: TilesTheme.SPACE_S, bottom: TilesTheme.SPACE_L })
    .backgroundColor(this.pal().barBg)
    .alignItems(VerticalAlign.Center)
  }
}
