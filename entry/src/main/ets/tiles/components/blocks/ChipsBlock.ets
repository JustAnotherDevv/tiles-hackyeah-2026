import { LengthMetrics } from '@kit.ArkUI';
import { TileAction, TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

class ChipRow {
  key: string = '';
  index: number = 0;
  label: string = '';
  tappable: boolean = false;
}

/**
 * `chips`: static `items` (tags / options), or tappable `actions` (e.g. vote options, kind 'vote').
 * A tapped chip becomes the selected one (solid) and emits its action.
 */
@Component
export struct ChipsBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();
  @State selected: number = -1;
  onAction: (a: TileAction) => void = (a: TileAction) => {
  };

  private rows(): ChipRow[] {
    const max: number = this.bs.compact ? 2 : (this.bs.detail ? 20 : 6);
    const out: ChipRow[] = [];
    const useActions: boolean = this.block.actions.length > 0;
    const n: number = useActions ? this.block.actions.length : this.block.items.length;
    for (let i = 0; i < n && i < max; i++) {
      const r: ChipRow = new ChipRow();
      r.index = i;
      r.tappable = useActions;
      r.label = useActions ? this.block.actions[i].label : this.block.items[i];
      r.key = i + ':' + r.label + ':' + (this.selected === i ? '1' : '0');
      out.push(r);
    }
    return out;
  }

  build() {
    Column({ space: 6 }) {
      if (this.block.text.length > 0 && !this.bs.compact) {
        Text(this.block.text)
          .fontSize(this.bs.fs(13))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.bs.fgDim)
          .maxLines(1)
      }
      Flex({ wrap: FlexWrap.Wrap, space: { main: LengthMetrics.vp(6), cross: LengthMetrics.vp(6) } }) {
        ForEach(this.rows(), (r: ChipRow) => {
          Row({ space: 6 }) {
            if (r.tappable && this.selected === r.index) {
              SymbolGlyph($r('sys.symbol.checkmark'))
                .fontSize(this.bs.fs(14))
                .fontColor([this.bs.onSolid])
            }
            Text(r.label)
              .fontSize(this.bs.fs(r.tappable ? 15 : 14))
              .fontWeight(r.tappable ? FontWeight.Bold : FontWeight.Medium)
              .fontColor(this.selected === r.index ? this.bs.onSolid : this.bs.fg)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
          .height(r.tappable ? (this.bs.compact ? 36 : this.bs.minTap - 4) : 30)
          .padding({ left: 12, right: 12 })
          .borderRadius(999)
          .backgroundColor(this.selected === r.index ? this.bs.solid : this.bs.well)
          .border({ width: (this.bs.highContrast || r.tappable) ? 1.5 : 0, color: this.bs.fg })
          .animation({ duration: this.bs.reduceMotion ? 0 : 180, curve: Curve.EaseOut })
          .accessibilityGroup(true)
          .accessibilityText(r.label + (this.selected === r.index ? ', selected' : ''))
          .onClick(() => {
            if (!r.tappable) {
              return;
            }
            this.selected = r.index;
            this.onAction(this.block.actions[r.index]);
          })
        }, (r: ChipRow) => r.key)
      }
      .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
