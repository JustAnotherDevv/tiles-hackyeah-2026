import { TileAction, TileBlock } from '../../model/Tile';
import { curves } from '@kit.ArkUI';
import { BlockStyle } from './BlockStyle';

/** True when a #RRGGBB / #AARRGGBB color is dark (used to pick the check glyph color). */
function isDarkColor(c: string): boolean {
  const h: string = c.startsWith('#') ? c.substring(1) : c;
  const rgb: string = h.length === 8 ? h.substring(2) : h;
  if (rgb.length !== 6) {
    return true;
  }
  const r: number = parseInt(rgb.substring(0, 2), 16);
  const g: number = parseInt(rgb.substring(2, 4), 16);
  const b: number = parseInt(rgb.substring(4, 6), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) < 150;
}

class CheckRow {
  key: string = '';
  index: number = 0;
  text: string = '';
  done: boolean = false;
}

/**
 * `checklist`: items + checked[]. Tapping a row flips it locally (optimistic) and emits
 * TileAction{ kind: 'toggle', arg: '<blockIndex>:<itemIndex>', label: item } so the store can persist it.
 */
@Component
export struct ChecklistBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();
  @Prop blockIndex: number = 0;
  @State done: boolean[] = [];
  onAction: (a: TileAction) => void = (a: TileAction) => {
  };

  aboutToAppear(): void {
    const d: boolean[] = [];
    for (let i = 0; i < this.block.items.length; i++) {
      d.push(i < this.block.checked.length ? this.block.checked[i] === true : false);
    }
    this.done = d;
  }

  private rows(): CheckRow[] {
    // Wide (non-square) medium tiles are the 2x2 checklist tiles of scaled profiles: show all rows like the prototype.
    const max: number = this.bs.limit(2, this.bs.square ? 3 : 5, 5, 30);
    const out: CheckRow[] = [];
    for (let i = 0; i < this.block.items.length && i < max; i++) {
      const r: CheckRow = new CheckRow();
      r.index = i;
      r.text = this.block.items[i];
      r.done = i < this.done.length ? this.done[i] : false;
      r.key = i + ':' + r.text;
      out.push(r);
    }
    return out;
  }

  /** Read through @State so a toggle re-renders the (stably keyed) row and its transitions animate. */
  private isDone(i: number): boolean {
    return i < this.done.length ? this.done[i] : false;
  }

  private doneCount(): number {
    let n: number = 0;
    for (let i = 0; i < this.done.length; i++) {
      if (this.done[i]) {
        n++;
      }
    }
    return n;
  }

  private toggle(i: number): void {
    const next: boolean[] = this.done.slice();
    while (next.length <= i) {
      next.push(false);
    }
    next[i] = !next[i];
    this.done = next;
    const a: TileAction = new TileAction();
    a.kind = 'toggle';
    a.label = i < this.block.items.length ? this.block.items[i] : '';
    a.arg = this.blockIndex + ':' + i;
    this.onAction(a);
  }

  /** Check glyph on the filled circle: white on dark ink (Living Light gradients), tile color on light ink. */
  private checkColor(): string {
    return this.bs.highContrast ? (isDarkColor(this.bs.fg) ? '#FFFFFF' : this.bs.bg) : this.bs.onSolid;
  }

  private checkSize(): number {
    return this.bs.highContrast ? Math.max(28, this.bs.checkSize) : this.bs.checkSize;
  }

  @Builder
  summary() {
    // Compact tiles: the checklist collapses to one key value ("2 of 6 done" + meter); tap the tile to tick items.
    Column({ space: 7 }) {
      Text(this.doneCount() + ' of ' + this.block.items.length + ' done')
        .fontSize(Math.round(this.bs.bodySize * 1.15))
        .fontFamily(this.bs.font)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.bs.fg)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Stack({ alignContent: Alignment.Start }) {
        Row()
          .width(this.block.items.length > 0 ? Math.round(this.doneCount() * 100 / this.block.items.length) + '%' : '0%')
          .height('100%')
          .borderRadius(6)
          .backgroundColor(this.bs.fg)
          .animation({ duration: this.bs.reduceMotion ? 0 : 700, curve: curves.cubicBezierCurve(0.22, 1, 0.36, 1) })
      }
      .width('100%')
      .height(this.bs.highContrast ? 16 : this.bs.barH)
      .borderRadius(this.bs.highContrast ? 8 : this.bs.barH / 2)
      .backgroundColor(this.bs.highContrast ? this.bs.well : this.bs.track)
      .border({ width: this.bs.highContrast ? 2 : 0, color: this.bs.fg })
      .clip(true)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .accessibilityGroup(true)
    .accessibilityText((this.block.text.length > 0 ? this.block.text + ', ' : '') + this.doneCount() + ' of ' +
      this.block.items.length + ' done')
  }

  build() {
    if (this.bs.compact && !this.bs.detail) {
      this.summary()
    } else {
      this.fullList()
    }
  }

  @Builder
  fullList() {
    Column({ space: 2 }) {
      if (this.block.text.length > 0 && !this.bs.compact) {
        Text(this.block.text + '  ·  ' + this.doneCount() + '/' + this.block.items.length)
          .fontSize(Math.round(this.bs.bodySize * 0.93))
          .fontFamily(this.bs.font)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.bs.fg)
          .opacity(0.8)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ bottom: 2 })
      }
      ForEach(this.rows(), (r: CheckRow) => {
        Row({ space: 10 }) {
          // Living Light check circle: 24 vp ring in the tile ink, filled + white check when done.
          Stack() {
            SymbolGlyph($r('sys.symbol.checkmark'))
              .fontSize(Math.round(this.checkSize() * 0.64))
              .fontWeight(FontWeight.Bold)
              .fontColor([this.checkColor()])
              .opacity(this.isDone(r.index) ? 1 : 0)
          }
          .width(this.checkSize())
          .height(this.checkSize())
          .borderRadius(999)
          .backgroundColor(this.isDone(r.index) ? this.bs.fg : Color.Transparent)
          .border({ width: this.bs.highContrast ? 3 : this.bs.checkStroke, color: this.bs.fg })
          .animation({ duration: this.bs.reduceMotion ? 0 : 250, curve: Curve.EaseOut })

          Text(r.text)
            .fontSize(this.bs.bodySize)
            .fontFamily(this.bs.font)
            .fontColor(this.bs.fg)
            .fontWeight(FontWeight.Medium)
            .decoration({ type: this.isDone(r.index) ? TextDecorationType.LineThrough : TextDecorationType.None, color: this.bs.fg })
            .maxLines(this.bs.detail ? 2 : 1)
            .wordBreak(WordBreak.NORMAL)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
        }
        .width('100%')
        .constraintSize({ minHeight: this.bs.rowMin })
        .opacity(this.isDone(r.index) && !this.bs.highContrast ? 0.62 : 1)
        .animation({ duration: this.bs.reduceMotion ? 0 : 300, curve: Curve.EaseOut })
        .accessibilityGroup(true)
        .accessibilityText(r.text + (this.isDone(r.index) ? ', done' : ', not done'))
        .accessibilityDescription('Double tap to toggle')
        .onClick(() => {
          this.toggle(r.index);
        })
      }, (r: CheckRow) => r.key)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
