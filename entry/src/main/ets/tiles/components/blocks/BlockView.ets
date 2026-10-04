import { TileAction, TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';
import { TextBlock } from './TextBlock';
import { BigBlock } from './BigBlock';
import { ListBlock } from './ListBlock';
import { ChecklistBlock } from './ChecklistBlock';
import { ProgressBlock } from './ProgressBlock';
import { ButtonsBlock } from './ButtonsBlock';
import { TimerBlock } from './TimerBlock';
import { ChipsBlock } from './ChipsBlock';
import { AlertBlock } from './AlertBlock';
import { WeatherBlock } from './WeatherBlock';

/** Dispatches one TileBlock to its renderer. Unknown kinds degrade to text (generated specs must never crash). */
@Component
export struct BlockView {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();
  @Prop blockIndex: number = 0;
  onAction: (a: TileAction) => void = (a: TileAction) => {
  };

  build() {
    if (this.block.kind === 'big') {
      BigBlock({ block: this.block, bs: this.bs })
    } else if (this.block.kind === 'list') {
      ListBlock({ block: this.block, bs: this.bs })
    } else if (this.block.kind === 'checklist') {
      ChecklistBlock({
        block: this.block, bs: this.bs, blockIndex: this.blockIndex, onAction: (a: TileAction) => {
          this.onAction(a);
        }
      })
    } else if (this.block.kind === 'progress') {
      ProgressBlock({ block: this.block, bs: this.bs })
    } else if (this.block.kind === 'buttons') {
      ButtonsBlock({
        block: this.block, bs: this.bs, onAction: (a: TileAction) => {
          this.onAction(a);
        }
      })
    } else if (this.block.kind === 'timer') {
      TimerBlock({
        block: this.block, bs: this.bs, onAction: (a: TileAction) => {
          this.onAction(a);
        }
      })
    } else if (this.block.kind === 'chips') {
      ChipsBlock({
        block: this.block, bs: this.bs, onAction: (a: TileAction) => {
          this.onAction(a);
        }
      })
    } else if (this.block.kind === 'alert') {
      AlertBlock({ block: this.block, bs: this.bs })
    } else if (this.block.kind === 'weather') {
      WeatherBlock({ block: this.block, bs: this.bs })
    } else {
      TextBlock({ block: this.block, bs: this.bs })
    }
  }
}
