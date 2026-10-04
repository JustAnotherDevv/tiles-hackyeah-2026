import { LengthMetrics } from '@kit.ArkUI';
import { TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';
import { llBodySize, llNumSize } from './TextBlock';

class WearRow {
  key: string = '';
  text: string = '';
}

/**
 * `weather`: `value` = temperature, `text` = condition line, `items` = what-to-wear hints.
 * Living Light: big tabular temperature + condition beside it (the tile header carries the weather icon),
 * wear hints as soft pills.
 */
@Component
export struct WeatherBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  private wear(): WearRow[] {
    const out: WearRow[] = [];
    const max: number = this.bs.limit(0, 2, 3, 10);
    for (let i = 0; i < this.block.items.length && i < max; i++) {
      const r: WearRow = new WearRow();
      r.key = i + ':' + this.block.items[i];
      r.text = this.block.items[i];
      out.push(r);
    }
    return out;
  }

  private chipSize(): number {
    return this.bs.chipSize;
  }

  build() {
    Column({ space: 8 }) {
      Row({ space: 8 }) {
        Text(this.block.value)
          .fontSize(llNumSize(this.bs))
          .fontWeight(this.bs.numWeight)
          .fontColor(this.bs.fg)
          .letterSpacing(this.bs.numLs())
          .fontFamily(this.bs.font)
          .lineHeight(Math.round(llNumSize(this.bs) * 1.04))
          .maxLines(1)
          .minFontSize(14)
          .maxFontSize(llNumSize(this.bs))
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .flexShrink(0)
        if (this.block.text.length > 0 && !this.bs.small) {
          Text(this.block.text)
            .fontSize(llBodySize(this.bs))
            .fontColor(this.bs.fg)
            .opacity(this.bs.highContrast ? 1 : 0.85)
            .lineHeight(Math.round(llBodySize(this.bs) * 1.2))
            .maxLines(this.bs.compact ? 2 : 3)
            .wordBreak(WordBreak.NORMAL)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
        }
      }
      .alignItems(VerticalAlign.Center)
      .width('100%')

      if (this.wear().length > 0) {
        Flex({ wrap: FlexWrap.Wrap, space: { main: LengthMetrics.vp(6), cross: LengthMetrics.vp(6) } }) {
          ForEach(this.wear(), (r: WearRow) => {
            Text(r.text)
              .fontSize(this.chipSize())
              .fontWeight(600)
              .fontColor(this.bs.fg)
              .lineHeight(Math.round(this.chipSize() * 1.2))
              .padding({ left: 10, right: 10, top: 5, bottom: 5 })
              .borderRadius(999)
              .backgroundColor(this.bs.highContrast ? this.bs.well : this.bs.pill)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .constraintSize({ maxWidth: '100%' })
          }, (r: WearRow) => r.key)
        }
        .width('100%')
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .accessibilityGroup(true)
    .accessibilityText(this.block.value + ', ' + this.block.text + (this.block.items.length > 0 ? '. Wear: ' +
    this.block.items.join(', ') : ''))
  }
}
