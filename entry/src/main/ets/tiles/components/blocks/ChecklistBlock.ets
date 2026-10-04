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
    const max: number = this.bs.limit(2, 3, 5, 30);
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

  @Builder
  summary() {
    // Compact tiles: the checklist collapses to one key value ("2 of 6 done" + meter); tap the tile to tick items.
    Column({ space: 6 }) {
      Text(this.doneCount() + ' of ' + this.block.items.length + ' done')
        .fontSize(this.bs.fs(16))
        .fontWeight(FontWeight.Bold)
        .fontColor(this.bs.fg)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Stack({ alignContent: Alignment.Start }) {
        Row()
          .width('100%')
          .height(this.bs.highContrast ? 14 : 10)
          .borderRadius(8)
          .backgroundColor(this.bs.well)
          .border({ width: this.bs.highContrast ? 2 : 0, color: this.bs.fg })
        Row()
          .width(this.block.items.length > 0 ? Math.round(this.doneCount() * 100 / this.block.items.length) + '%' : '0%')
          .height(this.bs.highContrast ? 14 : 10)
          .borderRadius(8)
          .backgroundColor(this.bs.fg)
      }
      .width('100%')
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
    Column({ space: 4 }) {
      if (this.block.text.length > 0 && !this.bs.compact) {
        Text(this.block.text + '  ·  ' + this.doneCount() + '/' + this.block.items.length)
          .fontSize(this.bs.fs(13))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.bs.fgDim)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
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
            .fontSize(this.bs.fs(this.bs.narrow && !this.bs.detail ? 15 : 16))
            .fontWeight(r.done ? FontWeight.Normal : FontWeight.Medium)
            .fontColor(r.done ? this.bs.fgDim : this.bs.fg)
            .decoration({ type: r.done ? TextDecorationType.LineThrough : TextDecorationType.None, color: this.bs.fgDim })
            .maxLines(this.bs.narrow && !this.bs.detail ? 1 : 2)
            .wordBreak(WordBreak.NORMAL)
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
