import { LengthMetrics } from '@kit.ArkUI';
import { TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

class WearRow {
  key: string = '';
  text: string = '';
}

/** Icon picked from the condition text (EN + PL keywords). */
function weatherIcon(text: string): Resource {
  const t: string = text.toLowerCase();
  if (t.indexOf('storm') >= 0 || t.indexOf('burz') >= 0 || t.indexOf('thunder') >= 0) {
    return $r('sys.symbol.bolt_1');
  }
  if (t.indexOf('rain') >= 0 || t.indexOf('deszcz') >= 0 || t.indexOf('shower') >= 0 || t.indexOf('umbrella') >= 0 ||
    t.indexOf('parasol') >= 0) {
    return $r('sys.symbol.umbrella');
  }
  if (t.indexOf('snow') >= 0 || t.indexOf('śnieg') >= 0) {
    return $r('sys.symbol.snowflake');
  }
  if (t.indexOf('cloud') >= 0 || t.indexOf('pochmur') >= 0 || t.indexOf('chmur') >= 0) {
    return $r('sys.symbol.cloud_fill');
  }
  if (t.indexOf('sun') >= 0 || t.indexOf('słon') >= 0 || t.indexOf('clear') >= 0) {
    return $r('sys.symbol.sun_max_fill');
  }
  return $r('sys.symbol.cloud_sun_fill');
}

/** `weather`: `value` = temperature, `text` = condition line, `items` = what-to-wear hints. */
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

  build() {
    Column({ space: 10 }) {
      Row({ space: 12 }) {
        if (!this.bs.compact) {
          SymbolGlyph(weatherIcon(this.block.text))
            .fontSize(this.bs.fs(this.bs.narrow ? 32 : 44))
            .fontColor([this.bs.fg])
        }
        Column({ space: 0 }) {
          Text(this.block.value)
            .fontSize(this.bs.fs(this.bs.compact ? 26 : (this.bs.narrow ? 32 : 40)))
            .fontWeight(FontWeight.Bolder)
            .fontColor(this.bs.fg)
            .maxLines(1)
            .minFontSize(14)
            .maxFontSize(this.bs.fs(this.bs.compact ? 26 : (this.bs.narrow ? 32 : 40)))
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          if (this.block.text.length > 0) {
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
        .layoutWeight(1)
      }
      .width('100%')

      if (this.wear().length > 0) {
        Flex({ wrap: FlexWrap.Wrap, space: { main: LengthMetrics.vp(6), cross: LengthMetrics.vp(6) } }) {
          ForEach(this.wear(), (r: WearRow) => {
            Text(r.text)
              .fontSize(this.bs.fs(14))
              .fontWeight(FontWeight.Medium)
              .fontColor(this.bs.fg)
              .padding({ left: 10, right: 10, top: 5, bottom: 5 })
              .borderRadius(999)
              .backgroundColor(this.bs.well)
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
