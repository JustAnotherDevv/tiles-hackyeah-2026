import { TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

/** `big`: one hero value ("8:00", "14°", "3/5") with an optional caption. */
@Component
export struct BigBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  private hero(): number {
    if (this.bs.tiny) {
      return 24;
    }
    if (this.bs.compact) {
      return 30;
    }
    return this.bs.narrow ? 36 : 44;
  }

  build() {
    Column({ space: 2 }) {
      Text(this.block.value.length > 0 ? this.block.value : this.block.text)
        .fontSize(this.bs.fs(this.hero()))
        .fontWeight(FontWeight.Bolder)
        .fontColor(this.bs.fg)
        .fontFeature('"tnum" on')
        .maxLines(1)
        .minFontSize(14)
        .maxFontSize(this.bs.fs(this.hero()))
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      if (this.block.value.length > 0 && this.block.text.length > 0) {
        Text(this.block.text)
          .fontSize(this.bs.fs(15))
          .fontWeight(FontWeight.Medium)
          .fontColor(this.bs.fgDim)
          .maxLines(this.bs.compact ? 1 : 2)
          .wordBreak(WordBreak.NORMAL)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
