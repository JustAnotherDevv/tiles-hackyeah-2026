import { Guardian, GuardianSample, GuardianVerdict, RedFlag } from '../ai/Guardian';
import { Profile } from '../model/Tile';
import { profileFor } from '../data/SeedTiles';
import { TileStore } from '../data/TileStore';
import { TileColors, TilesTheme, ThemePalette, TypeScale, withAlpha } from '../theme/TilesTheme';
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

/**
 * Guardian (route 'guardian'): on-device scam shield for seniors. Pick a simulated "Demo call" / "Demo SMS"
 * (EN + PL) or paste a message; Guardian explains its red flags, shows an animated risk meter and a huge calm
 * instruction, offers Hang up / Call <caregiver>, alerts the caregiver through Notification Kit, and previews
 * what WOULD be shared, with phone numbers / accounts replaced on-device by the PII redactor.
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
  @State phase: string = 'scanning'; // scanning | done
  @State meter: number = 0; // animated bar 0..100
  @State shown: number = 0; // counting-up number 0..100
  @State ended: boolean = false; // "Hang up" pressed
  @State alertState: string = ''; // '' | sending | sent | failed
  @State custom: string = '';
  private scanTimer: number = -1;
  private countTimer: number = -1;
  private alive: boolean = true;

  aboutToAppear(): void {
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
    if (this.scanTimer >= 0) {
      clearTimeout(this.scanTimer);
      this.scanTimer = -1;
    }
    if (this.countTimer >= 0) {
      clearInterval(this.countTimer);
      this.countTimer = -1;
    }
  }

  /** Analyse a sample: short "Analysing on this phone…" phase, then reveal the verdict with motion. */
  private run(s: GuardianSample): void {
    this.clearTimers();
    this.sample = s;
    this.ended = false;
    this.alertState = '';
    this.phase = 'scanning';
    this.meter = 0;
    this.shown = 0;
    this.verdict = Guardian.analyze(s.text, s.knownContact, s.lang, this.caregiver(), s.kind);
    TLog.info('guardian analysed ' + s.id + ' risk=' + this.verdict.risk + ' flags=' + this.verdict.flags.length);
    const wait: number = this.reduceMotion ? 0 : 900;
    this.scanTimer = setTimeout(() => {
      this.scanTimer = -1;
      if (!this.alive) {
        return;
      }
      this.reveal();
    }, wait);
  }

  private reveal(): void {
    const target: number = this.verdict.risk;
    this.phase = 'done';
    if (this.reduceMotion) {
      this.meter = target;
      this.shown = target;
    } else {
      this.getUIContext().animateTo({ duration: 1100, curve: Curve.EaseOut }, () => {
        this.meter = target;
      });
      const steps: number = 22;
      let i: number = 0;
      this.countTimer = setInterval(() => {
        i++;
        const t: number = i / steps;
        this.shown = Math.round(target * (1 - Math.pow(1 - t, 3)));
        if (i >= steps) {
          clearInterval(this.countTimer);
          this.countTimer = -1;
          this.shown = target;
        }
      }, 50);
    }
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
    this.ended = true;
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

  private verdictColors(): TileColors {
    const key: string = this.verdict.level === 'scam' ? 'coral' : (this.verdict.level === 'caution' ? 'sun' : 'mint');
    // Verdict cards always use the high-contrast variant: this is the screen that must be read in a panic.
    return TilesTheme.tile(key, true, this.dark);
  }

  build() {
    NavDestination() {
      Stack({ alignContent: Alignment.Top }) {
        Scroll() {
          Column({ space: TilesTheme.SPACE_L }) {
            this.Header()
            this.PrivacyBanner()
            this.SampleChips()
            this.IncomingCard()
            if (this.phase === 'scanning') {
              this.Scanning()
            } else if (this.ended) {
              this.EndedCard()
            } else {
              this.VerdictCard()
              this.ActionButtons()
              this.RiskMeter()
              this.Flags()
              this.CaregiverCard()
            }
            this.CustomCheck()
            this.Footnote()
          }
          .padding({
            left: TilesTheme.GUTTER,
            right: TilesTheme.GUTTER,
            top: TilesTheme.SPACE_M,
            bottom: TilesTheme.SPACE_XXL * 2
          })
          .alignItems(HorizontalAlign.Start)
          .width('100%')
        }
        .scrollBar(BarState.Off)
        .edgeEffect(EdgeEffect.Spring)
        .width('100%')
        .height('100%')
      }
      .width('100%')
      .height('100%')
      .backgroundColor(this.pal().bg)
    }
    .hideTitleBar(true)
    .backgroundColor(this.pal().bg)
  }

  private pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }

  private ts(): TypeScale {
    // Full-screen view is already large; cap so the verdict stays on one screen at 180% text.
    return TilesTheme.type(Math.min(this.profile.textScale, 1.4));
  }

  private tap(): number {
    return TilesTheme.tapTarget(this.profile);
  }

  @Builder
  Header() {
    Row({ space: TilesTheme.SPACE_M }) {
      Button({ type: ButtonType.Circle }) {
        SymbolGlyph($r('sys.symbol.chevron_left'))
          .fontSize(28)
          .fontColor([this.pal().text])
      }
      .width(this.tap())
      .height(this.tap())
      .backgroundColor(this.pal().surface)
      .border({ width: this.profile.highContrast ? 2 : 0, color: this.pal().border })
      .accessibilityText('Back')
      .onClick(() => {
        this.nav.pop();
      })

      Column({ space: 2 }) {
        Text('Guardian')
          .fontSize(this.ts().headline)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().text)
        Text('Scam shield for calls and messages')
          .fontSize(this.ts().caption)
          .fontColor(this.pal().textMuted)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      SymbolGlyph($r('sys.symbol.checkmark_shield_fill'))
        .fontSize(36)
        .fontColor([this.pal().success])
        .accessibilityText('Guardian is on')
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }

  @Builder
  PrivacyBanner() {
    Row({ space: TilesTheme.SPACE_S }) {
      SymbolGlyph($r('sys.symbol.lock_shield_fill'))
        .fontSize(this.ts().title)
        .fontColor([this.pal().success])
      Text('Analysed on this phone — nothing leaves')
        .fontSize(this.ts().label)
        .fontWeight(FontWeight.Medium)
        .fontColor(this.pal().text)
        .layoutWeight(1)
    }
    .width('100%')
    .padding({ left: TilesTheme.SPACE_M, right: TilesTheme.SPACE_M, top: 10, bottom: 10 })
    .borderRadius(TilesTheme.RADIUS_INNER)
    .backgroundColor(withAlpha(this.pal().success, 0.12))
    .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().success })
  }

  @Builder
  SampleChips() {
    Column({ space: TilesTheme.SPACE_S }) {
      Text('Try a demo (simulated input)')
        .fontSize(this.ts().caption)
        .fontWeight(FontWeight.Medium)
        .fontColor(this.pal().textMuted)
      Scroll() {
        Row() {
          ForEach(this.samples, (s: GuardianSample) => {
            Text(s.chip)
              .fontSize(this.ts().label)
              .fontWeight(FontWeight.Medium)
              .fontColor(s.id === this.sample.id ? this.pal().onAccent : this.pal().text)
              .padding({ left: 14, right: 14 })
              .height(Math.max(44, this.tap() - 12))
              .borderRadius(TilesTheme.RADIUS_CHIP)
              .backgroundColor(s.id === this.sample.id ? this.pal().accent : this.pal().surface)
              .border({ width: 1, color: s.id === this.sample.id ? this.pal().accent : this.pal().border })
              .margin({ right: TilesTheme.SPACE_S })
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
      .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  @Builder
  IncomingCard() {
    Column({ space: TilesTheme.SPACE_S }) {
      Row({ space: TilesTheme.SPACE_S }) {
        if (this.sample.kind === 'call') {
          SymbolGlyph($r('sys.symbol.phone_fill'))
            .fontSize(this.ts().body)
            .fontColor([this.pal().textMuted])
        } else {
          SymbolGlyph($r('sys.symbol.message_fill'))
            .fontSize(this.ts().body)
            .fontColor([this.pal().textMuted])
        }
        Text(this.sample.from + (this.sample.kind === 'call' ? ' · 2:14' : ''))
          .fontSize(this.ts().label)
          .fontColor(this.pal().textMuted)
          .layoutWeight(1)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(this.sample.id.startsWith(CUSTOM_ID) ? 'Your text' :
          (this.sample.kind === 'call' ? 'Demo call' : 'Demo SMS'))
          .fontSize(this.ts().caption)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().onAccent)
          .backgroundColor(this.pal().accent)
          .borderRadius(TilesTheme.RADIUS_CHIP)
          .padding({ left: 10, right: 10, top: 3, bottom: 3 })
      }
      .width('100%')

      Text('“' + this.sample.text + '”')
        .fontSize(this.ts().body)
        .lineHeight(Math.round(this.ts().body * 1.4))
        .fontColor(this.pal().text)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(TilesTheme.TILE_PAD)
    .borderRadius(TilesTheme.RADIUS_TILE)
    .backgroundColor(this.pal().surface)
    .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().border })
  }

  @Builder
  Scanning() {
    Row({ space: TilesTheme.SPACE_M }) {
      LoadingProgress()
        .width(40)
        .height(40)
        .color(this.pal().accent)
      Column({ space: 2 }) {
        Text('Checking on this phone…')
          .fontSize(this.ts().title)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.pal().text)
        Text('Looking for money requests, pressure, secrecy, codes and links')
          .fontSize(this.ts().caption)
          .fontColor(this.pal().textMuted)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .padding(TilesTheme.TILE_PAD)
    .borderRadius(TilesTheme.RADIUS_TILE)
    .backgroundColor(this.pal().surfaceAlt)
  }

  @Builder
  VerdictCard() {
    Column({ space: TilesTheme.SPACE_S }) {
      Row({ space: TilesTheme.SPACE_S }) {
        if (this.verdict.level === 'safe') {
          SymbolGlyph($r('sys.symbol.checkmark_shield_fill'))
            .fontSize(44)
            .fontColor([this.verdictColors().on])
        } else {
          SymbolGlyph($r('sys.symbol.exclamationmark_shield_fill'))
            .fontSize(44)
            .fontColor([this.verdictColors().on])
        }
        Blank()
        Button({ type: ButtonType.Circle }) {
          SymbolGlyph($r('sys.symbol.speaker_wave_2'))
            .fontSize(26)
            .fontColor([this.verdictColors().on])
        }
        .width(this.tap())
        .height(this.tap())
        .backgroundColor(this.verdictColors().soft)
        .accessibilityText('Read aloud')
        .onClick(() => {
          this.readAloud();
        })
      }
      .width('100%')

      Text(this.verdict.headline)
        .fontSize(this.ts().display)
        .fontWeight(FontWeight.Bold)
        .lineHeight(Math.round(this.ts().display * 1.12))
        .fontColor(this.verdictColors().on)
      Text(this.verdict.instruction)
        .fontSize(this.ts().title)
        .fontWeight(FontWeight.Medium)
        .lineHeight(Math.round(this.ts().title * 1.3))
        .fontColor(this.verdictColors().on)
      if (this.sample.lang === 'pl') {
        Text(this.verdict.headlineEn + ' ' + this.verdict.instructionEn)
          .fontSize(this.ts().caption)
          .fontColor(this.verdictColors().onMuted)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(TilesTheme.SPACE_XL)
    .borderRadius(TilesTheme.RADIUS_TILE_LG)
    .backgroundColor(this.verdictColors().bg)
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.scale({ x: 0.94, y: 0.94 }))
      .animation({ duration: TilesTheme.dur(TilesTheme.DUR_SLOW, this.reduceMotion), curve: Curve.Friction }))
    .accessibilityGroup(true)
    .accessibilityText(this.verdict.headline + ' ' + this.verdict.instruction)
  }

  @Builder
  ActionButtons() {
    Column({ space: TilesTheme.SPACE_M }) {
      if (this.verdict.level !== 'safe') {
        Button({ type: ButtonType.Normal }) {
          Row({ space: TilesTheme.SPACE_M }) {
            SymbolGlyph($r('sys.symbol.phone_down_fill'))
              .fontSize(this.ts().title)
              .fontColor(['#FFFFFF'])
            Text(this.sample.kind === 'call' ? 'Hang up' : 'Ignore message')
              .fontSize(this.ts().title)
              .fontWeight(FontWeight.Bold)
              .fontColor('#FFFFFF')
          }
        }
        .width('100%')
        .height(this.tap() + 12)
        .borderRadius(TilesTheme.RADIUS_BUTTON + 4)
        .backgroundColor(this.dark ? '#D93025' : '#A50E0E')
        .accessibilityText(this.sample.kind === 'call' ? 'Hang up' : 'Ignore message')
        .onClick(() => {
          this.hangUp();
        })
      }
      Button({ type: ButtonType.Normal }) {
        Row({ space: TilesTheme.SPACE_M }) {
          SymbolGlyph($r('sys.symbol.phone_fill'))
            .fontSize(this.ts().title)
            .fontColor(['#FFFFFF'])
          Text('Call ' + this.caregiver())
            .fontSize(this.ts().title)
            .fontWeight(FontWeight.Bold)
            .fontColor('#FFFFFF')
        }
      }
      .width('100%')
      .height(this.tap() + 12)
      .borderRadius(TilesTheme.RADIUS_BUTTON + 4)
      .backgroundColor('#00664F')
      .accessibilityText('Call ' + this.caregiver())
      .onClick(() => {
        this.callCaregiver();
      })
    }
    .width('100%')
  }

  @Builder
  RiskMeter() {
    Column({ space: TilesTheme.SPACE_S }) {
      Row() {
        Text('Scam risk')
          .fontSize(this.ts().label)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.pal().textMuted)
          .layoutWeight(1)
        Text(this.shown.toString() + '%')
          .fontSize(this.ts().display)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.meterColor())
      }
      .width('100%')
      .alignItems(VerticalAlign.Bottom)

      Stack({ alignContent: Alignment.Start }) {
        Row()
          .width('100%')
          .height(18)
          .borderRadius(9)
          .backgroundColor(this.pal().surfaceAlt)
        Row()
          .width(Math.max(4, this.meter).toString() + '%')
          .height(18)
          .borderRadius(9)
          .linearGradient({
            angle: 90,
            colors: [['#2ED3A0', 0.0], ['#FFC83D', 0.5], ['#E5483A', 1.0]]
          })
      }
      .width('100%')

      Row() {
        Text('Safe')
          .fontSize(this.ts().caption)
          .fontColor(this.pal().textMuted)
          .layoutWeight(1)
        Text('Scam')
          .fontSize(this.ts().caption)
          .fontColor(this.pal().textMuted)
      }
      .width('100%')
    }
    .width('100%')
    .padding(TilesTheme.TILE_PAD)
    .borderRadius(TilesTheme.RADIUS_TILE)
    .backgroundColor(this.pal().surface)
    .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().border })
    .accessibilityGroup(true)
    .accessibilityText('Scam risk ' + this.verdict.risk.toString() + ' percent')
  }

  private meterColor(): string {
    if (this.verdict.level === 'scam') {
      return this.pal().danger;
    }
    return this.verdict.level === 'caution' ? (this.dark ? '#FFC83D' : '#8A5A00') : this.pal().success;
  }

  @Builder
  Flags() {
    Column({ space: TilesTheme.SPACE_S }) {
      Text(this.verdict.flags.length > 0 ? 'Why Guardian thinks so' : 'No red flags found')
        .fontSize(this.ts().title)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().text)
      ForEach(this.verdict.flags, (f: RedFlag, i: number) => {
        Row({ space: TilesTheme.SPACE_M }) {
          Stack() {
            SymbolGlyph(flagIcon(f.icon))
              .fontSize(24)
              .fontColor([f.points >= 20 ? this.pal().onDanger : '#3D2C00'])
          }
          .width(48)
          .height(48)
          .borderRadius(24)
          .backgroundColor(f.points >= 20 ? this.pal().danger : '#FFC83D')

          Column({ space: 2 }) {
            Text(this.sample.lang === 'pl' ? f.label + ' · ' + f.labelPl : f.label)
              .fontSize(this.ts().body)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.pal().text)
            if (f.evidence.length > 0) {
              Text('“' + f.evidence + '”')
                .fontSize(this.ts().label)
                .fontStyle(FontStyle.Italic)
                .fontColor(this.pal().text)
            }
            Text(f.why)
              .fontSize(this.ts().caption)
              .fontColor(this.pal().textMuted)
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
        .padding(TilesTheme.SPACE_M)
        .borderRadius(TilesTheme.RADIUS_INNER)
        .backgroundColor(this.pal().surface)
        .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().border })
        .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 24 }))
          .animation({
            duration: TilesTheme.dur(TilesTheme.DUR_MED, this.reduceMotion),
            delay: this.reduceMotion ? 0 : 200 + i * TilesTheme.STAGGER * 2,
            curve: Curve.EaseOut
          }))
        .accessibilityGroup(true)
        .accessibilityText(f.label + '. ' + f.why)
      }, (f: RedFlag) => this.sample.id + ':' + f.id)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  @Builder
  CaregiverCard() {
    Column({ space: TilesTheme.SPACE_S }) {
      Row({ space: TilesTheme.SPACE_S }) {
        SymbolGlyph($r('sys.symbol.bell_fill'))
          .fontSize(this.ts().title)
          .fontColor([this.pal().accent])
        Text(this.caregiverStatus())
          .fontSize(this.ts().body)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().text)
          .layoutWeight(1)
      }
      .width('100%')

      if (this.verdict.level !== 'scam' && this.alertState !== 'sent' && this.verdict.level !== 'safe') {
        Button('Tell ' + this.caregiver())
          .fontSize(this.ts().label)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().onAccent)
          .backgroundColor(this.pal().accent)
          .height(this.tap())
          .width('100%')
          .onClick(() => {
            this.alertCaregiver();
          })
      }

      if (this.verdict.level !== 'safe') {
        Text(this.caregiver() + ' gets only the warning: "' + this.verdict.alertBody + '"')
          .fontSize(this.ts().caption)
          .fontColor(this.pal().textMuted)
      }

      Text('If you share the message, ' + this.caregiver() + ' would see:')
        .fontSize(this.ts().label)
        .fontWeight(FontWeight.Medium)
        .fontColor(this.pal().text)
        .margin({ top: TilesTheme.SPACE_XS })
      Text(this.verdict.sharedPreview)
        .fontSize(this.ts().label)
        .lineHeight(Math.round(this.ts().label * 1.4))
        .fontFamily('monospace')
        .fontColor(this.pal().text)
        .width('100%')
        .padding(TilesTheme.SPACE_M)
        .borderRadius(TilesTheme.RADIUS_INNER)
        .backgroundColor(this.pal().surfaceAlt)
      Row({ space: TilesTheme.SPACE_S }) {
        SymbolGlyph($r('sys.symbol.eye_slash'))
          .fontSize(this.ts().label)
          .fontColor([this.pal().success])
        Text(this.verdict.redactedCount > 0 ?
          'Hidden on this phone: ' + this.verdict.redactedKinds.join(', ') + ' (numbers and accounts)' :
          'No phone numbers or accounts to hide')
          .fontSize(this.ts().caption)
          .fontColor(this.pal().textMuted)
          .layoutWeight(1)
      }
      .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(TilesTheme.TILE_PAD)
    .borderRadius(TilesTheme.RADIUS_TILE)
    .backgroundColor(this.pal().surface)
    .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().border })
  }

  private caregiverStatus(): string {
    const who: string = this.caregiver();
    if (this.alertState === 'sent') {
      return who + ' already knows (alert sent · demo)';
    }
    if (this.alertState === 'sending') {
      return 'Telling ' + who + '…';
    }
    if (this.alertState === 'failed') {
      return 'Could not alert ' + who + ' (notifications off)';
    }
    return this.verdict.level === 'safe' ? 'Nothing to tell ' + who : who + ' has not been told yet';
  }

  @Builder
  EndedCard() {
    Column({ space: TilesTheme.SPACE_M }) {
      SymbolGlyph($r('sys.symbol.checkmark_shield_fill'))
        .fontSize(56)
        .fontColor([TilesTheme.tile('mint', true, this.dark).on])
      Text(this.sample.kind === 'call' ? 'Call ended. You are safe.' : 'Message ignored. You are safe.')
        .fontSize(this.ts().headline)
        .fontWeight(FontWeight.Bold)
        .fontColor(TilesTheme.tile('mint', true, this.dark).on)
      Text('You did the right thing. ' + this.caregiver() + ' will call you soon.')
        .fontSize(this.ts().title)
        .fontColor(TilesTheme.tile('mint', true, this.dark).on)
      Button('Call ' + this.caregiver() + ' now')
        .fontSize(this.ts().title)
        .fontWeight(FontWeight.Bold)
        .fontColor('#00664F')
        .backgroundColor('#FFFFFF')
        .height(this.tap() + 8)
        .width('100%')
        .onClick(() => {
          this.callCaregiver();
        })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(TilesTheme.SPACE_XL)
    .borderRadius(TilesTheme.RADIUS_TILE_LG)
    .backgroundColor(TilesTheme.tile('mint', true, this.dark).bg)
    .transition(TransitionEffect.OPACITY.animation({
      duration: TilesTheme.dur(TilesTheme.DUR_SLOW, this.reduceMotion)
    }))
  }

  @Builder
  CustomCheck() {
    Column({ space: TilesTheme.SPACE_S }) {
      Text('Check a message yourself')
        .fontSize(this.ts().title)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().text)
      TextArea({ text: this.custom, placeholder: 'Paste or type a message…' })
        .fontSize(this.ts().body)
        .fontColor(this.pal().text)
        .placeholderColor(this.pal().textMuted)
        .backgroundColor(this.pal().surface)
        .border({ width: 1, color: this.pal().border })
        .borderRadius(TilesTheme.RADIUS_INNER)
        .constraintSize({ minHeight: 96 })
        .maxLength(1000)
        .width('100%')
        .onChange((v: string) => {
          this.custom = v;
        })
      Button('Check on this phone')
        .fontSize(this.ts().label)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().onAccent)
        .backgroundColor(this.pal().accent)
        .height(this.tap())
        .width('100%')
        .enabled(this.custom.trim().length > 0)
        .opacity(this.custom.trim().length > 0 ? 1 : 0.5)
        .onClick(() => {
          this.checkCustom();
        })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  @Builder
  Footnote() {
    Text('Demo: calls and messages here are simulated and labelled. Guardian uses on-device rules ' +
      '(no AI model, no network); the caregiver alert is a local notification on this phone.')
      .fontSize(this.ts().caption)
      .fontColor(this.pal().textMuted)
  }
}
