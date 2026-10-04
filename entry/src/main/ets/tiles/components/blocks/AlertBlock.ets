import { LengthMetrics } from '@kit.ArkUI';
import { TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';
import { llBodySize } from './TextBlock';

class FlagRow {
  key: string = '';
  text: string = '';
}

// Living Light (THEMES.C) semantic tones: soft pill fill + ink. Local until TilesTheme exposes them.
const LL_DANGER_SOFT: string = '#1FC62B4A'; // rgba(198,43,74,.12)
const LL_DANGER_INK: string = '#8E1B33';
const LL_WARN_SOFT: string = '#1F8A4B00';
const LL_WARN_INK: string = '#6B3A00';
const LL_INFO_SOFT: string = '#1F4F5BD5'; // accent .12
const LL_INFO_INK: string = '#3540A8';
/** Frosted inset for the quoted message (Living Light surface on top of the tile gradient). */
const LL_QUOTE_BG: string = '#8CFFFFFF';

/**
 * `alert` (Guardian scam shield, warnings), Living Light: an inline warning line in the tile's ink (filled warning
 * glyph + semibold body text, as the prototype), the quoted message on a frosted inset, red flags as soft danger
 * pills (the scam screen's flag chips).
 *  - text  = what happened (e.g. the demo call quote)
 *  - value = what to do ("This looks like a scam. Hang up.") — or a bare severity 'danger' | 'warn' | 'info'
 *  - items = red flags ("asks for money", "pressure: right now")
 */
@Component
export struct AlertBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  private severity(): string {
    const v: string = this.block.value;
    return v === 'info' || v === 'warn' || v === 'danger' ? v : 'danger';
  }

  /** The "what to do" line, if value carries one. */
  private advice(): string {
    const v: string = this.block.value;
    return v === 'info' || v === 'warn' || v === 'danger' ? '' : v;
  }

  private ink(): string {
    const s: string = this.severity();
    if (s === 'info') {
      return LL_INFO_INK;
    }
    return s === 'warn' ? LL_WARN_INK : LL_DANGER_INK;
  }

  private soft(): string {
    const s: string = this.severity();
    if (s === 'info') {
      return LL_INFO_SOFT;
    }
    return s === 'warn' ? LL_WARN_SOFT : LL_DANGER_SOFT;
  }

  private flags(): FlagRow[] {
    const out: FlagRow[] = [];
    const max: number = this.bs.limit(0, 2, 3, 10);
    for (let i = 0; i < this.block.items.length && i < max; i++) {
      const r: FlagRow = new FlagRow();
      r.key = i + ':' + this.block.items[i];
      r.text = this.block.items[i];
      out.push(r);
    }
    return out;
  }

  private body(): number {
    return llBodySize(this.bs);
  }

  /** Quote shown under the warning line (only when the line is the advice). */
  private showQuote(): boolean {
    return this.advice().length > 0 && this.block.text.length > 0 && !this.bs.compact && !this.bs.small;
  }

  build() {
    Column({ space: 8 }) {
      Row({ space: 8 }) {
        SymbolGlyph(this.severity() === 'info' ? $r('sys.symbol.exclamationmark_circle') :
          $r('sys.symbol.exclamationmark_triangle_fill'))
          .fontSize(Math.max(20, Math.round(this.body() * 1.4)))
          .fontColor([this.bs.fg])
        Text(this.advice().length > 0 ? this.advice() : this.block.text)
          .fontSize(this.body())
          .fontWeight(600)
          .fontColor(this.bs.fg)
          .lineHeight(Math.round(this.body() * 1.25))
          .maxLines(this.bs.limit(2, 3, 4, 6))
          .wordBreak(WordBreak.NORMAL)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
      }
      .alignItems(VerticalAlign.Center)
      .width('100%')

      if (this.showQuote()) {
        Text(this.block.text)
          .fontSize(this.body())
          .fontStyle(FontStyle.Italic)
          .fontColor(this.bs.fg)
          .lineHeight(Math.round(this.body() * 1.3))
          .maxLines(this.bs.detail ? 8 : 3)
          .wordBreak(WordBreak.NORMAL)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%')
          .padding({ left: 12, right: 12, top: 8, bottom: 8 })
          .borderRadius(14)
          .backgroundColor(this.bs.highContrast ? '#FFFFFF' : LL_QUOTE_BG)
      }

      if (this.flags().length > 0) {
        Flex({ wrap: FlexWrap.Wrap, space: { main: LengthMetrics.vp(6), cross: LengthMetrics.vp(6) } }) {
          ForEach(this.flags(), (r: FlagRow) => {
            Row({ space: 6 }) {
              SymbolGlyph($r('sys.symbol.flag_fill'))
                .fontSize(Math.max(14, Math.round(this.body() * 1.15)))
                .fontColor([this.ink()])
              Text(r.text)
                .fontSize(Math.max(11, this.body()))
                .fontWeight(700)
                .fontColor(this.ink())
                .maxLines(1)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
                .flexShrink(1)
            }
            .padding({ left: 12, right: 12, top: 7, bottom: 7 })
            .borderRadius(999)
            .backgroundColor(this.bs.highContrast ? '#FFFFFF' : this.soft())
            .border({ width: this.bs.highContrast ? 2 : 0, color: this.ink() })
            .constraintSize({ maxWidth: '100%' })
          }, (r: FlagRow) => r.key)
        }
        .width('100%')
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .accessibilityGroup(true)
    .accessibilityText('Warning. ' + (this.advice().length > 0 ? this.advice() + '. ' : '') + this.block.text +
      (this.block.items.length > 0 ? '. ' + this.block.items.join(', ') : ''))
  }
}
