import { TileAction, TileBlock } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

function pad2(n: number): string {
  return n < 10 ? '0' + n : '' + n;
}

/** Seconds -> "m:ss" / "h:mm:ss". */
export function clockOf(totalSec: number): string {
  const s: number = Math.max(0, Math.floor(totalSec));
  const h: number = Math.floor(s / 3600);
  const m: number = Math.floor((s % 3600) / 60);
  const r: number = s % 60;
  return h > 0 ? h + ':' + pad2(m) + ':' + pad2(r) : m + ':' + pad2(r);
}

/** "25" | "25m" | "25:00" -> seconds (default 25 min). */
export function durationOf(value: string): number {
  const v: string = value.trim().toLowerCase().replace('min', '').replace('m', '').trim();
  if (v.indexOf(':') > 0) {
    const parts: string[] = v.split(':');
    const mm: number = Number.parseInt(parts[0]);
    const ss: number = Number.parseInt(parts[1]);
    if (!isNaN(mm) && !isNaN(ss)) {
      return mm * 60 + ss;
    }
  }
  const n: number = Number.parseFloat(v);
  return !isNaN(n) && n > 0 ? Math.round(n * 60) : 25 * 60;
}

/** Next occurrence of "HH:MM" (today, or tomorrow if already past) as epoch ms; -1 if unparsable. */
export function nextAt(hhmm: string, nowMs: number): number {
  const parts: string[] = hhmm.trim().split(':');
  if (parts.length < 2) {
    return -1;
  }
  const h: number = Number.parseInt(parts[0]);
  const m: number = Number.parseInt(parts[1]);
  if (isNaN(h) || isNaN(m)) {
    return -1;
  }
  const d: Date = new Date(nowMs);
  d.setHours(h, m, 0, 0);
  let t: number = d.getTime();
  if (t <= nowMs) {
    t += 24 * 3600 * 1000;
  }
  return t;
}

/**
 * `timer`: live countdown.
 *  - value "at:08:00" -> counts down to the next 08:00 (pills, departures); updates every second.
 *  - value "25" / "25m" / "25:00" -> focus timer with start / pause / reset (local), emits
 *    TileAction{ kind: 'timer', arg: 'start' | 'pause' | 'done' }.
 * `text` = label.
 */
@Component
export struct TimerBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();
  @State nowMs: number = Date.now();
  @State remaining: number = 0;
  @State running: boolean = false;
  private total: number = 0;
  private handle: number = -1;
  onAction: (a: TileAction) => void = (a: TileAction) => {
  };

  aboutToAppear(): void {
    if (this.isClock()) {
      this.handle = setInterval(() => {
        this.nowMs = Date.now();
      }, 1000);
    } else {
      this.total = durationOf(this.block.value);
      this.remaining = this.total;
    }
  }

  aboutToDisappear(): void {
    this.stopTick();
  }

  private isClock(): boolean {
    return this.block.value.startsWith('at:');
  }

  private stopTick(): void {
    if (this.handle >= 0) {
      clearInterval(this.handle);
      this.handle = -1;
    }
  }

  private emit(arg: string): void {
    const a: TileAction = new TileAction();
    a.kind = 'timer';
    a.arg = arg;
    a.label = this.block.text;
    this.onAction(a);
  }

  private start(): void {
    if (this.remaining <= 0) {
      this.remaining = this.total;
    }
    this.running = true;
    this.stopTick();
    this.handle = setInterval(() => {
      this.remaining = this.remaining - 1;
      if (this.remaining <= 0) {
        this.remaining = 0;
        this.running = false;
        this.stopTick();
        this.emit('done');
      }
    }, 1000);
    this.emit('start');
  }

  private pause(): void {
    this.running = false;
    this.stopTick();
    this.emit('pause');
  }

  private reset(): void {
    this.running = false;
    this.stopTick();
    this.remaining = this.total;
  }

  private clockTarget(): string {
    return this.block.value.substring(3);
  }

  private clockLeft(): string {
    const t: number = nextAt(this.clockTarget(), this.nowMs);
    if (t < 0) {
      return '';
    }
    const sec: number = Math.floor((t - this.nowMs) / 1000);
    if (sec >= 3600) {
      const h: number = Math.floor(sec / 3600);
      const m: number = Math.floor((sec % 3600) / 60);
      return 'in ' + h + ' h ' + pad2(m) + ' min';
    }
    return 'in ' + clockOf(sec);
  }

  private fraction(): number {
    return this.total > 0 ? (this.total - this.remaining) / this.total : 0;
  }

  @Builder
  roundBtn(icon: Resource, label: string, primary: boolean, act: () => void) {
    Stack() {
      SymbolGlyph(icon)
        .fontSize(this.bs.fs(22))
        .fontColor([primary ? this.bs.onSolid : this.bs.fg])
    }
    .width(this.bs.compact ? 40 : this.bs.minTap)
    .height(this.bs.compact ? 40 : this.bs.minTap)
    .borderRadius(999)
    .backgroundColor(primary ? this.bs.solid : this.bs.well)
    .accessibilityText(label)
    .accessibilityRole(AccessibilityRoleType.BUTTON)
    .onClick(() => {
      act();
    })
  }

  build() {
    if (this.isClock()) {
      Column({ space: 2 }) {
        Text(this.clockLeft())
          .fontSize(this.bs.fs(this.bs.compact ? 22 : 34))
          .fontWeight(FontWeight.Bolder)
          .fontColor(this.bs.fg)
          .fontFeature('"tnum" on')
          .maxLines(1)
        Text((this.block.text.length > 0 ? this.block.text + ' · ' : '') + this.clockTarget())
          .fontSize(this.bs.fs(14))
          .fontWeight(FontWeight.Medium)
          .fontColor(this.bs.fgDim)
          .maxLines(1)
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
      .accessibilityGroup(true)
      .accessibilityText((this.block.text.length > 0 ? this.block.text + ', ' : '') + 'at ' + this.clockTarget() + ', ' +
      this.clockLeft())
    } else {
      Row({ space: 14 }) {
        Stack() {
          Progress({ value: Math.round(this.fraction() * 1000), total: 1000, type: ProgressType.Ring })
            .width(this.bs.compact ? 56 : 84)
            .height(this.bs.compact ? 56 : 84)
            .color(this.bs.fg)
            .backgroundColor(this.bs.well)
            .style({ strokeWidth: this.bs.compact ? 6 : 9 })
          Text(clockOf(this.remaining))
            .fontSize(this.bs.fs(this.bs.compact ? 14 : 19))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.bs.fg)
            .fontFeature('"tnum" on')
        }

        if (!this.bs.compact) {
          Column({ space: 8 }) {
            if (this.block.text.length > 0) {
              Text(this.block.text)
                .fontSize(this.bs.fs(15))
                .fontWeight(FontWeight.Medium)
                .fontColor(this.bs.fgDim)
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }
            Row({ space: 8 }) {
              if (this.running) {
                this.roundBtn($r('sys.symbol.pause_fill'), 'Pause timer', true, () => {
                  this.pause();
                })
              } else {
                this.roundBtn($r('sys.symbol.play_fill'), 'Start timer', true, () => {
                  this.start();
                })
              }
              this.roundBtn($r('sys.symbol.arrow_counterclockwise'), 'Reset timer', false, () => {
                this.reset();
              })
            }
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
        }
      }
      .width('100%')
      .accessibilityText('Timer ' + clockOf(this.remaining) + (this.running ? ', running' : ', paused'))
      .onClick(() => {
        // Compact (1x1) tiles have no room for buttons: tapping the ring starts / pauses.
        if (this.bs.compact) {
          if (this.running) {
            this.pause();
          } else {
            this.start();
          }
        }
      })
    }
  }
}
