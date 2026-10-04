import { curves } from '@kit.ArkUI';
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

/**
 * `progress` (Living Light): 12 vp rounded track + fill in the tile's ink, label underneath
 * ("3 of 5 · Almost there!"). `value` = short label, `text` = caption.
 */
@Component
export struct ProgressBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  private label(): string {
    const v: string = this.block.value.length > 0 ? this.block.value : percentOf(this.block.progress) + '%';
    if (this.block.text.length > 0 && !this.bs.compact) {
      return v + ' · ' + this.block.text;
    }
    return v;
  }

  private barH(): number {
    return this.bs.highContrast ? Math.max(16, this.bs.barH) : this.bs.barH;
  }

  build() {
    Column({ space: 7 }) {
      Stack({ alignContent: Alignment.Start }) {
        Row()
          .width(percentOf(this.block.progress) + '%')
          .height('100%')
          .borderRadius(this.barH() / 2)
          .backgroundColor(this.bs.fg)
          .animation({ duration: this.bs.reduceMotion ? 0 : 700, curve: curves.cubicBezierCurve(0.22, 1, 0.36, 1) })
      }
      .width('100%')
      .height(this.barH())
      .borderRadius(this.barH() / 2)
      .backgroundColor(this.bs.highContrast ? this.bs.well : this.bs.track)
      .border({ width: this.bs.highContrast ? 2 : 0, color: this.bs.fg })
      .clip(true)

      Text(this.label())
        .fontSize(this.bs.bodySize)
        .fontFamily(this.bs.font)
        .fontColor(this.bs.fg)
        .opacity(0.9)
        .lineHeight(Math.round(this.bs.bodySize * 1.25))
        .maxLines(this.bs.tier === 'full' || this.bs.detail ? 2 : 1)
        .wordBreak(WordBreak.NORMAL)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .accessibilityGroup(true)
    .accessibilityText((this.block.value.length > 0 ? this.block.value + ', ' : '') + percentOf(this.block.progress) +
      ' percent' + (this.block.text.length > 0 ? ', ' + this.block.text : ''))
  }
}
