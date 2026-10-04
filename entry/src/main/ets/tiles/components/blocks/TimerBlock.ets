import { TileAction, TileBlock, Profile } from '../../model/Tile';
import { BlockStyle } from './BlockStyle';

/** Living Light "creature" (Mo, the kid profile's focus buddy): white blob with an ink face. */
const CREATURE_INK: string = '#2A2420';
/** Mo body / ring / shadow: white 90 %, lilac ring, soft violet drop shadow. */
const MO_BODY: string = '#E6FFFFFF';
const MO_RING: string = '#8C9A7FE0';
const MO_SHADOW: string = '#4D5B3FB8';
/** Prototype: blink 4.2 s (eyes squash to scaleY .08 at 95%), breathe 2.4 s while focusing. */
const BLINK_EVERY_MS: number = 4200;
const BREATHE_HALF_MS: number = 1200;

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
 * `timer` (Living Light): live countdown.
 *  - value "at:08:00" -> counts down to the next 08:00 (pills, departures); updates every second.
 *  - value "25" / "25m" / "25:00" -> focus timer: big tabular number + hint + round play/pause control.
 *    In the kid profile the focus timer is joined by Mo (gradient blob that blinks; breathes while running).
 *    Emits TileAction{ kind: 'timer', arg: 'start' | 'pause' | 'done' }.
 * `text` = label. Reduced motion: no blink / breathe.
 */
@Component
export struct TimerBlock {
  @Prop block: TileBlock = new TileBlock();
  @Prop bs: BlockStyle = new BlockStyle();
  @StorageProp('tiles.profile') profile: Profile = new Profile();
  @State nowMs: number = Date.now();
  @State remaining: number = 0;
  @State running: boolean = false;
  @State eyeScale: number = 1;
  @State moScale: number = 1;
  private total: number = 0;
  private handle: number = -1;
  private blinkHandle: number = -1;
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
      if (this.withMo() && !this.bs.reduceMotion) {
        this.blinkHandle = setInterval(() => {
          this.blink();
        }, BLINK_EVERY_MS);
      }
    }
  }

  aboutToDisappear(): void {
    this.stopTick();
    if (this.blinkHandle >= 0) {
      clearInterval(this.blinkHandle);
      this.blinkHandle = -1;
    }
  }

  private isClock(): boolean {
    return this.block.value.startsWith('at:');
  }

  /** Mo joins focus timers in the kid profile. */
  private withMo(): boolean {
    return !this.isClock() && this.profile !== undefined && this.profile.id === 'kid';
  }

  private blink(): void {
    if (this.bs.reduceMotion) {
      return;
    }
    animateTo({
      duration: 170, curve: Curve.EaseIn, onFinish: () => {
        animateTo({ duration: 170, curve: Curve.EaseOut }, () => {
          this.eyeScale = 1;
        });
      }
    }, () => {
      this.eyeScale = 0.08;
    });
  }

  private breathe(on: boolean): void {
    if (!this.withMo()) {
      return;
    }
    if (on && !this.bs.reduceMotion) {
      animateTo({ duration: BREATHE_HALF_MS, curve: Curve.EaseInOut, iterations: -1, playMode: PlayMode.Alternate }, () => {
        this.moScale = 1.05;
      });
    } else {
      animateTo({ duration: this.bs.reduceMotion ? 0 : 240, curve: Curve.EaseOut }, () => {
        this.moScale = 1;
      });
    }
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
    this.breathe(true);
    this.stopTick();
    this.handle = setInterval(() => {
      this.remaining = this.remaining - 1;
      if (this.remaining <= 0) {
        this.remaining = 0;
        this.running = false;
        this.breathe(false);
        this.stopTick();
        this.emit('done');
      }
    }, 1000);
    this.emit('start');
  }

  private pause(): void {
    this.running = false;
    this.breathe(false);
    this.stopTick();
    this.emit('pause');
  }

  private toggle(): void {
    if (this.running) {
      this.pause();
    } else {
      this.start();
    }
  }

  private reset(): void {
    this.running = false;
    this.breathe(false);
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

  /** Controls (hint + play button) only when the tile is wide enough; square tiles toggle on tap. */
  private showCtl(): boolean {
    return this.bs.detail || !this.bs.square;
  }

  /** Prototype numSize = 38 * fs; x.78 in tiny tiles, x.74 next to Mo in square tiles. */
  private numSize(): number {
    const base: number = this.bs.numSize;
    if (!this.bs.small && this.bs.square && this.withMo()) {
      return Math.round(base * 0.74);
    }
    return base;
  }

  private hint(): string {
    if (this.running) {
      return this.withMo() ? 'Mo is focusing too' : 'focusing';
    }
    if (this.withMo()) {
      return 'with Mo';
    }
    return this.block.text.length > 0 ? this.block.text : 'tap to start';
  }

  private btnSize(): number {
    return this.bs.minTap > 48 ? Math.max(this.bs.roundSize, 56) : this.bs.roundSize;
  }

  private moW(): number {
    return this.bs.detail ? 68 : 52;
  }

  private moH(): number {
    return this.bs.detail ? 63 : 48;
  }

  /** Mo: rounded blob, two blinking eyes, a mouth that widens into a smile while focusing. */
  @Builder
  creature() {
    Stack({ alignContent: Alignment.TopStart }) {
      Row()
        .width(7)
        .height(9)
        .borderRadius(4.5)
        .backgroundColor(CREATURE_INK)
        .scale({ x: 1, y: this.eyeScale })
        .position({ x: Math.round(this.moW() * 0.27), y: Math.round(this.moH() * 0.35) })
      Row()
        .width(7)
        .height(9)
        .borderRadius(4.5)
        .backgroundColor(CREATURE_INK)
        .scale({ x: 1, y: this.eyeScale })
        .position({ x: this.moW() - Math.round(this.moW() * 0.27) - 7, y: Math.round(this.moH() * 0.35) })
      Row()
        .width(this.running ? 18 : 12)
        .height(6)
        .borderRadius({ topLeft: 0, topRight: 0, bottomLeft: 8, bottomRight: 8 })
        .backgroundColor(CREATURE_INK)
        .position({ x: Math.round(this.moW() / 2) - (this.running ? 9 : 6), y: Math.round(this.moH() * 0.625) })
        .animation({ duration: this.bs.reduceMotion ? 0 : 300, curve: Curve.EaseOut })
    }
    .width(this.moW())
    .height(this.moH())
    .borderRadius({
      topLeft: Math.round(this.moW() / 2), topRight: Math.round(this.moW() / 2),
      bottomLeft: Math.round(this.moW() * 0.44), bottomRight: Math.round(this.moW() * 0.44)
    })
    // Visible on the lavender tile: near-white body (90 %) with a soft lilac ring + shadow, ink face (audit A08).
    .backgroundColor(this.bs.highContrast ? '#FFFFFF' : MO_BODY)
    .border({ width: this.bs.highContrast ? 2 : 1.5, color: this.bs.highContrast ? CREATURE_INK : MO_RING })
    .shadow({ radius: 10, color: MO_SHADOW, offsetX: 0, offsetY: 3 })
    .margin({ top: 2, bottom: 4 })
    .scale({ x: this.moScale, y: this.moScale })
    .accessibilityText(this.running ? 'Mo, focusing with you. Pause timer' : 'Mo. Start timer')
    .accessibilityRole(AccessibilityRoleType.BUTTON)
    .onClick(() => {
      this.toggle();
    })
  }

  @Builder
  roundBtn(icon: Resource, label: string, act: () => void) {
    Stack() {
      SymbolGlyph(icon)
        .fontSize(24)
        .fontColor([this.bs.fg])
    }
    .width(this.btnSize())
    .height(this.btnSize())
    .borderRadius(999)
    .backgroundColor(this.bs.highContrast ? this.bs.well : this.bs.roundFill)
    .border({ width: this.bs.highContrast ? 2 : 0, color: this.bs.fg })
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
          .fontSize(Math.round(this.numSize() * 0.74))
          .fontWeight(this.bs.numWeight)
            .fontFamily(this.bs.font)
          .fontColor(this.bs.fg)
          .letterSpacing(-0.03 * Math.round(this.numSize() * 0.74))
          .fontFeature('"tnum" on')
          .maxLines(1)
          .minFontSize(12)
          .maxFontSize(Math.round(this.numSize() * 0.74))
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text((this.block.text.length > 0 ? this.block.text + ' · ' : '') + this.clockTarget())
          .fontSize(this.bs.bodySize)
          .fontFamily(this.bs.font)
          .fontColor(this.bs.fg)
          .opacity(0.8)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
      .accessibilityGroup(true)
      .accessibilityText((this.block.text.length > 0 ? this.block.text + ', ' : '') + 'at ' + this.clockTarget() + ', ' +
      this.clockLeft())
    } else {
      Row({ space: 10 }) {
        if (this.withMo()) {
          this.creature()
        }
        Column({ space: 2 }) {
          Text(clockOf(this.remaining))
            .fontSize(this.numSize())
            .fontWeight(this.bs.numWeight)
            .fontFamily(this.bs.font)
            .fontColor(this.bs.fg)
            .letterSpacing(-0.03 * this.numSize())
            .lineHeight(Math.round(this.numSize() * 1.0))
            .fontFeature('"tnum" on')
            .maxLines(1)
            .minFontSize(14)
            .maxFontSize(this.numSize())
            .textOverflow({ overflow: TextOverflow.Clip })
          if (this.showCtl()) {
            Text(this.hint())
              .fontSize(this.bs.bodySize)
          .fontFamily(this.bs.font)
              .fontColor(this.bs.fg)
              .opacity(0.8)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        if (this.showCtl()) {
          if (this.bs.detail) {
            this.roundBtn($r('sys.symbol.arrow_counterclockwise'), 'Reset timer', () => {
              this.reset();
            })
          }
          this.roundBtn(this.running ? $r('sys.symbol.pause_fill') : $r('sys.symbol.play_fill'),
            this.running ? 'Pause timer' : 'Start timer', () => {
              this.toggle();
            })
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .accessibilityText((this.block.text.length > 0 ? this.block.text + '. ' : '') + 'Timer ' + clockOf(this.remaining) +
        (this.running ? ', running' : ', paused'))
      .onClick(() => {
        // Square tiles have no room for the control: tapping the timer starts / pauses (prototype behaviour).
        if (!this.showCtl()) {
          this.toggle();
        }
      })
    }
  }
}
