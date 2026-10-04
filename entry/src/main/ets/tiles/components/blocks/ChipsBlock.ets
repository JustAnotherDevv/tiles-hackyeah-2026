import { LengthMetrics, curves } from '@kit.ArkUI';
import { TileAction, TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

/** Living Light ease cubic-bezier(.22,1,.36,1). */
const LL_EASE: ICurve = curves.cubicBezierCurve(0.22, 1, 0.36, 1);

class ChipRow {
  key: string = '';
  index: number = 0;
  label: string = '';
  tappable: boolean = false;
}

/**
 * `chips` (Living Light): small translucent pills ("Ola ✓ · Kuba ? · You ✓"). Static `items` (tags), or tappable
 * `actions` (e.g. vote options): a tapped chip becomes the selected one (solid on-color pill) and emits its action.
 */
@Component
export struct ChipsBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();
  @State selected: number = -1;
  @State pressedIdx: number = -1;
  onAction: (a: TileAction) => void = (a: TileAction) => {
  };

  private rows(): ChipRow[] {
    const max: number = this.bs.limit(2, 2, 6, 20);
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

  /** Prototype chipSize = max(11, body * .85); tappable (vote) chips use the body size. */
  private chipFs(tappable: boolean): number {
    return tappable ? this.bs.bodySize : this.bs.chipSize;
  }

  private chipFg(i: number): string {
    return this.selected === i ? this.bs.onSolid : this.bs.fg;
  }

  build() {
    Column({ space: 6 }) {
      if (this.block.text.length > 0 && !this.bs.compact) {
        Text(this.block.text)
          .fontSize(this.bs.chipSize)
          .fontFamily(this.bs.font)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.bs.fg)
          .opacity(0.72)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      Flex({ wrap: FlexWrap.Wrap, space: { main: LengthMetrics.vp(6), cross: LengthMetrics.vp(6) } }) {
        ForEach(this.rows(), (r: ChipRow) => {
          Row({ space: 4 }) {
            if (r.tappable && this.selected === r.index) {
              SymbolGlyph($r('sys.symbol.checkmark'))
                .fontSize(this.chipFs(true))
                .fontColor([this.chipFg(r.index)])
            }
            Text(r.label)
              .fontSize(this.chipFs(r.tappable))
              .fontFamily(this.bs.font)
              .fontWeight(r.tappable ? 700 : 600)
              .fontColor(this.chipFg(r.index))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .flexShrink(1)
          }
          .constraintSize({
            maxWidth: '100%',
            minHeight: r.tappable ? (this.bs.compact ? 32 : Math.max(36, Math.round(this.bs.btnH * 0.9))) : 0
          })
          .padding(r.tappable ? { left: 14, right: 14, top: 6, bottom: 6 } : { left: 10, right: 10, top: 5, bottom: 5 })
          .borderRadius(999)
          .backgroundColor(this.selected === r.index ? this.bs.solid : this.bs.pill)
          .border({ width: this.bs.highContrast ? 1.5 : 0, color: this.bs.fg })
          .scale({ x: this.pressedIdx === r.index ? 0.95 : 1, y: this.pressedIdx === r.index ? 0.95 : 1 })
          .animation({ duration: this.bs.reduceMotion ? 0 : 240, curve: LL_EASE })
          .accessibilityGroup(true)
          .accessibilityText(r.label + (this.selected === r.index ? ', selected' : ''))
          .onTouch((e: TouchEvent) => {
            if (!r.tappable) {
              return;
            }
            e.stopPropagation();
            if (e.type === TouchType.Down) {
              this.pressedIdx = r.index;
            } else if (e.type === TouchType.Up || e.type === TouchType.Cancel) {
              this.pressedIdx = -1;
            }
          })
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

/** Prototype APP_ICONS (Material names) -> HarmonyOS symbols, in the same order (2 rows x 7). */
function appIcons(): Resource[] {
  return [
    $r('sys.symbol.plus_square_fill'), $r('sys.symbol.doc_text_fill'), $r('sys.symbol.map'),
    $r('sys.symbol.wallet_fill'), $r('sys.symbol.envelope_fill'), $r('sys.symbol.bag_fill'),
    $r('sys.symbol.headphones_fill'), $r('sys.symbol.globe_and_keyboard'), $r('sys.symbol.gamecontroller_fill'),
    $r('sys.symbol.paintbrush_fill'), $r('sys.symbol.dumbbell_fill'), $r('sys.symbol.play_video_fill'),
    $r('sys.symbol.book_pages_fill'), $r('sys.symbol.cloud_fill')
  ];
}

class AppCell {
  key: string = '';
  icon: Resource = $r('sys.symbol.map');
}

/**
 * `apps` (Living Light "More apps"): a 7-column grid of small rounded app wells (radius 9, rgba(0,0,0,.09), icon 17)
 * like the prototype. Pass block kind 'apps' (BlockView dispatch); `items` is ignored, the icon set is fixed.
 */
@Component
export struct AppsBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();

  private row(r: number): AppCell[] {
    const all: Resource[] = appIcons();
    const out: AppCell[] = [];
    for (let i = r * 7; i < r * 7 + 7 && i < all.length; i++) {
      const c: AppCell = new AppCell();
      c.key = 'app' + i;
      c.icon = all[i];
      out.push(c);
    }
    return out;
  }

  private cellH(): number {
    return Math.max(24, Math.round(this.bs.bodySize * 2));
  }

  @Builder
  appRow(r: number) {
    Row({ space: 6 }) {
      ForEach(this.row(r), (c: AppCell) => {
        Column() {
          SymbolGlyph(c.icon)
            .fontSize(17)
            .fontColor([this.bs.fg])
        }
        .layoutWeight(1)
        .height(this.cellH())
        .justifyContent(FlexAlign.Center)
        .borderRadius(9)
        .backgroundColor(this.bs.highContrast ? this.bs.pill : '#17000000')
      }, (c: AppCell) => c.key)
    }
    .width('100%')
  }

  build() {
    Column({ space: 6 }) {
      this.appRow(0)
      if (!this.bs.compact) {
        this.appRow(1)
      }
    }
    .width('100%')
    .accessibilityGroup(true)
    .accessibilityText('More apps: 14 apps')
  }
}
