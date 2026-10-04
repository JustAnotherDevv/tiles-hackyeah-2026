import { curves, window } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';
import { Guardian, GuardianSample, GuardianVerdict, RedFlag } from '../ai/Guardian';
import { Profile } from '../model/Tile';
import { profileFor } from '../data/SeedTiles';
import { TileStore } from '../data/TileStore';
import { LL_FONT_FAMILY, TilesTheme, ThemePalette } from '../theme/TilesTheme';
import { TileNotifications } from '../platform/TileNotifications';
import { Calls } from '../platform/Calls';
import { Speech } from '../platform/Speech';
import { TilesPlatform, TLog } from '../platform/TilesPlatform';
import { Haptics } from '../../platform/Haptics';
import { K_DARK, K_REDUCE_MOTION } from './ShellKeys';

/** Map a RedFlag icon key to a system symbol ($r needs literal names). */
function flagIcon(icon: string): Resource {
  switch (icon) {
    case 'wallet_fill':
      return $r('sys.symbol.wallet_fill');
    case 'clock_fill':
      return $r('sys.symbol.clock_fill');
    case 'eye_slash':
      return $r('sys.symbol.eye_slash');
    case 'person_2':
      return $r('sys.symbol.person_2');
    case 'person_shield_fill':
      return $r('sys.symbol.person_shield_fill');
    case 'exclamationmark_triangle_fill':
      return $r('sys.symbol.exclamationmark_triangle_fill');
    case 'lock_fill':
      return $r('sys.symbol.lock_fill');
    case 'link':
      return $r('sys.symbol.link');
    case 'phone_badge_nosign':
      return $r('sys.symbol.phone_badge_nosign');
    default:
      return $r('sys.symbol.exclamationmark_triangle_fill');
  }
}

const CUSTOM_ID: string = 'custom';

// Living Light direction C (design/tiles-motion/source/Tiles_Stage.dc.html, guardian + call screens).
const LL_EASE: ICurve = curves.cubicBezierCurve(0.22, 1, 0.36, 1);
/** fxTS: transform .5s cubic-bezier(.34,1.56,.64,1) — the small overshoot used for pills popping in. */
const LL_POP: ICurve = curves.cubicBezierCurve(0.34, 1.56, 0.64, 1);
const CALL_GLASS: string = '#24FFFFFF'; // rgba(255,255,255,.14)
const RING_HALO: string = '#59787878'; // rgba(120,120,120,.35)
const SUN_BG1: string = '#FFE48F';
const SUN_BG2: string = '#FFB870';
const SUN_ON: string = '#3B2500';
/** Time between transcript lines appearing (prototype: 1.6 s). */
const LINE_MS: number = 1600;
/** Incoming-call ring before the (demo) call is answered and Guardian starts listening. */
const RING_MS: number = 2200;

@Extend(Text)
function llText(size: number, weight: number, color: ResourceColor) {
  .fontFamily(LL_FONT_FAMILY)
  .fontSize(size)
  .fontWeight(weight)
  .fontColor(color)
}

/** One transcript line: a sentence (or a comma-delimited part of a long one) with its offsets in the text. */
class Chunk {
  text: string = '';
  start: number = 0;
  end: number = 0;

  constructor(text: string, start: number, end: number) {
    this.text = text;
    this.start = start;
    this.end = end;
  }
}

/** Split a transcript / message into short lines that "arrive" one by one (sentences; long ones at commas). */
function splitChunks(text: string): Chunk[] {
  const out: Chunk[] = [];
  const pushRange = (a: number, b: number): void => {
    let s: number = a;
    let e: number = b;
    while (s < e && text.charAt(s) === ' ') {
      s++;
    }
    while (e > s && text.charAt(e - 1) === ' ') {
      e--;
    }
    if (e > s) {
      out.push(new Chunk(text.substring(s, e), s, e));
    }
  };
  const pushSentence = (a: number, b: number): void => {
    if (b - a <= 56) {
      pushRange(a, b);
      return;
    }
    let from: number = a;
    for (let i = a; i < b - 1; i++) {
      if (text.charAt(i) === ',' && text.charAt(i + 1) === ' ' && i + 1 - from >= 30 && b - (i + 2) >= 15) {
        pushRange(from, i + 1);
        from = i + 2;
      }
    }
    pushRange(from, b);
  };
  let start: number = 0;
  for (let i = 0; i < text.length; i++) {
    const c: string = text.charAt(i);
    if ((c === '.' || c === '!' || c === '?') && (i + 1 >= text.length || text.charAt(i + 1) === ' ')) {
      pushSentence(start, i + 1);
      start = i + 1;
    }
  }
  if (start < text.length) {
    pushSentence(start, text.length);
  }
  if (out.length === 0) {
    out.push(new Chunk(text, 0, text.length));
  }
  return out;
}

class ShownLine {
  key: string = '';
  text: string = '';

  constructor(key: string, text: string) {
    this.key = key;
    this.text = text;
  }
}

/**
 * Guardian (route 'guardian'): on-device scam shield for seniors, styled as direction C "Living Light".
 * A simulated demo call rings on the call screen, then Guardian "listens": the transcript arrives line by line,
 * red flags pop in, the risk meter climbs, and a calm full-screen instruction follows ("This looks like a scam.
 * Hang up. Kasia already knows.") with Hang up / Call Kasia. Caregiver alert via Notification Kit, PII-redacted
 * share preview and "check a message yourself" sit below the verdict. All inputs are simulated and labelled.
 */
@Component
export struct GuardianView {
  @Consume('tilesNav') nav: NavPathStack;
  @StorageProp(K_REDUCE_MOTION) reduceMotion: boolean = false;
  @State profile: Profile = profileFor('senior');
  @StorageProp(K_DARK) dark: boolean = false;
  @State samples: GuardianSample[] = Guardian.samples();
  @State sample: GuardianSample = Guardian.samples()[0];
  @State verdict: GuardianVerdict = new GuardianVerdict();
  @State phase: string = 'listening'; // ring | listening | done
  @State lines: ShownLine[] = [];
  @State flagsShown: RedFlag[] = [];
  @State meter: number = 0; // animated bar 0..100
  @State shown: number = 0; // counting-up number 0..100
  @State ended: boolean = false; // "Hang up" pressed
  @State alertState: string = ''; // '' | sending | sent | failed
  @State custom: string = '';
  @State ringOn: boolean = false;
  @State pulseOn: boolean = false;
  @State endedIn: boolean = false;
  @State viewH: number = 640;
  /** Status-bar height (vp) and where our root starts: the window is full-screen (immersive). */
  @State sysTop: number = 0;
  @State rootY: number = 0;
  private chunks: Chunk[] = [];
  private flagLine: number[] = [];
  private stepTimer: number = -1;
  private countTimer: number = -1;
  private alive: boolean = true;
  private runId: number = 0;

  aboutToAppear(): void {
    try {
      const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
      window.getLastWindow(ctx).then((win: window.Window) => {
        const area: window.AvoidArea = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);
        this.sysTop = this.getUIContext().px2vp(area.topRect.height);
      }).catch(() => {
      });
    } catch (e) {
      // no window (preview)
    }
    this.profile = this.loadProfile();
    this.run(this.sample);
  }

  aboutToDisappear(): void {
    this.alive = false;
    this.clearTimers();
  }

  private loadProfile(): Profile {
    try {
      return TileStore.get().profile();
    } catch (e) {
      TLog.warn('guardian: store not ready, using senior profile');
      return profileFor('senior');
    }
  }

  private caregiver(): string {
    return this.profile.caregiver.length > 0 ? this.profile.caregiver : 'Kasia';
  }

  private clearTimers(): void {
    if (this.stepTimer >= 0) {
      clearTimeout(this.stepTimer);
      this.stepTimer = -1;
    }
    if (this.countTimer >= 0) {
      clearInterval(this.countTimer);
      this.countTimer = -1;
    }
  }

  private later(ms: number, fn: () => void): void {
    const id: number = this.runId;
    this.stepTimer = setTimeout(() => {
      this.stepTimer = -1;
      if (!this.alive || id !== this.runId) {
        return;
      }
      fn();
    }, ms);
  }

  /** Analyse a sample, then play it: ring (calls) -> transcript lines + flags + climbing risk -> verdict. */
  private run(s: GuardianSample): void {
    this.clearTimers();
    this.runId++;
    this.sample = s;
    this.ended = false;
    this.endedIn = false;
    this.alertState = '';
    this.meter = 0;
    this.shown = 0;
    this.lines = [];
    this.flagsShown = [];
    this.verdict = Guardian.analyze(s.text, s.knownContact, s.lang, this.caregiver(), s.kind);
    TLog.info('guardian analysed ' + s.id + ' risk=' + this.verdict.risk + ' flags=' + this.verdict.flags.length);
    this.chunks = splitChunks(s.text);
    this.flagLine = this.verdict.flags.map((f: RedFlag) => this.lineForFlag(f));

    if (this.reduceMotion) {
      this.phase = 'listening';
      this.lines = this.chunks.map((c: Chunk, i: number) => new ShownLine(this.runId + ':' + i, c.text));
      this.flagsShown = this.verdict.flags.slice();
      this.meter = this.verdict.risk;
      this.shown = this.verdict.risk;
      this.later(900, () => this.finish());
      return;
    }
    if (s.kind === 'call') {
      this.ringOn = false;
      this.phase = 'ring';
      this.later(RING_MS, () => {
        this.getUIContext().animateTo({ duration: TilesTheme.LL_DUR, curve: LL_EASE }, () => {
          this.phase = 'listening';
        });
        this.later(700, () => this.step(0));
      });
    } else {
      this.phase = 'listening';
      this.later(500, () => this.step(0));
    }
  }

  /** The transcript line after which a flag "fires" (metadata flags such as Unknown number fire on line 0). */
  private lineForFlag(f: RedFlag): number {
    let ev: string = f.evidence;
    if (ev.endsWith('…')) {
      ev = ev.substring(0, ev.length - 1);
    }
    if (ev.length === 0) {
      return 0;
    }
    const at: number = this.sample.text.indexOf(ev);
    if (at < 0) {
      return this.chunks.length - 1;
    }
    const end: number = at + ev.length;
    for (let i = 0; i < this.chunks.length; i++) {
      if (end <= this.chunks[i].end) {
        return i;
      }
    }
    return this.chunks.length - 1;
  }

  private step(i: number): void {
    if (i >= this.chunks.length) {
      this.finish();
      return;
    }
    this.lines = this.lines.concat([new ShownLine(this.runId + ':' + i, this.chunks[i].text)]);
    const add: RedFlag[] = [];
    for (let k = 0; k < this.verdict.flags.length; k++) {
      if (this.flagLine[k] === i) {
        add.push(this.verdict.flags[k]);
      }
    }
    if (add.length > 0) {
      this.flagsShown = this.flagsShown.concat(add);
    }
    this.climbTo(this.riskAfter(i));
    if (i + 1 < this.chunks.length) {
      this.later(LINE_MS, () => this.step(i + 1));
    } else {
      this.later(LINE_MS, () => this.finish());
    }
  }

  /** Risk after line i: share of flag points revealed so far (or of lines, when there are no flags). */
  private riskAfter(i: number): number {
    const risk: number = this.verdict.risk;
    if (i >= this.chunks.length - 1) {
      return risk;
    }
    let total: number = 0;
    let seen: number = 0;
    for (let k = 0; k < this.verdict.flags.length; k++) {
      total += this.verdict.flags[k].points;
      if (this.flagLine[k] <= i) {
        seen += this.verdict.flags[k].points;
      }
    }
    const frac: number = total > 0 ? seen / total : (i + 1) / this.chunks.length;
    return Math.max(Math.min(risk, 8), Math.round(risk * frac * 0.92));
  }

  /** Risk meter: bar eases (0.9 s, LL ease) while the number counts up. */
  private climbTo(target: number): void {
    this.getUIContext().animateTo({ duration: 900, curve: LL_EASE }, () => {
      this.meter = target;
    });
    if (this.countTimer >= 0) {
      clearInterval(this.countTimer);
      this.countTimer = -1;
    }
    const from: number = this.shown;
    const steps: number = 18;
    let n: number = 0;
    this.countTimer = setInterval(() => {
      n++;
      const t: number = n / steps;
      this.shown = Math.round(from + (target - from) * (1 - Math.pow(1 - t, 3)));
      if (n >= steps) {
        clearInterval(this.countTimer);
        this.countTimer = -1;
        this.shown = target;
      }
    }, 40);
  }

  /** Verdict: the calm full-screen instruction. Scam -> haptic + caregiver alert (unchanged behaviour). */
  private finish(): void {
    this.flagsShown = this.verdict.flags.slice();
    this.meter = this.verdict.risk;
    this.shown = this.verdict.risk;
    this.getUIContext().animateTo({ duration: TilesTheme.dur(TilesTheme.LL_DUR, this.reduceMotion), curve: LL_EASE },
      () => {
        this.phase = 'done';
      });
    if (this.verdict.level === 'scam') {
      Haptics.notice();
      this.alertCaregiver();
    }
  }

  /** Caregiver alert via Notification Kit (published on this phone, labelled as sent to the caregiver, demo). */
  private alertCaregiver(): void {
    if (this.alertState === 'sending' || this.alertState === 'sent') {
      return;
    }
    this.alertState = 'sending';
    const name: string = this.profile.name.length > 0 ? this.profile.name : 'Your relative';
    const title: string = this.sample.kind === 'call' ? 'Guardian: ' + name + ' may be on a scam call' :
      'Guardian: ' + name + ' got a suspicious message';
    const body: string = this.verdict.alertBody;
    const who: string = this.caregiver();
    TileNotifications.requestPermission(false).then((enabled: boolean) => {
      if (!enabled) {
        TLog.warn('guardian alert: notifications not enabled');
        return false;
      }
      return TileNotifications.caregiverAlert(who, title, body, 'guardian', 'guardian');
    }).then((ok: boolean) => {
      if (this.alive) {
        this.alertState = ok ? 'sent' : 'failed';
      }
    }).catch(() => {
      if (this.alive) {
        this.alertState = 'failed';
      }
    });
  }

  private hangUp(): void {
    Haptics.success();
    this.clearTimers();
    this.runId++;
    this.getUIContext().animateTo({ duration: TilesTheme.dur(TilesTheme.LL_DUR, this.reduceMotion), curve: LL_EASE },
      () => {
        this.ended = true;
        this.phase = 'done';
      });
    TilesPlatform.toast(this.sample.kind === 'call' ? 'Call ended (demo call)' : 'Message ignored (demo SMS)');
  }

  private callCaregiver(): void {
    const who: string = this.caregiver();
    Calls.dial(who, who).then((opened: boolean) => {
      TLog.info('guardian call ' + who + ' opened=' + opened);
    });
  }

  private readAloud(): void {
    Speech.speak(this.verdict.headline + ' ' + this.verdict.instruction, 'guardian');
  }

  private checkCustom(): void {
    const text: string = this.custom.trim();
    if (text.length === 0) {
      return;
    }
    const s: GuardianSample = new GuardianSample();
    s.id = CUSTOM_ID + '-' + Date.now().toString();
    s.kind = 'sms';
    s.lang = Guardian.detectLang(text);
    s.chip = 'Your text';
    s.from = 'Pasted text';
    s.knownContact = false;
    s.text = text;
    this.run(s);
  }

  private pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }

  private isCall(): boolean {
    return this.sample.kind === 'call';
  }

  private riskColor(v: number): string {
    return v < 40 ? this.pal().ok : (v < 75 ? this.pal().accent : this.pal().danger);
  }

  private flagLabel(f: RedFlag): string {
    return this.sample.lang === 'pl' ? f.labelPl : f.label;
  }

  private caregiverStatus(): string {
    const who: string = this.caregiver();
    if (this.alertState === 'sent') {
      return who + ' already knows · demo alert';
    }
    if (this.alertState === 'sending') {
      return 'Telling ' + who + '…';
    }
    if (this.alertState === 'failed') {
      return 'Could not alert ' + who + ' (notifications off)';
    }
    return this.verdict.level === 'safe' ? 'Nothing to tell ' + who : who + ' has not been told yet';
  }

  build() {
    NavDestination() {
      Stack({ alignContent: Alignment.Top }) {
        // Page gradient under the status / navigation bars; content itself stays inside the safe area.
        Column()
          .width('100%')
          .height('100%')
          .linearGradient({ angle: this.pal().bgGradient.angle, colors: this.pal().bgGradient.colors })
          .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
        Column() {
          this.TopBar()
          if (this.phase === 'done') {
            this.DoneScroll()
          } else {
            this.LiveScreen()
          }
        }
        .width('100%')
        .height('100%')
        .padding({ top: Math.max(0, this.sysTop - this.rootY) })
        .onAreaChange((o: Area, n: Area) => {
          const y: number = Number(n.globalPosition.y);
          if (!isNaN(y) && Math.abs(y - this.rootY) > 0.5) {
            this.rootY = y;
          }
        })

        if (this.phase === 'ring') {
          this.CallScreen()
        }
      }
      .width('100%')
      .height('100%')
    }
    .hideTitleBar(true)
    .backgroundColor(this.pal().bg)
  }

  // ---------------------------------------------------------------- top bar (back + labelled demo inputs)

  @Builder
  TopBar() {
    Row({ space: 10 }) {
      Button({ type: ButtonType.Circle }) {
        SymbolGlyph($r('sys.symbol.chevron_left'))
          .fontSize(24)
          .fontColor([this.pal().ink])
      }
      .width(48)
      .height(48)
      .backgroundColor(this.pal().surface)
      .shadow(TilesTheme.LL_SHADOW_SOFT)
      .accessibilityText('Back')
      .onClick(() => {
        this.nav.pop();
      })

      Scroll() {
        Row({ space: 8 }) {
          ForEach(this.samples, (s: GuardianSample) => {
            Text(s.chip)
              .llText(14, 700, s.id === this.sample.id ? this.pal().onInk : this.pal().ink)
              .padding({ left: 14, right: 14 })
              .height(40)
              .borderRadius(TilesTheme.LL_RADIUS_PILL)
              .backgroundColor(s.id === this.sample.id ? this.pal().ink : this.pal().surface2)
              .accessibilityText(s.chip + (s.id === this.sample.id ? ', selected' : ''))
              .onClick(() => {
                this.run(s);
              })
          }, (s: GuardianSample) => s.id)
        }
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .edgeEffect(EdgeEffect.Spring)
      .layoutWeight(1)
    }
    .width('100%')
    .padding({ left: 20, right: 0, top: 8, bottom: 4 })
    .alignItems(VerticalAlign.Center)
  }

  // ---------------------------------------------------------------- incoming call (callBg)

  @Builder
  CallScreen() {
    Column() {
      Column({ space: 18 }) {
        Stack() {
          Circle()
            .width(128)
            .height(128)
            .fill(RING_HALO)
            .scale({ x: this.ringOn ? 1.44 : 1, y: this.ringOn ? 1.44 : 1 })
            .opacity(this.ringOn ? 0 : 1)
            .animation({ duration: TilesTheme.LL_RING_MS, curve: Curve.EaseOut, iterations: -1 })
          Stack() {
            SymbolGlyph($r('sys.symbol.person_fill'))
              .fontSize(60)
              .fontColor([SUN_ON])
          }
          .width(128)
          .height(128)
          .borderRadius(64)
          .linearGradient({ angle: 135, colors: [[SUN_BG1, 0.0], [SUN_BG2, 1.0]] })
        }
        .width(128)
        .height(128)
        .onAppear(() => {
          setTimeout(() => {
            this.ringOn = true;
          }, 60);
        })

        Text(this.sample.from)
          .llText(36, 700, this.pal().callFg)
          .letterSpacing(-0.7)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text('Incoming call · demo')
          .llText(19, 500, this.pal().callFg)
          .opacity(0.75)
        Row({ space: 6 }) {
          SymbolGlyph($r('sys.symbol.checkmark_shield_fill'))
            .fontSize(18)
            .fontColor([this.pal().callFg])
          Text('Guardian is listening')
            .llText(14, 700, this.pal().callFg)
        }
        .padding({ left: 12, right: 14, top: 8, bottom: 8 })
        .borderRadius(TilesTheme.LL_RADIUS_PILL)
        .backgroundColor(CALL_GLASS)
      }
      .alignItems(HorizontalAlign.Center)

      Row({ space: 28 }) {
        Stack() {
          SymbolGlyph($r('sys.symbol.mic_slash_fill'))
            .fontSize(28)
            .fontColor([this.pal().callFg])
        }
        .width(64)
        .height(64)
        .borderRadius(32)
        .backgroundColor(CALL_GLASS)

        Button({ type: ButtonType.Circle }) {
          SymbolGlyph($r('sys.symbol.phone_down_fill'))
            .fontSize(38)
            .fontColor(['#FFFFFF'])
        }
        .width(84)
        .height(84)
        .backgroundColor('#C62B4A')
        .shadow({ radius: 24, color: '#80000000', offsetX: 0, offsetY: 12 })
        .accessibilityText('Hang up')
        .onClick(() => {
          this.hangUp();
        })

        Stack() {
          SymbolGlyph($r('sys.symbol.speaker_wave_2_fill'))
            .fontSize(28)
            .fontColor([this.pal().callFg])
        }
        .width(64)
        .height(64)
        .borderRadius(32)
        .backgroundColor(CALL_GLASS)
      }
    }
    .width('100%')
    .height('100%')
    .justifyContent(FlexAlign.SpaceBetween)
    .alignItems(HorizontalAlign.Center)
    .padding({ left: 24, right: 24, top: 96, bottom: 64 })
    .linearGradient({ angle: this.pal().callBg.angle, colors: this.pal().callBg.colors })
    .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.scale({ x: 1.04, y: 1.04 }))
      .animation({ duration: TilesTheme.LL_DUR, curve: LL_EASE }))
  }

  // ---------------------------------------------------------------- listening (transcript, flags, risk)

  @Builder
  LiveScreen() {
    Column() {
      Row({ space: 12 }) {
        Stack() {
          SymbolGlyph($r('sys.symbol.person_fill'))
            .fontSize(30)
            .fontColor([this.pal().ink])
        }
        .width(56)
        .height(56)
        .borderRadius(28)
        .backgroundColor(this.pal().surface2)

        Column({ space: 2 }) {
          Text(this.sample.from)
            .llText(21, 700, this.pal().ink)
            .letterSpacing(TilesTheme.letterSpacing(21))
            .maxFontSize(21)
            .minFontSize(16)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(this.sample.id.startsWith(CUSTOM_ID) ? 'Your text · checked here' :
            (this.isCall() ? 'Demo call · simulated' : 'Demo SMS · simulated'))
            .llText(14, 500, this.pal().muted)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Row({ space: 6 }) {
          SymbolGlyph($r('sys.symbol.checkmark_shield_fill'))
            .fontSize(18)
            .fontColor([this.pal().okInk])
            .opacity(this.pulseOn ? 0.45 : 1)
            .scale({ x: this.pulseOn ? 0.8 : 1, y: this.pulseOn ? 0.8 : 1 })
            .animation({
              duration: TilesTheme.LL_PULSE_MS / 2,
              curve: Curve.EaseInOut,
              iterations: -1,
              playMode: PlayMode.Alternate
            })
          Text(this.lines.length === 0 ? 'Guardian on' : (this.isCall() ? 'Listening' : 'Reading'))
            .llText(13, 700, this.pal().okInk)
            .maxLines(1)
        }
        .padding({ left: 12, right: 12, top: 8, bottom: 8 })
        .borderRadius(TilesTheme.LL_RADIUS_PILL)
        .backgroundColor(this.pal().okSoft)
        .onAppear(() => {
          if (!this.reduceMotion) {
            setTimeout(() => {
              this.pulseOn = true;
            }, 60);
          }
        })
        .onDisAppear(() => {
          this.pulseOn = false;
        })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Column({ space: 10 }) {
        ForEach(this.lines, (ln: ShownLine) => {
          Text(ln.text)
            .llText(17, 500, this.pal().ink)
            .lineHeight(23)
            .padding({ left: 16, right: 16, top: 12, bottom: 12 })
            .borderRadius(TilesTheme.LL_RADIUS_M)
            .backgroundColor(this.pal().surface)
            .shadow(TilesTheme.LL_SHADOW_TILE)
            .constraintSize({ maxWidth: '88%' })
            .alignSelf(ItemAlign.Start)
            .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 24 }))
              .animation({ duration: TilesTheme.dur(500, this.reduceMotion), curve: LL_EASE }))
        }, (ln: ShownLine) => ln.key)

        Flex({ wrap: FlexWrap.Wrap }) {
          ForEach(this.flagsShown, (f: RedFlag) => {
            Row({ space: 6 }) {
              SymbolGlyph($r('sys.symbol.flag_fill'))
                .fontSize(18)
                .fontColor([this.pal().dangerInk])
              Text(this.flagLabel(f))
                .llText(14, 700, this.pal().dangerInk)
                .maxLines(1)
            }
            .padding({ left: 12, right: 12, top: 8, bottom: 8 })
            .margin({ right: 8, bottom: 8 })
            .borderRadius(TilesTheme.LL_RADIUS_PILL)
            .backgroundColor(this.pal().dangerSoft)
            .transition(TransitionEffect.OPACITY.combine(TransitionEffect.scale({ x: 0.6, y: 0.6 }))
              .animation({ duration: TilesTheme.dur(500, this.reduceMotion), curve: LL_POP }))
          }, (f: RedFlag) => this.runId + ':' + f.id)
        }
        .width('100%')
        .margin({ top: 6 })
      }
      .width('100%')
      .layoutWeight(1)
      .margin({ top: 22 })
      .alignItems(HorizontalAlign.Start)
      .clip(true)

      this.RiskMeter()

      Row({ space: 10 }) {
        Button({ type: ButtonType.Capsule }) {
          Row({ space: 8 }) {
            SymbolGlyph($r('sys.symbol.phone_down_fill'))
              .fontSize(24)
              .fontColor([this.pal().onDanger])
            Text(this.isCall() ? 'Hang up' : 'Ignore')
              .llText(18, 800, this.pal().onDanger)
          }
        }
        .layoutWeight(1)
        .height(64)
        .backgroundColor(this.pal().danger)
        .accessibilityText(this.isCall() ? 'Hang up' : 'Ignore message')
        .onClick(() => {
          this.hangUp();
        })

        Button({ type: ButtonType.Capsule }) {
          Text(this.isCall() ? 'Keep listening' : 'Keep reading')
            .llText(16, 600, this.pal().muted)
        }
        .layoutWeight(1)
        .height(64)
        .backgroundColor(Color.Transparent)
        .border({ width: 1.5, color: this.pal().line })
      }
      .width('100%')
      .margin({ top: 22 })
    }
    .width('100%')
    .layoutWeight(1)
    .padding({ left: 20, right: 20, top: 14, bottom: 28 })
  }

  @Builder
  RiskMeter() {
    Column({ space: 10 }) {
      Row() {
        Text('SCAM RISK')
          .llText(15, 700, this.pal().muted)
          .letterSpacing(1.2)
          .layoutWeight(1)
        Text(this.shown.toString() + '%')
          .llText(44, 800, this.riskColor(this.shown))
          .letterSpacing(-1.3)
      }
      .width('100%')
      .alignItems(VerticalAlign.Bottom)

      Stack({ alignContent: Alignment.Start }) {
        Row()
          .width(Math.max(0, Math.min(100, this.meter)).toString() + '%')
          .height('100%')
          .borderRadius(6)
          .backgroundColor(this.riskColor(this.meter))
      }
      .width('100%')
      .height(12)
      .borderRadius(6)
      .backgroundColor(this.pal().surface2)
      .clip(true)
    }
    .width('100%')
    .margin({ top: 16 })
    .accessibilityGroup(true)
    .accessibilityText('Scam risk ' + this.shown.toString() + ' percent')
  }

  // ---------------------------------------------------------------- verdict / ended (full screen + details)

  @Builder
  DoneScroll() {
    Scroll() {
      Column() {
        if (this.ended) {
          this.EndedHero()
        } else {
          this.VerdictHero()
        }
        this.Details()
      }
      .width('100%')
    }
    .scrollBar(BarState.Off)
    .edgeEffect(EdgeEffect.Spring)
    .width('100%')
    .layoutWeight(1)
    .onAreaChange((o: Area, n: Area) => {
      const h: number = Number(n.height);
      if (h > 0 && Math.abs(h - this.viewH) > 1) {
        this.viewH = h;
      }
    })
  }

  @Builder
  VerdictHero() {
    Column() {
      Blank()
      Column({ space: 18 }) {
        Stack() {
          if (this.verdict.level === 'safe') {
            SymbolGlyph($r('sys.symbol.checkmark_shield_fill'))
              .fontSize(56)
              .fontColor([this.pal().okInk])
          } else if (this.verdict.level === 'caution') {
            SymbolGlyph($r('sys.symbol.exclamationmark_triangle_fill'))
              .fontSize(52)
              .fontColor([SUN_ON])
          } else {
            SymbolGlyph($r('sys.symbol.exclamationmark_shield_fill'))
              .fontSize(56)
              .fontColor([this.pal().dangerInk])
          }
        }
        .width(104)
        .height(104)
        .borderRadius(52)
        .backgroundColor(this.verdict.level === 'safe' ? this.pal().okSoft :
          (this.verdict.level === 'caution' ? SUN_BG1 : this.pal().dangerSoft))

        Text(this.verdict.headline)
          .llText(38, 700, this.pal().ink)
          .lineHeight(41)
          .letterSpacing(-0.76)
          .textAlign(TextAlign.Center)
        Text(this.verdict.instruction)
          .llText(24, 500, this.pal().muted)
          .lineHeight(31)
          .textAlign(TextAlign.Center)
        if (this.sample.lang === 'pl') {
          Text(this.verdict.headlineEn + ' ' + this.verdict.instructionEn)
            .llText(15, 500, this.pal().muted)
            .textAlign(TextAlign.Center)
        }

        Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.Center }) {
          if (this.verdict.flags.length === 0) {
            Row({ space: 6 }) {
              SymbolGlyph($r('sys.symbol.checkmark'))
                .fontSize(16)
                .fontColor([this.pal().okInk])
              Text('No red flags found')
                .llText(14, 700, this.pal().okInk)
            }
            .padding({ left: 12, right: 12, top: 8, bottom: 8 })
            .borderRadius(TilesTheme.LL_RADIUS_PILL)
            .backgroundColor(this.pal().okSoft)
          }
          ForEach(this.verdict.flags, (f: RedFlag) => {
            Text(this.flagLabel(f))
              .llText(14, 700, this.pal().ink)
              .padding({ left: 12, right: 12, top: 8, bottom: 8 })
              .margin({ left: 4, right: 4, bottom: 8 })
              .borderRadius(TilesTheme.LL_RADIUS_PILL)
              .backgroundColor(this.pal().surface)
              .shadow(TilesTheme.LL_SHADOW_TILE)
          }, (f: RedFlag) => this.runId + ':v:' + f.id)
        }
        .width('100%')
        .margin({ top: 6 })

      }
      .width('100%')
      .padding({ top: 12, bottom: 20 })
      .alignItems(HorizontalAlign.Center)
      .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 24 }))
        .animation({ duration: TilesTheme.dur(TilesTheme.LL_DUR, this.reduceMotion), curve: LL_EASE }))
      .accessibilityGroup(true)
      .accessibilityText(this.verdict.headline + ' ' + this.verdict.instruction)

      Blank()
      if (this.verdict.level === 'safe') {
        Button({ type: ButtonType.Normal }) {
          Row({ space: 12 }) {
            SymbolGlyph($r('sys.symbol.checkmark'))
              .fontSize(30)
              .fontColor([this.pal().onSuccess])
            Text('All good')
              .llText(26, 800, this.pal().onSuccess)
          }
        }
        .width('100%')
        .height(84)
        .borderRadius(TilesTheme.LL_RADIUS_L)
        .backgroundColor(this.pal().ok)
        .shadow(TilesTheme.LL_SHADOW_SHEET)
        .onClick(() => {
          this.nav.pop();
        })
      } else {
        Button({ type: ButtonType.Normal }) {
          Row({ space: 12 }) {
            SymbolGlyph($r('sys.symbol.phone_down_fill'))
              .fontSize(34)
              .fontColor([this.pal().onDanger])
            Text(this.isCall() ? 'Hang up' : 'Ignore message')
              .llText(28, 800, this.pal().onDanger)
          }
        }
        .width('100%')
        .height(84)
        .borderRadius(TilesTheme.LL_RADIUS_L)
        .backgroundColor(this.pal().danger)
        .shadow(TilesTheme.LL_SHADOW_SHEET)
        .accessibilityText(this.isCall() ? 'Hang up' : 'Ignore message')
        .onClick(() => {
          this.hangUp();
        })
      }

      Text(this.verdict.level === 'safe' ? 'Call ' + this.caregiver() : 'Call ' + this.caregiver() + ' instead')
        .llText(18, 700, this.pal().ink)
        .decoration({ type: TextDecorationType.Underline, color: this.pal().ink })
        .height(56)
        .margin({ top: 10 })
        .padding({ left: 16, right: 16 })
        .accessibilityText('Call ' + this.caregiver())
        .onClick(() => {
          this.callCaregiver();
        })
    }
    .width('100%')
    .constraintSize({ minHeight: this.viewH })
    .padding({ left: 20, right: 20, top: 8, bottom: 28 })
    .alignItems(HorizontalAlign.Center)
  }

  @Builder
  EndedHero() {
    Column() {
      Blank()
      Column({ space: 16 }) {
        Stack() {
          SymbolGlyph($r('sys.symbol.checkmark'))
            .fontSize(60)
            .fontWeight(FontWeight.Bold)
            .fontColor([this.pal().okInk])
        }
        .width(104)
        .height(104)
        .borderRadius(52)
        .backgroundColor(this.pal().okSoft)
        .opacity(this.endedIn ? 1 : 0)
        .scale({ x: this.endedIn ? 1 : 0.6, y: this.endedIn ? 1 : 0.6 })
        .onAppear(() => {
          this.getUIContext().animateTo({ duration: TilesTheme.dur(500, this.reduceMotion), curve: LL_POP }, () => {
            this.endedIn = true;
          });
        })

        Text(this.isCall() ? 'You hung up.' : 'Message ignored.')
          .llText(36, 700, this.pal().ink)
          .letterSpacing(-0.72)
          .textAlign(TextAlign.Center)
        Text((this.sample.lang === 'pl' ? 'Dobrze. ' : 'Well done. ') + this.caregiver() +
          ' will call you in a minute.')
          .llText(22, 500, this.pal().muted)
          .lineHeight(29)
          .textAlign(TextAlign.Center)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Center)

      Blank()
      Text('Call ' + this.caregiver() + ' now')
        .llText(18, 700, this.pal().ink)
        .decoration({ type: TextDecorationType.Underline, color: this.pal().ink })
        .height(56)
        .padding({ left: 16, right: 16 })
        .onClick(() => {
          this.callCaregiver();
        })
    }
    .width('100%')
    .constraintSize({ minHeight: this.viewH })
    .padding({ left: 20, right: 20, top: 8, bottom: 28 })
    .alignItems(HorizontalAlign.Center)
  }

  // ---------------------------------------------------------------- details below the fold

  @Builder
  SectionTitle(text: string) {
    Text(text)
      .llText(20, 700, this.pal().ink)
      .letterSpacing(TilesTheme.letterSpacing(20))
      .margin({ top: 8 })
  }

  @Builder
  Details() {
    Column({ space: 12 }) {
      if (!this.ended) {
        Row({ space: 8 }) {
          Row({ space: 6 }) {
            SymbolGlyph($r('sys.symbol.bell_fill'))
              .fontSize(16)
              .fontColor([this.alertState === 'sent' ? this.pal().okInk : this.pal().muted])
            Text(this.caregiverStatus())
              .llText(13, 700, this.alertState === 'sent' ? this.pal().okInk : this.pal().muted)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
          .padding({ left: 12, right: 12, top: 8, bottom: 8 })
          .borderRadius(TilesTheme.LL_RADIUS_PILL)
          .backgroundColor(this.alertState === 'sent' ? this.pal().okSoft : this.pal().surface2)
          .flexShrink(1)

          Button({ type: ButtonType.Circle }) {
            SymbolGlyph($r('sys.symbol.speaker_wave_2_fill'))
              .fontSize(20)
              .fontColor([this.pal().ink])
          }
          .width(44)
          .height(44)
          .backgroundColor(this.pal().surface2)
          .accessibilityText('Read aloud')
          .onClick(() => {
            this.readAloud();
          })
        }
        .width('100%')
        this.SectionTitle(this.verdict.flags.length > 0 ? 'Why Guardian thinks so' : 'No red flags found')
        ForEach(this.verdict.flags, (f: RedFlag) => {
          Row({ space: 12 }) {
            Stack() {
              SymbolGlyph(flagIcon(f.icon))
                .fontSize(22)
                .fontColor([f.points >= 20 ? this.pal().dangerInk : SUN_ON])
            }
            .width(44)
            .height(44)
            .borderRadius(22)
            .backgroundColor(f.points >= 20 ? this.pal().dangerSoft : SUN_BG1)

            Column({ space: 3 }) {
              Text(this.sample.lang === 'pl' ? f.label + ' · ' + f.labelPl : f.label)
                .llText(17, 700, this.pal().ink)
              if (f.evidence.length > 0) {
                Text('“' + f.evidence + '”')
                  .llText(15, 500, this.pal().ink)
                  .fontStyle(FontStyle.Italic)
              }
              Text(f.why)
                .llText(14, 500, this.pal().muted)
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
          }
          .width('100%')
          .alignItems(VerticalAlign.Top)
          .padding(14)
          .borderRadius(TilesTheme.LL_RADIUS_M)
          .backgroundColor(this.pal().surface)
          .shadow(TilesTheme.LL_SHADOW_TILE)
          .accessibilityGroup(true)
          .accessibilityText(f.label + '. ' + f.why)
        }, (f: RedFlag) => this.runId + ':d:' + f.id)

        this.CaregiverCard()
      }
      this.CustomCheck()
      Text('Demo: calls and messages here are simulated and labelled. Guardian uses on-device rules ' +
        '(no AI model, no network); the caregiver alert is a local notification on this phone.')
        .llText(13, 500, this.pal().muted)
        .lineHeight(18)
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding({ left: 20, right: 20, top: 4, bottom: 48 })
  }

  @Builder
  CaregiverCard() {
    Column({ space: 10 }) {
      Row({ space: 8 }) {
        SymbolGlyph($r('sys.symbol.lock_shield_fill'))
          .fontSize(20)
          .fontColor([this.pal().okInk])
        Text('Shared with ' + this.caregiver() + ' (redacted on this phone)')
          .llText(16, 700, this.pal().ink)
          .layoutWeight(1)
      }
      .width('100%')

      if (this.verdict.level !== 'scam' && this.alertState !== 'sent' && this.verdict.level !== 'safe') {
        Button('Tell ' + this.caregiver())
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(16)
          .fontWeight(700)
          .fontColor(this.pal().onInk)
          .backgroundColor(this.pal().ink)
          .height(52)
          .width('100%')
          .onClick(() => {
            this.alertCaregiver();
          })
      }
      if (this.verdict.level !== 'safe') {
        Text(this.caregiver() + ' gets only the warning: "' + this.verdict.alertBody + '"')
          .llText(13, 500, this.pal().muted)
      }
      Text(this.verdict.sharedPreview)
        .fontFamily('monospace')
        .fontSize(14)
        .lineHeight(20)
        .fontColor(this.pal().ink)
        .width('100%')
        .padding(12)
        .borderRadius(TilesTheme.LL_RADIUS_S)
        .backgroundColor(this.pal().inputBg)
      Row({ space: 6 }) {
        SymbolGlyph($r('sys.symbol.eye_slash'))
          .fontSize(14)
          .fontColor([this.pal().okInk])
        Text(this.verdict.redactedCount > 0 ?
          'Hidden on this phone: ' + this.verdict.redactedKinds.join(', ') + ' (numbers and accounts)' :
          'No phone numbers or accounts to hide')
          .llText(13, 500, this.pal().muted)
          .layoutWeight(1)
      }
      .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(16)
    .borderRadius(TilesTheme.LL_RADIUS_L)
    .backgroundColor(this.pal().surface)
    .shadow(TilesTheme.LL_SHADOW_TILE)
  }

  @Builder
  CustomCheck() {
    Column({ space: 10 }) {
      this.SectionTitle('Check a message yourself')
      TextArea({ text: this.custom, placeholder: 'Paste or type a message…' })
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(17)
        .fontColor(this.pal().ink)
        .placeholderColor(this.pal().muted)
        .backgroundColor(this.pal().inputBg)
        .border({ width: 1.5, color: this.pal().line })
        .borderRadius(TilesTheme.LL_RADIUS_M)
        .constraintSize({ minHeight: 96 })
        .maxLength(1000)
        .width('100%')
        .onChange((v: string) => {
          this.custom = v;
        })
      Button('Check on this phone')
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(16)
        .fontWeight(700)
        .fontColor(this.pal().onInk)
        .backgroundColor(this.pal().ink)
        .height(52)
        .width('100%')
        .enabled(this.custom.trim().length > 0)
        .opacity(this.custom.trim().length > 0 ? 1 : 0.45)
        .onClick(() => {
          this.checkCustom();
        })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
