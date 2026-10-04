import { TileAction, TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

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
    const max: number = this.bs.compact ? 2 : (this.bs.detail ? 30 : 5);
    const out: CheckRow[] = [];
    for (let i = 0; i < this.block.items.length && i < max; i++) {
      const r: CheckRow = new CheckRow();
      r.index = i;
      r.text = this.block.items[i];
      r.done = i < this.done.length ? this.done[i] : false;
      r.key = i + ':' + r.text + ':' + (r.done ? '1' : '0');
      out.push(r);
    }
    return out;
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

  build() {
    Column({ space: 4 }) {
      if (this.block.text.length > 0 && !this.bs.compact) {
        Text(this.block.text + '  ·  ' + this.doneCount() + '/' + this.block.items.length)
          .fontSize(this.bs.fs(13))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.bs.fgDim)
          .maxLines(1)
      }
      ForEach(this.rows(), (r: CheckRow) => {
        Row({ space: 12 }) {
          Stack() {
            if (r.done) {
              SymbolGlyph($r('sys.symbol.checkmark'))
                .fontSize(this.bs.fs(16))
                .fontWeight(FontWeight.Bold)
                .fontColor([this.bs.bg])
            }
          }
          .width(28)
          .height(28)
          .borderRadius(9)
          .backgroundColor(r.done ? this.bs.fg : Color.Transparent)
          .border({ width: 2.5, color: this.bs.fg })
          .animation({ duration: this.bs.reduceMotion ? 0 : 180, curve: Curve.EaseOut })

          Text(r.text)
            .fontSize(this.bs.fs(16))
            .fontWeight(r.done ? FontWeight.Normal : FontWeight.Medium)
            .fontColor(r.done ? this.bs.fgDim : this.bs.fg)
            .decoration({ type: r.done ? TextDecorationType.LineThrough : TextDecorationType.None, color: this.bs.fgDim })
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
        }
        .width('100%')
        .constraintSize({ minHeight: this.bs.compact ? 36 : this.bs.minTap })
        .accessibilityGroup(true)
        .accessibilityText(r.text + (r.done ? ', done' : ', not done'))
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
