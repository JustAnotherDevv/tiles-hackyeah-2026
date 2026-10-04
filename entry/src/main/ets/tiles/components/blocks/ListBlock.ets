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

  private rows(): ListRow[] {
    const max: number = this.bs.compact ? 2 : (this.bs.detail ? 20 : 4);
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
      }
      ForEach(this.rows(), (r: ListRow) => {
        Row({ space: 10 }) {
          Circle()
            .width(7)
            .height(7)
            .fill(this.bs.fg)
          Text(r.text)
            .fontSize(this.bs.fs(16))
            .fontColor(this.bs.fg)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
        }
        .width('100%')
      }, (r: ListRow) => r.key)
      if (!this.bs.detail && this.block.items.length > (this.bs.compact ? 2 : 4)) {
        Text('+' + (this.block.items.length - (this.bs.compact ? 2 : 4)) + ' more')
          .fontSize(this.bs.fs(13))
          .fontColor(this.bs.fgDim)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
