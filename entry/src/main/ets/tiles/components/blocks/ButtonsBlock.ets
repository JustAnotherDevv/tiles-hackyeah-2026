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
    const max: number = this.bs.limit(1, 2, 4, 4);
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

  /** Narrow tiles: one full-width primary button reads better than a squeezed pill. */
  private fullWidth(): boolean {
    return this.bs.narrow && !this.bs.detail && this.rows().length === 1;
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
            .maxLines(this.bs.compact ? 1 : 2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.Center)
            .flexShrink(1)
        }
        .width(this.fullWidth() ? '100%' : 'auto')
        .justifyContent(FlexAlign.Center)
        // Min height (not fixed) so long labels at large text sizes wrap to 2 lines instead of truncating.
        .constraintSize({ maxWidth: '100%', minHeight: this.bs.compact ? Math.min(this.bs.minTap, 48) : this.bs.minTap })
        .padding({ left: this.bs.narrow ? 12 : 18, right: this.bs.narrow ? 12 : 18, top: 4, bottom: 4 })
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
