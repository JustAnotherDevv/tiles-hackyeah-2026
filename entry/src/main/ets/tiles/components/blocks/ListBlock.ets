import { TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

class ListRow {
  key: string = '';
  text: string = '';
  lead: string = '';
  meta: string = '';
}

/**
 * `list` (Living Light): soft rows in the tile's on-color, matching the prototype's checklist rhythm
 * (row min height max(28, body * 2), gap 10, line-height 1.2). "Name · detail" lines render the name bold and the
 * rest dimmed; `text` is an optional small heading.
 */
@Component
export struct ListBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  private max(): number {
    return this.bs.limit(2, 3, 4, 20);
  }

  private small(): boolean {
    return this.bs.narrow && !this.bs.detail;
  }

  private bodyFs(): number {
    return this.small() ? Math.max(11, Math.round(this.bs.bodySize * 0.92)) : this.bs.bodySize;
  }

  private rows(): ListRow[] {
    const max: number = this.max();
    const out: ListRow[] = [];
    for (let i = 0; i < this.block.items.length && i < max; i++) {
      const r: ListRow = new ListRow();
      const t: string = this.block.items[i];
      r.key = i + ':' + t;
      r.text = t;
      const cut: number = t.indexOf(' · ');
      r.lead = cut > 0 ? t.substring(0, cut) : t;
      r.meta = cut > 0 ? t.substring(cut) : '';
      out.push(r);
    }
    return out;
  }

  build() {
    Column({ space: 2 }) {
      if (this.block.text.length > 0) {
        Text(this.block.text)
          .fontSize(this.bs.chipSize)
          .fontFamily(this.bs.font)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.bs.fg)
          .opacity(0.72)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ bottom: 2 })
      }
      ForEach(this.rows(), (r: ListRow) => {
        Row({ space: this.small() ? 8 : 10 }) {
          Circle()
            .width(6)
            .height(6)
            .fill(this.bs.fg)
            .opacity(0.55)
          Text() {
            Span(r.lead)
              .fontWeight(FontWeight.Bold)
            if (r.meta.length > 0) {
              Span(r.meta)
                .fontWeight(FontWeight.Regular)
                .fontColor(this.bs.fgDim)
            }
          }
          .fontSize(this.bodyFs())
          .fontFamily(this.bs.font)
          .fontColor(this.bs.fg)
          .lineHeight(Math.round(this.bodyFs() * 1.25))
          .maxLines(this.small() ? 1 : 2)
          .wordBreak(WordBreak.NORMAL)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
        }
        .width('100%')
        .constraintSize({ minHeight: this.bs.compact || this.small() ? 0 : this.bs.rowMin })
        .alignItems(VerticalAlign.Center)
        .accessibilityGroup(true)
        .accessibilityText(r.text)
      }, (r: ListRow) => r.key)
      if (!this.bs.detail && this.block.items.length > this.max()) {
        Text('+' + (this.block.items.length - this.max()) + ' more')
          .fontSize(this.bs.chipSize)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.bs.fg)
          .opacity(0.7)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
