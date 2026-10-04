import { TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

class ListRow {
  key: string = '';
  text: string = '';
}

/** `list`: bulleted lines; `text` is an optional heading. */
@Component
export struct ListBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  private max(): number {
    return this.bs.limit(2, 3, 4, 20);
  }

  private rows(): ListRow[] {
    const max: number = this.max();
    const out: ListRow[] = [];
    for (let i = 0; i < this.block.items.length && i < max; i++) {
      const r: ListRow = new ListRow();
      r.key = i + ':' + this.block.items[i];
      r.text = this.block.items[i];
      out.push(r);
    }
    return out;
  }

  build() {
    Column({ space: 6 }) {
      if (this.block.text.length > 0) {
        Text(this.block.text)
          .fontSize(this.bs.fs(13))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.bs.fgDim)
          .letterSpacing(0.6)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      ForEach(this.rows(), (r: ListRow) => {
        Row({ space: this.bs.narrow && !this.bs.detail ? 7 : 10 }) {
          Circle()
            .width(this.bs.narrow && !this.bs.detail ? 5 : 7)
            .height(this.bs.narrow && !this.bs.detail ? 5 : 7)
            .fill(this.bs.fg)
          Text(r.text)
            .fontSize(this.bs.fs(this.bs.narrow && !this.bs.detail ? 14 : 16))
            .fontColor(this.bs.fg)
            .maxLines(this.bs.narrow && !this.bs.detail ? 1 : 2)
            .wordBreak(WordBreak.NORMAL)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
        }
        .width('100%')
      }, (r: ListRow) => r.key)
      if (!this.bs.detail && this.block.items.length > this.max()) {
        Text('+' + (this.block.items.length - this.max()) + ' more')
          .fontSize(this.bs.fs(13))
          .fontColor(this.bs.fgDim)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
