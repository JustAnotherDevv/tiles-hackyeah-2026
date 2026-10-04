import { TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

class FlagRow {
  key: string = '';
  text: string = '';
}

/**
 * `alert`: a high-visibility card (Guardian scam shield, warnings). Always a solid light card so it reads on any tile.
 *  - text  = what happened (e.g. the demo call quote)
 *  - value = what to do ("This looks like a scam. Hang up.") — or a bare severity 'danger' | 'warn' | 'info'
 *  - items = red flags ("asks for money", "pressure: right now")
 */
@Component
export struct AlertBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  private severity(): string {
    const v: string = this.block.value;
    return v === 'info' || v === 'warn' || v === 'danger' ? v : 'danger';
  }

  /** The "what to do" line, if value carries one. */
  private advice(): string {
    const v: string = this.block.value;
    return v === 'info' || v === 'warn' || v === 'danger' ? '' : v;
  }

  private tone(): string {
    const s: string = this.severity();
    if (s === 'info') {
      return '#0B57D0';
    }
    if (s === 'warn') {
      return '#8A4B00';
    }
    return '#B3261E';
  }

  private flags(): FlagRow[] {
    const out: FlagRow[] = [];
    const max: number = this.bs.compact ? 0 : (this.bs.detail ? 10 : 3);
    for (let i = 0; i < this.block.items.length && i < max; i++) {
      const r: FlagRow = new FlagRow();
      r.key = i + ':' + this.block.items[i];
      r.text = this.block.items[i];
      out.push(r);
    }
    return out;
  }

  build() {
    Column({ space: 8 }) {
      Row({ space: 10 }) {
        if (this.severity() === 'info') {
          SymbolGlyph($r('sys.symbol.exclamationmark_circle'))
            .fontSize(this.bs.fs(26))
            .fontColor([this.tone()])
        } else {
          SymbolGlyph($r('sys.symbol.exclamationmark_triangle_fill'))
            .fontSize(this.bs.fs(26))
            .fontColor([this.tone()])
        }
        Text(this.advice().length > 0 ? this.advice() : this.block.text)
          .fontSize(this.bs.fs(this.bs.compact ? 15 : 18))
          .fontWeight(FontWeight.Bolder)
          .fontColor(this.advice().length > 0 ? this.tone() : '#1C2230')
          .maxLines(this.bs.compact ? 2 : 4)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
      }
      .alignItems(VerticalAlign.Top)
      .width('100%')

      if (this.advice().length > 0 && this.block.text.length > 0 && !this.bs.compact) {
        Text(this.block.text)
          .fontSize(this.bs.fs(15))
          .fontStyle(FontStyle.Italic)
          .fontColor('#3A3F4B')
          .lineHeight(Math.round(this.bs.fs(15) * 1.35))
          .maxLines(this.bs.detail ? 8 : 3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%')
          .padding({ left: 10 })
          .border({ width: { left: 3 }, color: { left: this.tone() } })
      }

      ForEach(this.flags(), (r: FlagRow) => {
        Row({ space: 8 }) {
          SymbolGlyph($r('sys.symbol.xmark_circle_fill'))
            .fontSize(this.bs.fs(16))
            .fontColor([this.tone()])
          Text(r.text)
            .fontSize(this.bs.fs(15))
            .fontWeight(FontWeight.Medium)
            .fontColor('#3A3F4B')
            .maxLines(2)
            .layoutWeight(1)
        }
        .width('100%')
      }, (r: FlagRow) => r.key)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(12)
    .borderRadius(16)
    .backgroundColor('#FFFFFF')
    .border({ width: this.bs.highContrast ? 3 : 2, color: this.tone() })
    .accessibilityGroup(true)
    .accessibilityText('Warning. ' + (this.advice().length > 0 ? this.advice() + '. ' : '') + this.block.text +
      (this.block.items.length > 0 ? '. ' + this.block.items.join(', ') : ''))
  }
}
