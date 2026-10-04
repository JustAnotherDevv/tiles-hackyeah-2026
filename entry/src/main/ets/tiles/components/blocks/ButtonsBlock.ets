import { LengthMetrics } from '@kit.ArkUI';
import { TileAction, TileBlock } from '../../model/Tile';
import { BlockStyle, actionIcon } from './BlockStyle';

class BtnRow {
  key: string = '';
  index: number = 0;
  action: TileAction = new TileAction();
}

/** `buttons`: block.actions as big pill buttons; the first is primary (solid), the rest are tonal. */
@Component
export struct ButtonsBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();
  onAction: (a: TileAction) => void = (a: TileAction) => {
  };

  private rows(): BtnRow[] {
    const max: number = this.bs.compact ? 1 : 4;
    const out: BtnRow[] = [];
    for (let i = 0; i < this.block.actions.length && i < max; i++) {
      const r: BtnRow = new BtnRow();
      r.index = i;
      r.action = this.block.actions[i];
      r.key = i + ':' + r.action.kind + ':' + r.action.label;
      out.push(r);
    }
    return out;
  }

  build() {
    Flex({
      wrap: FlexWrap.Wrap,
      alignItems: ItemAlign.Center,
      space: { main: LengthMetrics.vp(8), cross: LengthMetrics.vp(8) }
    }) {
      ForEach(this.rows(), (r: BtnRow) => {
        Row({ space: 8 }) {
          SymbolGlyph(actionIcon(r.action.kind))
            .fontSize(this.bs.fs(18))
            .fontColor([r.index === 0 ? this.bs.onSolid : this.bs.fg])
          Text(r.action.label.length > 0 ? r.action.label : r.action.kind)
            .fontSize(this.bs.fs(16))
            .fontWeight(FontWeight.Bold)
            .fontColor(r.index === 0 ? this.bs.onSolid : this.bs.fg)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .height(this.bs.compact ? 40 : this.bs.minTap)
        .padding({ left: 18, right: 18 })
        .borderRadius(999)
        .backgroundColor(r.index === 0 ? this.bs.solid : this.bs.well)
        .border({ width: this.bs.highContrast && r.index > 0 ? 2 : 0, color: this.bs.fg })
        .accessibilityGroup(true)
        .accessibilityText(r.action.label.length > 0 ? r.action.label : r.action.kind)
        .accessibilityRole(AccessibilityRoleType.BUTTON)
        .onClick(() => {
          this.onAction(r.action);
        })
      }, (r: BtnRow) => r.key)
    }
    .width('100%')
  }
}
