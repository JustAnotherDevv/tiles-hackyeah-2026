import { LengthMetrics, curves } from '@kit.ArkUI';
import { TileAction, TileBlock } from '../../model/Tile';
import { BlockStyle, actionIcon } from './BlockStyle';

/** Living Light ease cubic-bezier(.22,1,.36,1). */
const LL_EASE: ICurve = curves.cubicBezierCurve(0.22, 1, 0.36, 1);

class BtnRow {
  key: string = '';
  index: number = 0;
  action: TileAction = new TileAction();
}

/**
 * `buttons` (Living Light): block.actions as pills. The first is primary: bs.solid (the tile's on-color, dark ink
 * on pastel tiles) with bs.onSolid text; the rest are translucent pills in the on-color. Pressed pills scale
 * to .96 with the LL ease.
 */
@Component
export struct ButtonsBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();
  @State pressedIdx: number = -1;
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

  private btnBg(i: number): string {
    return i === 0 ? this.bs.solid : this.bs.pill;
  }

  private btnFg(i: number): string {
    return i === 0 ? this.bs.onSolid : this.bs.fg;
  }

  /** Prototype btnH = max(40, body * 2.5); senior / low-vision profiles keep their larger tap target. */
  private minH(): number {
    const floor: number = this.bs.minTap > 48 && !this.bs.compact ? this.bs.minTap : 0;
    return Math.max(this.bs.btnH, floor);
  }

  build() {
    Flex({
      wrap: FlexWrap.Wrap,
      alignItems: ItemAlign.Center,
      space: { main: LengthMetrics.vp(8), cross: LengthMetrics.vp(8) }
    }) {
      ForEach(this.rows(), (r: BtnRow) => {
        Row({ space: 6 }) {
          if (this.bs.detail) {
            SymbolGlyph(actionIcon(r.action.kind))
              .fontSize(Math.round(this.bs.bodySize * 1.15))
              .fontColor([this.btnFg(r.index)])
          }
          Text(r.action.label.length > 0 ? r.action.label : r.action.kind)
            .fontSize(this.bs.bodySize)
            .fontFamily(this.bs.font)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.btnFg(r.index))
            .maxLines(this.bs.compact ? 1 : 2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.Center)
            .flexShrink(1)
        }
        .width(this.fullWidth() ? '100%' : 'auto')
        .justifyContent(FlexAlign.Center)
        // Min height (not fixed) so long labels at large text sizes wrap to 2 lines instead of truncating.
        .constraintSize({ maxWidth: '100%', minHeight: this.minH() })
        .padding({ left: this.bs.btnPad, right: this.bs.btnPad, top: 4, bottom: 4 })
        .borderRadius(999)
        .backgroundColor(this.btnBg(r.index))
        .border({ width: this.bs.highContrast && r.index > 0 ? 2 : 0, color: this.bs.fg })
        .shadow(r.index === 0 && !this.bs.highContrast ?
          { radius: 14, offsetY: 6, color: '#331D2140' } : { radius: 0, color: Color.Transparent })
        .scale({ x: this.pressedIdx === r.index ? 0.96 : 1, y: this.pressedIdx === r.index ? 0.96 : 1 })
        .animation({ duration: this.bs.reduceMotion ? 0 : 240, curve: LL_EASE })
        .accessibilityGroup(true)
        .accessibilityText(r.action.label.length > 0 ? r.action.label : r.action.kind)
        .accessibilityRole(AccessibilityRoleType.BUTTON)
        .onTouch((e: TouchEvent) => {
          // Keep the press on the pill; don't let the whole tile depress.
          e.stopPropagation();
          if (e.type === TouchType.Down) {
            this.pressedIdx = r.index;
          } else if (e.type === TouchType.Up || e.type === TouchType.Cancel) {
            this.pressedIdx = -1;
          }
        })
        .onClick(() => {
          this.onAction(r.action);
        })
      }, (r: BtnRow) => r.key)
    }
    .width('100%')
  }
}
