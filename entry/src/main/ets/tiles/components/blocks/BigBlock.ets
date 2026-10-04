import { TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';
import { llBodySize, llNumSize } from './TextBlock';

/** '4 min' -> number '4' + unit 'min'; '8:00' / '14°' / '3/5' stay whole. */
class NumParts {
  num: string = '';
  unit: string = '';
}

const NUM_UNIT: RegExp = new RegExp('^([0-9][0-9:.,/°%+\\-]*)\\s+([^\\s0-9].{0,9})$');

function splitNumber(v: string): NumParts {
  const p: NumParts = new NumParts();
  const m: RegExpMatchArray | null = v.trim().match(NUM_UNIT);
  if (m !== null && m.length >= 3) {
    p.num = m[1];
    p.unit = m[2];
  } else {
    p.num = v.trim();
  }
  return p;
}

/**
 * `big` — the prototype's "number" block: one hero value with big tabular numerals (800, -3% tracking) and a
 * baseline-aligned unit at body size; the optional caption sits inline (wide tiles) or underneath.
 */
@Component
export struct BigBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  private parts(): NumParts {
    return splitNumber(this.block.value.length > 0 ? this.block.value : this.block.text);
  }

  private caption(): string {
    return this.block.value.length > 0 ? this.block.text : '';
  }

  /** Text shown inline next to the number: the unit, else the caption on roomy tiles. */
  private inlineText(): string {
    const p: NumParts = this.parts();
    if (p.unit.length > 0) {
      return p.unit;
    }
    return this.bs.square || this.bs.small ? '' : this.caption();
  }

  /** Caption under the number when it did not go inline. */
  private belowText(): string {
    if (this.bs.small || this.bs.squeeze < 0.99) {
      return '';
    }
    return this.inlineText() === this.caption() ? '' : this.caption();
  }

  build() {
    Column({ space: 4 }) {
      Flex({ direction: FlexDirection.Row, alignItems: ItemAlign.Baseline }) {
        Text(this.parts().num)
          .fontSize(llNumSize(this.bs))
          .fontWeight(this.bs.numWeight)
          .fontColor(this.bs.fg)
          .fontFeature('"tnum" on')
          .letterSpacing(this.bs.numLs())
          .fontFamily(this.bs.font)
          .lineHeight(Math.round(llNumSize(this.bs) * 1.04))
          .maxLines(1)
          .minFontSize(14)
          .maxFontSize(llNumSize(this.bs))
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .flexShrink(0)
        if (this.inlineText().length > 0) {
          Text(this.inlineText())
            .fontSize(llBodySize(this.bs))
            .fontColor(this.bs.fg)
            .opacity(this.bs.highContrast ? 1 : 0.8)
            .maxLines(this.parts().unit.length > 0 ? 1 : 2)
            .wordBreak(WordBreak.NORMAL)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ left: 6 })
            .flexShrink(1)
        }
      }
      .width('100%')

      if (this.belowText().length > 0) {
        Text(this.belowText())
          .fontSize(llBodySize(this.bs))
          .fontColor(this.bs.fg)
          .opacity(this.bs.highContrast ? 1 : 0.8)
          .lineHeight(Math.round(llBodySize(this.bs) * 1.25))
          .maxLines(this.bs.compact ? 1 : 2)
          .wordBreak(WordBreak.NORMAL)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%')
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .accessibilityGroup(true)
    .accessibilityText((this.block.value.length > 0 ? this.block.value : this.block.text) +
      (this.caption().length > 0 ? ', ' + this.caption() : ''))
  }
}
