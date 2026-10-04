import { TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

/** Normalizes TileBlock.progress (0..1 or 0..100) to a 0..100 percentage. */
export function percentOf(p: number): number {
  if (!isFinite(p) || p <= 0) {
    return 0;
  }
  const v: number = p <= 1 ? p * 100 : p;
  return Math.max(0, Math.min(100, Math.round(v)));
}

/** `progress`: a friendly meter. `value` = label ("3 of 5"), `text` = caption. */
@Component
export struct ProgressBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  build() {
    Column({ space: 8 }) {
      Row() {
        Text(this.block.value.length > 0 ? this.block.value : percentOf(this.block.progress) + '%')
          .fontSize(this.bs.fs(this.bs.compact ? 16 : 20))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.bs.fg)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
        if (this.block.value.length > 0 && !this.bs.compact) {
          Text(percentOf(this.block.progress) + '%')
            .fontSize(this.bs.fs(14))
            .fontWeight(FontWeight.Medium)
            .fontColor(this.bs.fgDim)
            .fontFeature('"tnum" on')
        }
      }
      .width('100%')

      Stack({ alignContent: Alignment.Start }) {
        Row()
          .width('100%')
          .height(this.bs.highContrast ? 16 : 12)
          .borderRadius(8)
          .backgroundColor(this.bs.well)
          .border({ width: this.bs.highContrast ? 2 : 0, color: this.bs.fg })
        Row()
          .width(percentOf(this.block.progress) + '%')
          .height(this.bs.highContrast ? 16 : 12)
          .borderRadius(8)
          .backgroundColor(this.bs.fg)
          .animation({ duration: this.bs.reduceMotion ? 0 : 400, curve: Curve.EaseOut })
      }
      .width('100%')

      if (this.block.text.length > 0 && !this.bs.compact) {
        Text(this.block.text)
          .fontSize(this.bs.fs(14))
          .fontColor(this.bs.fgDim)
          .maxLines(this.bs.tier === 'full' || this.bs.detail ? 2 : 1)
          .wordBreak(WordBreak.NORMAL)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .accessibilityGroup(true)
    .accessibilityText((this.block.value.length > 0 ? this.block.value + ', ' : '') + percentOf(this.block.progress) +
      ' percent' + (this.block.text.length > 0 ? ', ' + this.block.text : ''))
  }
}
