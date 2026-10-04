import { Profile, Suggestion, TileAction, TileBlock, TileSpec } from '../model/Tile';
import { TileStore } from '../data/TileStore';
import { Adaptation, PreviewState } from '../ai/Adaptation';
import { LL_FONT_FAMILY, TileColors, TilesTheme, ThemePalette } from '../theme/TilesTheme';
import { TileView } from '../components/TileView';
import { MiniHome } from './OnboardingView';
import { Haptics } from '../../platform/Haptics';
import { LengthMetrics, window } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';

/** One row of the caregiver's "Today" activity list (tone: ok | danger | neutral). */
class ActivityRow {
  key: string = '';
  icon: Resource = $r('sys.symbol.checkmark');
  text: string = '';
  time: string = '';
  tone: string = 'ok';
}

/** Living Light text defaults (Manrope, prototype letter-spacing -0.012em). */
@Extend(Text)
function llText(size: number, weight: FontWeight, color: ResourceColor) {
  .fontFamily(LL_FONT_FAMILY)
  .fontSize(size)
  .fontWeight(weight)
  .fontColor(color)
  .letterSpacing(TilesTheme.letterSpacing(size))
}

/** Small uppercase kicker / section label (12 px, 700, tracking .1em). */
@Extend(Text)
function llKicker(color: ResourceColor) {
  .fontFamily(LL_FONT_FAMILY)
  .fontSize(12)
  .fontWeight(FontWeight.Bold)
  .letterSpacing(1.4)
  .fontColor(color)
}

/**
 * Caregiver view (route 'caregiver'): a SIMULATION of the caregiver's own phone ("Kasia's phone"), shown on the
 * same device for the demo. Living Light (design direction C): wallpaper gradient, frosted-glass cards,
 * "Needs you" approvals (assistant tiles + adaptation suggestions with before/after previews; Approve / Decline go
 * through TileStore / Adaptation.decide) and a "Today" activity list derived from the person's tiles.
 * Uses the caregiver's own (standard) text size, not the profile's.
 */
@Component
export struct CaregiverView {
  @Consume('tilesNav') nav: NavPathStack;
  @StorageProp('tiles.dark') dark: boolean = false;
  @StorageProp('tiles.profile') profile: Profile = new Profile();
  @StorageProp('tiles.list') tiles: TileSpec[] = [];
  @StorageProp('tiles.pending') pending: TileSpec[] = [];
  @StorageProp('tiles.pendingReply') pendingReply: string = '';
  @StorageProp('tiles.suggestions') suggs: Suggestion[] = [];
  @StorageProp('tiles.hideApps') appsHidden: boolean = false;
  @State simResult: string = '';
  @State simulating: boolean = false;
  /** Status-bar height (vp) and where our root starts: the window is full-screen (immersive). */
  @State sysTop: number = 0;
  @State rootY: number = 0;
  /** Measured width of one before/after column, so the mini homes use all of it (less title squeezing). */
  @State miniW: number = 132;

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
  }

  /** Extra top padding only when the page really lays out under the status bar. */
  private topPad(): number {
    return Math.min(this.sysTop, Math.max(0, this.sysTop - this.rootY));
  }

  private pal(): ThemePalette {
    return TilesTheme.palette(this.dark, false);
  }

  private caregiver(): string {
    return this.profile.caregiver.length > 0 ? this.profile.caregiver : '';
  }

  private person(): string {
    return this.profile.name.length > 0 ? this.profile.name : 'this phone';
  }

  /** What the caregiver calls the person ("Mama" for a daughter / son), else the name. */
  private callName(): string {
    const r: string = this.profile.caregiverRole;
    return r === 'daughter' || r === 'son' ? 'Mama' : this.person();
  }

  private headerTitle(): string {
    const n: string = this.callName();
    return n === this.person() ? n : n + ' · ' + this.person();
  }

  private avatarColors(): TileColors {
    return TilesTheme.tile(this.profile.id === 'kid' ? 'leaf' : 'sun', false, this.dark);
  }

  private pendingSuggs(): Suggestion[] {
    return this.suggs.filter((s: Suggestion) => s.status === 'pending');
  }

  private needsCount(): number {
    return this.pending.length + this.pendingSuggs().length;
  }

  private declineBorder(): string {
    return this.dark ? this.pal().line : '#33000000';
  }

  private slotOf(t: TileSpec): string {
    const m: RegExpMatchArray | null = t.title.match(new RegExp('\\d{1,2}:\\d{2}'));
    return m !== null ? m[0] : '';
  }

  /** ' · 2 calls blocked' from the guardian tile's subtitle or text ("On · 2 calls blocked"), else ''. */
  private guardianDetail(t: TileSpec): string {
    const texts: string[] = [t.subtitle];
    for (const b of t.blocks) {
      texts.push(b.text);
    }
    for (const x of texts) {
      if (x.toLowerCase().indexOf('blocked') >= 0) {
        const i: number = x.indexOf('·');
        return ' · ' + (i >= 0 ? x.substring(i + 1).trim() : x.trim()).toLowerCase();
      }
    }
    return '';
  }

  private hasDangerAlert(t: TileSpec): boolean {
    return t.blocks.some((b: TileBlock) => b.kind === 'alert' && b.value === 'danger');
  }

  /** Activity rows derived from the person's tiles and decided suggestions (no extra state). */
  private activity(): ActivityRow[] {
    const out: ActivityRow[] = [];
    for (const t of this.tiles) {
      if (t.type === 'pills') {
        const taken: boolean = t.subtitle.startsWith('Taken at ');
        const slot: string = this.slotOf(t);
        const r: ActivityRow = new ActivityRow();
        r.key = 'a-' + t.id + (taken ? '-t' : '-d');
        r.icon = taken ? $r('sys.symbol.checkmark') : $r('sys.symbol.cross_case_fill');
        r.text = taken ? 'Took the ' + (slot.length > 0 ? slot + ' ' : '') + 'pills' :
          t.title + ' — not yet';
        r.time = taken ? t.subtitle.substring(9) : 'due';
        r.tone = taken ? 'ok' : 'danger';
        // Two medication tiles can describe the same dose: never list an identical row twice.
        if (out.every((o: ActivityRow) => o.text !== r.text)) {
          out.push(r);
        }
      } else if (t.type === 'guardian') {
        const r: ActivityRow = new ActivityRow();
        if (this.hasDangerAlert(t)) {
          r.key = 'a-' + t.id + '-alert';
          r.icon = $r('sys.symbol.exclamationmark_shield_fill');
          r.text = 'Guardian alert · likely scam call. ' + this.callName() + ' was told to hang up';
          r.time = 'today';
          r.tone = 'danger';
        } else {
          r.key = 'a-' + t.id + '-on';
          r.icon = $r('sys.symbol.checkmark_shield_fill');
          r.text = 'Guardian on' + this.guardianDetail(t);
          r.time = 'this week';
          r.tone = 'ok';
        }
        out.push(r);
      } else if (t.subtitle.startsWith('Done at ')) {
        const r: ActivityRow = new ActivityRow();
        r.key = 'a-' + t.id + '-done';
        r.icon = $r('sys.symbol.checkmark');
        r.text = 'Finished: ' + t.title;
        r.time = t.subtitle.substring(8);
        r.tone = 'ok';
        out.push(r);
      }
    }
    const decided: Suggestion[] = this.suggs.filter((s: Suggestion) => s.status !== 'pending').reverse().slice(0, 4);
    for (const s of decided) {
      const ok: boolean = s.status === 'approved';
      const r: ActivityRow = new ActivityRow();
      r.key = 'a-s-' + s.id + s.status;
      r.icon = ok ? $r('sys.symbol.wand_and_stars_fill') : $r('sys.symbol.xmark');
      r.text = (ok ? 'Approved: ' : 'Declined: ') + s.title;
      r.time = 'today';
      r.tone = ok ? 'ok' : 'neutral';
      out.push(r);
    }
    if (this.profile.readAloud) {
      const r: ActivityRow = new ActivityRow();
      r.key = 'a-readaloud';
      r.icon = $r('sys.symbol.speaker_wave_2_fill');
      r.text = 'Tiles read aloud on tap';
      r.time = 'on';
      r.tone = 'ok';
      out.push(r);
    }
    return out;
  }

  private toneBg(tone: string): string {
    return tone === 'ok' ? this.pal().okSoft : tone === 'danger' ? this.pal().dangerSoft : this.pal().surface2;
  }

  private toneFg(tone: string): string {
    return tone === 'ok' ? this.pal().okInk : tone === 'danger' ? this.pal().dangerInk : this.pal().muted;
  }

  private toast(msg: string): void {
    try {
      this.getUIContext().getPromptAction().showToast({ message: msg, duration: 2200 });
    } catch (e) {
      // toast is cosmetic
    }
  }

  private decideTile(id: string, approve: boolean): void {
    this.getUIContext().animateTo({ duration: TilesTheme.LL_DUR, curve: TilesTheme.ease() }, () => {
      if (approve) {
        TileStore.get().approvePending(id);
      } else {
        TileStore.get().declinePending(id);
      }
    });
    if (approve) {
      Haptics.success();
      this.toast('Approved: the tile is now on ' + this.person() + '\'s home');
    } else {
      this.toast('Declined');
    }
  }

  private decideSugg(s: Suggestion, approve: boolean): void {
    this.getUIContext().animateTo({ duration: TilesTheme.LL_DUR, curve: TilesTheme.ease() }, () => {
      Adaptation.decide(s.id, approve);
    });
    if (approve) {
      Haptics.success();
      this.toast('Applied: ' + s.title);
    } else {
      this.toast('Declined: ' + s.title);
    }
  }

  private simulate(): void {
    this.simulating = true;
    setTimeout(() => {
      this.getUIContext().animateTo({ duration: TilesTheme.LL_DUR, curve: TilesTheme.ease() }, () => {
        this.simResult = Adaptation.simulateDay();
        this.simulating = false;
      });
    }, 600);
  }

  private enter(): TransitionEffect {
    return TransitionEffect.OPACITY
      .combine(TransitionEffect.scale({ x: TilesTheme.LL_ENTER_SCALE, y: TilesTheme.LL_ENTER_SCALE }))
      .combine(TransitionEffect.translate({ y: TilesTheme.LL_ENTER_TY }));
  }

  build() {
    NavDestination() {
      // Column (not a floating Stack): the call button docks below the scroll so cards never slide under it.
      Column() {
        Scroll() {
          Column({ space: 14 }) {
            this.topBar()
            this.deviceHeader()

            // ----- Needs you -----
            Column({ space: 8 }) {
              this.sectionLabel('Needs you', this.needsCount())
              if (this.needsCount() === 0) {
                Text('Nothing right now')
                  .llText(15, FontWeight.Medium, this.pal().muted)
                  .textAlign(TextAlign.Center)
                  .width('100%')
                  .padding(18)
                  .borderRadius(TilesTheme.LL_RADIUS_L)
                  .border({ width: 1.5, color: this.pal().line, style: BorderStyle.Dashed })
              }
              if (this.pending.length > 0 && this.pendingReply.length > 0) {
                Text('Tiles assistant: “' + this.pendingReply + '”')
                  .llText(14, FontWeight.Medium, this.pal().muted)
                  .lineHeight(20)
                  .width('100%')
              }
              ForEach(this.pending, (t: TileSpec) => {
                this.proposalCard(t)
              }, (t: TileSpec) => 'p-' + t.id)
              if (this.pending.length > 1) {
                this.inkPill('Approve all ' + this.pending.length.toString(), () => {
                  this.getUIContext().animateTo({ duration: TilesTheme.LL_DUR, curve: TilesTheme.ease() }, () => {
                    TileStore.get().approveAllPending();
                  });
                  Haptics.success();
                  this.toast('All new tiles approved');
                })
              }
              ForEach(this.pendingSuggs(), (s: Suggestion) => {
                this.suggestionCard(s)
              }, (s: Suggestion) => 's-' + s.id + '-' + this.tiles.length.toString() + '-' +
                this.profile.textScale.toString())
            }
            .width('100%')

            // ----- Today -----
            Column({ space: 8 }) {
              this.sectionLabel('Today', -1)
              if (this.activity().length === 0) {
                Text('No activity yet today')
                  .llText(15, FontWeight.Medium, this.pal().muted)
                  .textAlign(TextAlign.Center)
                  .width('100%')
                  .padding(18)
                  .borderRadius(TilesTheme.LL_RADIUS_L)
                  .border({ width: 1.5, color: this.pal().line, style: BorderStyle.Dashed })
              } else {
                Column() {
                  ForEach(this.activity(), (r: ActivityRow, i: number) => {
                    this.activityRow(r, i === this.activity().length - 1)
                  }, (r: ActivityRow) => r.key)
                }
                .width('100%')
                .padding({ left: 16, right: 16, top: 4, bottom: 4 })
                .borderRadius(TilesTheme.LL_RADIUS_L)
                .backgroundColor(this.pal().surface)
                .backdropBlur(TilesTheme.LL_BLUR)
                .shadow(TilesTheme.LL_SHADOW_TILE)
              }
            }
            .width('100%')

            this.simulateCard()

            Text('Simulation: on a real deployment this screen runs on ' +
              (this.caregiver().length > 0 ? this.caregiver() + '\'s' : 'the caregiver\'s') +
              ' own phone. Suggestions come from on-device rules over usage signals; nothing is sent anywhere.')
              .llText(13, FontWeight.Regular, this.pal().muted)
              .lineHeight(18)
              .width('100%')
          }
          .padding({ left: 16, right: 16, top: 14 + this.topPad(), bottom: 20 })
        }
        .scrollBar(BarState.Off)
        .align(Alignment.Top)
        .width('100%')
        .layoutWeight(1)
        .fadingEdge(true, { fadingEdgeLength: LengthMetrics.vp(40) })

        this.callButton()
      }
      .width('100%')
      .height('100%')
      .onAreaChange((o: Area, n: Area) => {
        const y: number = Number(n.globalPosition.y);
        if (!isNaN(y) && Math.abs(y - this.rootY) > 0.5) {
          this.rootY = y;
        }
      })
      // Prototype caregiver phone uses the page bg gradient (t.bg), not the launcher wallpaper.
      .linearGradient({ angle: this.pal().bgGradient.angle, colors: this.pal().bgGradient.colors })
      .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.BOTTOM])
    }
    .hideTitleBar(true)
    .backgroundColor(this.pal().bg)
  }

  @Builder
  topBar() {
    Row({ space: 10 }) {
      Row() {
        SymbolGlyph($r('sys.symbol.chevron_left'))
          .fontSize(24)
          .fontColor([this.pal().ink])
      }
      .width(48)
      .height(48)
      .justifyContent(FlexAlign.Center)
      .borderRadius(24)
      .backgroundColor(this.pal().surface)
      .backdropBlur(TilesTheme.LL_BLUR)
      .shadow(TilesTheme.LL_SHADOW_SOFT)
      .onClick(() => this.nav.pop())
      .accessibilityText('Back')

      Blank()
      Text('SIMULATED SECOND PHONE')
        .llKicker(this.pal().muted)
        .padding({ left: 10, right: 10, top: 6, bottom: 6 })
        .borderRadius(TilesTheme.LL_RADIUS_PILL)
        .border({ width: 1.5, color: this.pal().line })
    }
    .width('100%')
  }

  @Builder
  deviceHeader() {
    Row({ space: 12 }) {
      Text(this.person().substring(0, 1).toUpperCase())
        .llText(20, FontWeight.Bolder, this.avatarColors().on)
        .textAlign(TextAlign.Center)
        .width(48)
        .height(48)
        .borderRadius(24)
        .linearGradient({ angle: this.avatarColors().gradient.angle, colors: this.avatarColors().gradient.colors })
      Column({ space: 2 }) {
        Text(this.headerTitle())
          .llText(21, TilesTheme.LL_WEIGHT, this.pal().ink)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Row({ space: 6 }) {
          Circle()
            .width(8)
            .height(8)
            .fill(this.pal().ok)
            .margin({ top: 6 })
          Text(this.caregiver().length > 0 ? 'Phone active · just now' :
            'No caregiver set: changes are approved here')
            .llText(14, FontWeight.Medium, this.pal().muted)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      if (this.caregiver().length > 0) {
        Text(this.caregiver().toUpperCase())
          .llKicker(this.pal().muted)
          .padding({ left: 10, right: 10, top: 6, bottom: 6 })
          .borderRadius(TilesTheme.LL_RADIUS_PILL)
          .border({ width: 1.5, color: this.pal().line })
      }
    }
    .width('100%')
    .accessibilityGroup(true)
  }

  @Builder
  sectionLabel(title: string, count: number) {
    Row({ space: 8 }) {
      Text(title.toUpperCase())
        .llKicker(this.pal().muted)
      if (count > 0) {
        Text(count.toString())
          .llText(12, FontWeight.Bold, this.pal().onAccent)
          .padding({ left: 7, right: 7, top: 1, bottom: 1 })
          .borderRadius(TilesTheme.LL_RADIUS_PILL)
          .backgroundColor(this.pal().accent)
      }
    }
    .width('100%')
  }

  @Builder
  kicker(icon: Resource, label: string, time: string, color: ResourceColor) {
    Row({ space: 8 }) {
      SymbolGlyph(icon)
        .fontSize(18)
        .fontColor([color])
      Text(label.toUpperCase())
        .llKicker(color)
        .letterSpacing(1)
        .layoutWeight(1)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Text(time)
        .llText(12, FontWeight.Medium, color)
    }
    .width('100%')
    .opacity(0.85)
  }

  @Builder
  proposalCard(t: TileSpec) {
    Column({ space: 10 }) {
      this.kicker($r('sys.symbol.wand_and_stars_fill'),
        (t.source === 'assistant' ? 'New tile · ' : 'Approval · ') + this.callName(), 'now', this.pal().ink)
      Text('Add “' + t.title + '” to ' + this.callName() + '’s home')
        .llText(20, TilesTheme.LL_WEIGHT, this.pal().ink)
        .lineHeight(23)
        .width('100%')
      Text(t.source === 'assistant' ? 'Made by the Tiles assistant. It appears only after you approve.' :
        'Nothing changes on ' + this.callName() + '’s phone until you approve.')
        .llText(15, FontWeight.Regular, this.pal().ink)
        .lineHeight(22)
        .opacity(0.85)
        .width('100%')

      // Preview only: actions are ignored until the tile is approved.
      TileView({
        tile: t,
        profile: this.profile,
        dark: this.dark,
        onAction: (a: TileAction, x: TileSpec) => {
        }
      })

      this.decisionRow('Approve', () => this.decideTile(t.id, true), () => this.decideTile(t.id, false))
    }
    .padding(16)
    .borderRadius(TilesTheme.LL_RADIUS_L)
    .backgroundColor(this.pal().surface)
    .backdropBlur(TilesTheme.LL_BLUR)
    .shadow(TilesTheme.LL_SHADOW_TILE)
    .transition(this.enter())
  }

  @Builder
  suggestionCard(s: Suggestion) {
    Column({ space: 10 }) {
      this.kicker($r('sys.symbol.wand_and_stars_fill'), 'Approval · ' + this.callName(), 'now', this.pal().ink)
      Text(s.title)
        .llText(20, TilesTheme.LL_WEIGHT, this.pal().ink)
        .lineHeight(23)
        .width('100%')
      if (s.reason.length > 0 || s.detail.length > 0) {
        Text(s.reason.length > 0 && s.detail.length > 0 ? s.reason + '. ' + s.detail :
          (s.reason.length > 0 ? s.reason : s.detail))
          .llText(15, FontWeight.Regular, this.pal().ink)
          .lineHeight(22)
          .opacity(0.85)
          .width('100%')
      }

      this.beforeAfter(s, Adaptation.preview(s.change, this.profile, this.tiles, this.appsHidden))

      this.decisionRow('Approve', () => this.decideSugg(s, true), () => this.decideSugg(s, false))
    }
    .padding(16)
    .borderRadius(TilesTheme.LL_RADIUS_L)
    .backgroundColor(this.pal().surface)
    .backdropBlur(TilesTheme.LL_BLUR)
    .shadow(TilesTheme.LL_SHADOW_TILE)
    .transition(this.enter())
  }

  @Builder
  beforeAfter(s: Suggestion, after: PreviewState) {
    Row({ space: 6 }) {
      Column({ space: 6 }) {
        Text('NOW')
          .llKicker(this.pal().muted)
        MiniHome({
          tiles: this.tiles,
          profile: this.profile,
          dark: this.dark,
          appsHidden: this.appsHidden,
          highlight: Adaptation.focusTile(s.change),
          maxTiles: 6,
          frameWidth: this.miniW
        })
      }
      .layoutWeight(1)
      .alignItems(HorizontalAlign.Start)
      .onAreaChange((o: Area, n: Area) => {
        const w: number = Math.floor(Number(n.width));
        if (!isNaN(w) && w > 80 && Math.abs(w - this.miniW) > 1) {
          this.miniW = w;
        }
      })

      SymbolGlyph($r('sys.symbol.arrow_right'))
        .fontSize(18)
        .fontColor([this.pal().muted])
        .margin({ top: 22 })

      Column({ space: 6 }) {
        Text('AFTER')
          .llKicker(this.pal().okInk)
        MiniHome({
          tiles: after.tiles,
          profile: after.profile,
          dark: this.dark,
          appsHidden: after.appsHidden,
          highlight: s.change.startsWith('remove:') ? '' : Adaptation.focusTile(s.change),
          maxTiles: 6,
          frameWidth: this.miniW
        })
      }
      .layoutWeight(1)
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
    .padding(10)
    .borderRadius(TilesTheme.LL_RADIUS_M)
    .backgroundColor(this.pal().surface2)
  }

  @Builder
  decisionRow(approveLabel: string, onApprove: () => void, onDecline: () => void) {
    Row({ space: 8 }) {
      Row({ space: 6 }) {
        SymbolGlyph($r('sys.symbol.checkmark'))
          .fontSize(18)
          .fontColor([this.pal().onAccent])
        Text(approveLabel)
          .llText(15, FontWeight.Bold, this.pal().onAccent)
      }
      .justifyContent(FlexAlign.Center)
      .layoutWeight(1.3)
      .height(52)
      .borderRadius(TilesTheme.LL_RADIUS_PILL)
      .backgroundColor(this.pal().accent)
      .border({ width: 1.5, color: this.pal().accent })
      .onClick(onApprove)
      .accessibilityText(approveLabel)

      Text('Decline')
        .llText(15, FontWeight.Bold, this.pal().ink)
        .textAlign(TextAlign.Center)
        .layoutWeight(1)
        .height(52)
        .borderRadius(TilesTheme.LL_RADIUS_PILL)
        .border({ width: 1.5, color: this.declineBorder() })
        .onClick(onDecline)
        .accessibilityText('Decline')
    }
    .width('100%')
    .margin({ top: 2 })
  }

  @Builder
  inkPill(label: string, onTap: () => void) {
    Text(label)
      .llText(15, FontWeight.Bold, this.pal().onInk)
      .textAlign(TextAlign.Center)
      .width('100%')
      .height(52)
      .borderRadius(TilesTheme.LL_RADIUS_PILL)
      .backgroundColor(this.pal().ink)
      .onClick(onTap)
  }

  @Builder
  activityRow(r: ActivityRow, last: boolean) {
    Row({ space: 12 }) {
      Row() {
        SymbolGlyph(r.icon)
          .fontSize(20)
          .fontColor([this.toneFg(r.tone)])
      }
      .width(36)
      .height(36)
      .justifyContent(FlexAlign.Center)
      .borderRadius(18)
      .backgroundColor(this.toneBg(r.tone))

      Text(r.text)
        .llText(15, FontWeight.Medium, this.pal().ink)
        .fontWeight(600)
        .lineHeight(20)
        .layoutWeight(1)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Text(r.time)
        .llText(13, FontWeight.Regular, this.pal().muted)
    }
    .width('100%')
    .constraintSize({ minHeight: 56 })
    .padding({ top: 8, bottom: 8 })
    .border({ width: { bottom: last ? 0 : 1 }, color: this.pal().line })
    .accessibilityGroup(true)
  }

  @Builder
  simulateCard() {
    Column({ space: 10 }) {
      Row({ space: 8 }) {
        Text('DEMO')
          .llKicker(TilesTheme.tile('sun', false, this.dark).on)
          .letterSpacing(1)
          .padding({ left: 8, right: 8, top: 3, bottom: 3 })
          .borderRadius(TilesTheme.LL_RADIUS_PILL)
          .linearGradient({
            angle: TilesTheme.tile('sun', false, this.dark).gradient.angle,
            colors: TilesTheme.tile('sun', false, this.dark).gradient.colors
          })
        Text('Simulate a day of use')
          .llText(17, TilesTheme.LL_WEIGHT, this.pal().ink)
          .layoutWeight(1)
      }
      .width('100%')
      Text('Feeds simulated usage into the adaptation engine: 11 missed taps on small targets, the morning tile ' +
        'opened first, some tiles never opened. Real taps on the home are counted the same way.')
        .llText(13, FontWeight.Regular, this.pal().muted)
        .lineHeight(18)
        .width('100%')
      if (this.simResult.length > 0) {
        Text(this.simResult)
          .llText(15, FontWeight.Medium, this.pal().okInk)
          .lineHeight(21)
          .width('100%')
          .padding(12)
          .borderRadius(TilesTheme.LL_RADIUS_S)
          .backgroundColor(this.pal().okSoft)
          .transition(TransitionEffect.OPACITY)
      }
      Row({ space: 8 }) {
        if (this.simulating) {
          LoadingProgress()
            .width(24)
            .height(24)
            .color(this.pal().ink)
        } else {
          SymbolGlyph($r('sys.symbol.play_fill'))
            .fontSize(18)
            .fontColor([this.pal().ink])
        }
        Text(this.simulating ? 'Simulating a day…' : 'Simulate a day of use')
          .llText(15, FontWeight.Bold, this.pal().ink)
      }
      .justifyContent(FlexAlign.Center)
      .width('100%')
      .height(52)
      .borderRadius(TilesTheme.LL_RADIUS_PILL)
      .border({ width: 1.5, color: this.pal().line, style: BorderStyle.Dashed })
      .enabled(!this.simulating)
      .onClick(() => this.simulate())
      .accessibilityText('Demo: simulate a day of use')
    }
    .padding(16)
    .borderRadius(TilesTheme.LL_RADIUS_L)
    .backgroundColor(this.pal().surface)
    .backdropBlur(TilesTheme.LL_BLUR)
    .shadow(TilesTheme.LL_SHADOW_TILE)
  }

  @Builder
  callButton() {
    Row() {
      Row({ space: 10 }) {
        SymbolGlyph($r('sys.symbol.phone_fill'))
          .fontSize(22)
          .fontColor([this.pal().onInk])
        Text('Call ' + this.callName())
          .llText(17, FontWeight.Bold, this.pal().onInk)
      }
      .justifyContent(FlexAlign.Center)
      .height(60)
      .layoutWeight(1)
      .borderRadius(TilesTheme.LL_RADIUS_PILL)
      .backgroundColor(this.pal().ink)
      .shadow(TilesTheme.LL_SHADOW_SHEET)
      .onClick(() => this.toast('Simulated: calling ' + this.callName() + '…'))
      .accessibilityText('Call ' + this.callName() + ' (simulated)')
    }
    .width('100%')
    .padding({ left: 16, right: 16, top: 6, bottom: 24 })
  }
}
