import { TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

/** `text`: a short paragraph. */
@Component
export struct TextBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  build() {
    Text(this.block.text.length > 0 ? this.block.text : this.block.value)
      .fontSize(this.bs.fs(17))
      .fontColor(this.bs.fg)
      .lineHeight(Math.round(this.bs.fs(17) * 1.35))
      .maxLines(this.bs.limit(2, 3, 4, 12))
      .wordBreak(WordBreak.NORMAL)
      .textOverflow({ overflow: TextOverflow.Ellipsis })
      .width('100%')
  }
}
