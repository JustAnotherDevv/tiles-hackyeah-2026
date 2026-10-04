import { TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';


/** Prototype `tile.bodySize` (14 * fs, x.9 on small tiles) — resolved by TileView into BlockStyle. */
export function llBodySize(bs: BlockStyle): number {
  return Math.max(11, bs.bodySize);
}

/** Prototype `tile.bodyLines` (1 on tiles shorter than 120 vp, else 3); detail shows everything. */
export function llBodyLines(bs: BlockStyle): number {
  return bs.detail ? 12 : Math.max(1, bs.bodyLines);
}

/** `text`: a short paragraph (Living Light: body size, 1.3 line height, 92% ink). */
@Component
export struct TextBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  build() {
    Text(this.block.text.length > 0 ? this.block.text : this.block.value)
      .fontSize(llBodySize(this.bs))
      .fontColor(this.bs.fg)
      .fontFamily(this.bs.font)
      .opacity(this.bs.highContrast ? 1 : 0.92)
      .lineHeight(Math.round(llBodySize(this.bs) * 1.3))
      .maxLines(llBodyLines(this.bs))
      .wordBreak(WordBreak.NORMAL)
      .textOverflow({ overflow: TextOverflow.Ellipsis })
      .width('100%')
  }
}

/** Prototype `tile.numSize` (38 * fs, x.78 on small tiles) — resolved by TileView into BlockStyle. */
export function llNumSize(bs: BlockStyle): number {
  return Math.max(20, bs.numSize);
}
