import { Profile } from '../model/Tile';
import { K_PROFILE } from '../data/TileStore';
import { LL_FONT_FAMILY, ProfileLayout, ThemePalette, TilesTheme } from '../theme/TilesTheme';
import { K_DARK } from './ShellKeys';

const WAVE_IDX: number[] = [0, 1, 2, 3, 4];
const WAVE_STATIC: number[] = [0.45, 0.9, 0.6, 1.0, 0.4]; // reduced-motion bar heights

/**
 * Voice waveform from the Living Light prototype: 5 accent bars, 4x28 vp, radius 2, gap 3,
 * `wave .9s ease-in-out infinite` (scaleY .3 -> 1 -> .3), staggered 110 ms. Static when reduced motion.
 */
@Component
export struct LLWaveBars {
  @Prop color: string = '#4F5BD5';
  @Prop reduced: boolean = false;
  @State private up: boolean = false;

  build() {
    Row({ space: 3 }) {
      ForEach(WAVE_IDX, (i: number) => {
        Column()
          .width(4)
          .height(28)
          .borderRadius(2)
          .backgroundColor(this.color)
          .scale({ x: 1, y: this.reduced ? WAVE_STATIC[i] : (this.up ? 1 : 0.3), centerY: '50%' })
          .animation({
            duration: TilesTheme.LL_WAVE_MS / 2,
            delay: i * 110,
            curve: Curve.EaseInOut,
            iterations: this.reduced ? 1 : -1,
            playMode: PlayMode.Alternate
          })
      }, (i: number) => 'wb' + i)
    }
    .height(28)
    .alignItems(VerticalAlign.Center)
    .onAppear(() => {
      if (!this.reduced) {
        this.up = true;
      }
    })
  }
}

/** Sparkle outlines in a 24-unit box (big 4-point star + two small ones), like Material "auto_awesome". */
const SPARKLE_STARS: number[][] = [[9, 12, 8], [19, 5, 4], [19, 19, 4]]; // cx, cy, radius

/**
 * The prototype's ✦ "auto_awesome" glyph (no HM Symbol equivalent): concave 4-point sparkles drawn with Path.
 */
@Component
export struct LLSparkle {
  @Prop glyphSize: number = 24;
  @Prop color: string = '#F3F5FF';

  cmds(): string {
    const k: number = this.getUIContext().vp2px(this.glyphSize) / 24;
    let out: string = '';
    for (let i = 0; i < SPARKLE_STARS.length; i++) {
      const cx: number = SPARKLE_STARS[i][0] * k;
      const cy: number = SPARKLE_STARS[i][1] * k;
      const r: number = SPARKLE_STARS[i][2] * k;
      const c: number = r * 0.14; // how far the concave edge bows toward the centre
      out += `M${cx} ${cy - r} Q${cx + c} ${cy - c} ${cx + r} ${cy} Q${cx + c} ${cy + c} ${cx} ${cy + r} ` +
        `Q${cx - c} ${cy + c} ${cx - r} ${cy} Q${cx - c} ${cy - c} ${cx} ${cy - r} Z `;
    }
    return out;
  }

  build() {
    Path()
      .width(this.glyphSize)
      .height(this.glyphSize)
      .commands(this.cmds())
      .fill(this.color)
      .stroke(Color.Transparent)
  }
}

/**
 * The pinned "Ask Tiles…" dock at the bottom of Home — Living Light (direction C).
 * Idle (prototype Tiles_Stage line ~148): ink pill, height = profile askH, padding 0 8 0 20, gap 12,
 *   auto_awesome glyph, "Ask Tiles…" (17 * min(fs,1.2), weight 600, opacity .9), 44 vp mic circle (askMicBg),
 *   sheetShadow. The parent positions it 16 vp from the sides and 30 vp from the bottom.
 * Listening (optional, `listening`): glass card (surface .8 + blur 26 / saturate 1.5, radius 26,
 *   padding 14/16/16, 12 vp from the sides) with the accent waveform and an accent mic button.
 * Behaviour: tapping the bar calls onOpen(''), tapping the mic calls onOpen('mic').
 */
@Component
export struct AskDock {
  @StorageLink(K_PROFILE) profile: Profile = new Profile();
  @StorageProp(K_DARK) dark: boolean = false;
  @Prop listening: boolean = false;
  onOpen: (seed: string) => void = (seed: string) => {
  };

  pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }

  lay(): ProfileLayout {
    return TilesTheme.layoutFor(this.profile);
  }

  /** Prototype askFontSize = round(17 * min(fs, 1.2)). */
  askFont(): number {
    return Math.round(17 * Math.min(this.lay().fs, 1.2));
  }

  @Builder
  idlePill() {
    Row({ space: 12 }) {
      LLSparkle({ glyphSize: 24, color: this.pal().onInk })
      Text('Ask Tiles…')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.askFont())
        .fontWeight(600)
        .letterSpacing(TilesTheme.letterSpacing(this.askFont()))
        .fontColor(this.pal().onInk)
        .opacity(0.9)
        .layoutWeight(1)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph($r('sys.symbol.mic_fill'))
          .fontSize(24)
          .fontColor([this.pal().onInk])
      }
      .width(44)
      .height(44)
      .backgroundColor(this.pal().askMicBg)
      .accessibilityText('Speak to Tiles')
      .onClick(() => this.onOpen('mic'))
    }
    .width('100%')
    .height(this.lay().askH)
    .padding({ left: 20, right: 8 })
    .borderRadius(TilesTheme.LL_RADIUS_PILL)
    .backgroundColor(this.pal().ink)
    .shadow(TilesTheme.LL_SHADOW_SHEET)
    .alignItems(VerticalAlign.Center)
  }

  @Builder
  listeningCard() {
    Row({ space: 12 }) {
      LLWaveBars({ color: this.pal().accent, reduced: this.lay().reducedMotion })
      Text('Listening…')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(16)
        .fontWeight(600)
        .fontColor(this.pal().ink)
        .layoutWeight(1)
        .maxLines(1)
      Button({ type: ButtonType.Circle, stateEffect: true }) {
        SymbolGlyph($r('sys.symbol.mic_fill'))
          .fontSize(24)
          .fontColor([this.pal().onAccent])
      }
      .width(44)
      .height(44)
      .backgroundColor(this.pal().accent)
      .accessibilityText('Speak to Tiles')
      .onClick(() => this.onOpen('mic'))
    }
    .width('100%')
    .constraintSize({ minHeight: this.lay().askH })
    .padding({ top: 14, left: 16, right: 16, bottom: 16 })
    .margin({ left: -4, right: -4 }) // dock sits 16 vp in; the glass card sits 12 vp in
    .borderRadius(TilesTheme.LL_RADIUS_L)
    .backgroundColor(this.dark ? this.pal().surface : '#CCFFFFFF')
    .backdropBlur(TilesTheme.LL_BLUR)
    .shadow(TilesTheme.LL_SHADOW_SHEET)
    .alignItems(VerticalAlign.Center)
  }

  build() {
    Column() {
      if (this.listening) {
        this.listeningCard()
      } else {
        this.idlePill()
      }
    }
    .width('100%')
    .onClick(() => this.onOpen(''))
    .accessibilityGroup(true)
    .accessibilityText(this.listening ? 'Tiles is listening' : 'Ask Tiles. Type or speak to make a new tile')
  }
}
