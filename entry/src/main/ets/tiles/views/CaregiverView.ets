import { Profile, Suggestion, TileAction, TileSpec } from '../model/Tile';
import { TileStore } from '../data/TileStore';
import { Adaptation, PreviewState } from '../ai/Adaptation';
import { TilesTheme, ThemePalette, TypeScale } from '../theme/TilesTheme';
import { TileView } from '../components/TileView';
import { MiniHome } from './OnboardingView';
import { Haptics } from '../../platform/Haptics';

/**
 * Caregiver view (route 'caregiver'): a SIMULATION of the caregiver's own phone ("Kasia's phone"), shown on the
 * same device for the demo. Lists assistant proposals waiting for approval and adaptation suggestions with
 * before/after previews; Approve / Decline applies them through TileStore (Adaptation.decide for suggestions).
 * Uses the caregiver's own (standard) text size and colors, not the profile's.
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

  private pal(): ThemePalette {
    return TilesTheme.palette(this.dark, false);
  }

  private ty(): TypeScale {
    return TilesTheme.type(1.0);
  }

  private caregiver(): string {
    return this.profile.caregiver.length > 0 ? this.profile.caregiver : '';
  }

  private person(): string {
    return this.profile.name.length > 0 ? this.profile.name : 'this phone';
  }

  private pendingSuggs(): Suggestion[] {
    return this.suggs.filter((s: Suggestion) => s.status === 'pending');
  }

  private decided(): Suggestion[] {
    return this.suggs.filter((s: Suggestion) => s.status !== 'pending').reverse().slice(0, 6);
  }

  private toast(msg: string): void {
    try {
      this.getUIContext().getPromptAction().showToast({ message: msg, duration: 2200 });
    } catch (e) {
      // toast is cosmetic
    }
  }

  private decideTile(id: string, approve: boolean): void {
    this.getUIContext().animateTo({ duration: 300, curve: TilesTheme.springReflow() }, () => {
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
    this.getUIContext().animateTo({ duration: 300, curve: TilesTheme.springReflow() }, () => {
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
      this.getUIContext().animateTo({ duration: 350, curve: TilesTheme.springReflow() }, () => {
        this.simResult = Adaptation.simulateDay();
        this.simulating = false;
      });
    }, 600);
  }

  build() {
    NavDestination() {
      Scroll() {
        Column({ space: TilesTheme.SPACE_L }) {
          this.topBar()
          this.deviceHeader()

          // ----- assistant proposals -----
          if (this.pending.length > 0) {
            this.sectionTitle('New tiles to approve', this.pending.length)
            if (this.pendingReply.length > 0) {
              Text('Tiles assistant: "' + this.pendingReply + '"')
                .fontSize(this.ty().label)
                .fontColor(this.pal().textMuted)
                .width('100%')
            }
            ForEach(this.pending, (t: TileSpec) => {
              this.proposalCard(t)
            }, (t: TileSpec) => 'p-' + t.id)
            if (this.pending.length > 1) {
              this.pillButton('Approve all ' + this.pending.length.toString(), true, () => {
                this.getUIContext().animateTo({ duration: 300, curve: TilesTheme.springReflow() }, () => {
                  TileStore.get().approveAllPending();
                });
                Haptics.success();
                this.toast('All new tiles approved');
              })
            }
          }

          // ----- adaptation suggestions -----
          this.sectionTitle('Suggested changes', this.pendingSuggs().length)
          if (this.pendingSuggs().length === 0) {
            Column({ space: 6 }) {
              SymbolGlyph($r('sys.symbol.checkmark_circle_fill'))
                .fontSize(36)
                .fontColor([this.pal().success])
              Text('All caught up')
                .fontSize(this.ty().title)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.pal().text)
              Text('Tiles watches how ' + this.person() + ' uses the phone and suggests changes here.')
                .fontSize(this.ty().label)
                .fontColor(this.pal().textMuted)
                .textAlign(TextAlign.Center)
            }
            .width('100%')
            .padding(TilesTheme.SPACE_XL)
            .borderRadius(TilesTheme.RADIUS_TILE)
            .backgroundColor(this.pal().surface)
          }
          ForEach(this.pendingSuggs(), (s: Suggestion) => {
            this.suggestionCard(s)
          }, (s: Suggestion) => 's-' + s.id + '-' + this.tiles.length.toString() + '-' +
            this.profile.textScale.toString())

          this.simulateCard()

          if (this.decided().length > 0) {
            this.sectionTitle('Decided', -1)
            Column() {
              ForEach(this.decided(), (s: Suggestion) => {
                Row({ space: 10 }) {
                  SymbolGlyph(s.status === 'approved' ? $r('sys.symbol.checkmark') : $r('sys.symbol.xmark'))
                    .fontSize(18)
                    .fontColor([s.status === 'approved' ? this.pal().success : this.pal().textMuted])
                  Text(s.title)
                    .fontSize(this.ty().label)
                    .fontColor(this.pal().text)
                    .layoutWeight(1)
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                  Text(s.status === 'approved' ? 'Approved' : 'Declined')
                    .fontSize(this.ty().caption)
                    .fontColor(s.status === 'approved' ? this.pal().success : this.pal().textMuted)
                }
                .width('100%')
                .height(44)
              }, (s: Suggestion) => 'd-' + s.id + s.status)
            }
            .padding({ left: TilesTheme.SPACE_L, right: TilesTheme.SPACE_L })
            .borderRadius(TilesTheme.RADIUS_INNER)
            .backgroundColor(this.pal().surface)
          }

          Text('Simulation: on a real deployment this screen runs on ' +
            (this.caregiver().length > 0 ? this.caregiver() + '\'s' : 'the caregiver\'s') +
            ' own phone. Suggestions come from on-device rules over usage signals; nothing is sent anywhere.')
            .fontSize(this.ty().caption)
            .fontColor(this.pal().textMuted)
            .width('100%')
            .margin({ bottom: 24 })
        }
        .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: 12, bottom: 24 })
      }
      .scrollBar(BarState.Off)
      .align(Alignment.Top)
      .width('100%')
      .height('100%')
      .backgroundColor(this.pal().bg)
    }
    .hideTitleBar(true)
  }

  @Builder
  topBar() {
    Row({ space: 10 }) {
      Row() {
        SymbolGlyph($r('sys.symbol.chevron_left'))
          .fontSize(24)
          .fontColor([this.pal().text])
      }
      .width(48)
      .height(48)
      .justifyContent(FlexAlign.Center)
      .borderRadius(24)
      .backgroundColor(this.pal().surface)
      .onClick(() => this.nav.pop())
      .accessibilityText('Back')

      Blank()
      Text('SIMULATED SECOND DEVICE')
        .fontSize(12)
        .fontWeight(FontWeight.Bold)
        .fontColor('#3D2C00')
        .padding({ left: 10, right: 10, top: 5, bottom: 5 })
        .borderRadius(999)
        .backgroundColor('#FFC83D')
    }
    .width('100%')
  }

  @Builder
  deviceHeader() {
    Row({ space: 14 }) {
      Text(this.caregiver().length > 0 ? this.caregiver().substring(0, 1).toUpperCase() :
        this.person().substring(0, 1).toUpperCase())
        .fontSize(26)
        .fontWeight(FontWeight.Bolder)
        .fontColor('#06243F')
        .textAlign(TextAlign.Center)
        .width(56)
        .height(56)
        .borderRadius(28)
        .backgroundColor('#3DA5FF')
      Column({ space: 4 }) {
        Text(this.caregiver().length > 0 ? this.caregiver() + '\'s phone' : this.person() + '\'s approvals')
          .fontSize(26)
          .fontWeight(FontWeight.Bolder)
          .fontColor('#FFFFFF')
        Text(this.caregiver().length > 0 ?
          'Approves changes to ' + this.person() + '\'s Tiles' +
            (this.profile.caregiverRole.length > 0 ? ' · ' + this.profile.caregiverRole : '') :
          'No caregiver set: changes are approved on this phone')
          .fontSize(this.ty().label)
          .fontColor('#C8CEDB')
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .padding(TilesTheme.SPACE_L)
    .borderRadius(TilesTheme.RADIUS_TILE_LG)
    .backgroundColor('#1C2230')
    .accessibilityGroup(true)
  }

  @Builder
  sectionTitle(title: string, count: number) {
    Row({ space: 8 }) {
      Text(title)
        .fontSize(this.ty().title)
        .fontWeight(FontWeight.Bolder)
        .fontColor(this.pal().text)
      if (count > 0) {
        Text(count.toString())
          .fontSize(this.ty().caption)
          .fontWeight(FontWeight.Bold)
          .fontColor('#FFFFFF')
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(999)
          .backgroundColor('#FF6B5A')
      }
    }
    .width('100%')
    .margin({ top: TilesTheme.SPACE_S })
  }

  @Builder
  proposalCard(t: TileSpec) {
    Column({ space: TilesTheme.SPACE_M }) {
      Row({ space: 6 }) {
        SymbolGlyph($r('sys.symbol.wand_and_stars_fill'))
          .fontSize(18)
          .fontColor([this.pal().accent])
        Text(t.source === 'assistant' ? 'Made by the Tiles assistant for ' + this.person() :
          'New tile for ' + this.person())
          .fontSize(this.ty().caption)
          .fontColor(this.pal().textMuted)
      }
      .width('100%')

      // Preview only: actions are ignored until the tile is approved.
      TileView({
        tile: t,
        profile: this.profile,
        dark: this.dark,
        onAction: (a: TileAction, x: TileSpec) => {
        }
      })

      this.decisionRow(() => this.decideTile(t.id, true), () => this.decideTile(t.id, false))
    }
    .padding(TilesTheme.SPACE_L)
    .borderRadius(TilesTheme.RADIUS_TILE)
    .backgroundColor(this.pal().surface)
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ x: 80 })))
  }

  @Builder
  suggestionCard(s: Suggestion) {
    Column({ space: TilesTheme.SPACE_M }) {
      Text(s.title)
        .fontSize(this.ty().title)
        .fontWeight(FontWeight.Bolder)
        .fontColor(this.pal().text)
        .width('100%')
      if (s.reason.length > 0) {
        Row({ space: 8 }) {
          SymbolGlyph($r('sys.symbol.wand_and_stars_fill'))
            .fontSize(16)
            .fontColor([this.pal().accent])
          Text('Why: ' + s.reason)
            .fontSize(this.ty().label)
            .fontColor(this.pal().text)
            .layoutWeight(1)
        }
        .width('100%')
        .padding(10)
        .borderRadius(TilesTheme.RADIUS_INNER)
        .backgroundColor(this.pal().surfaceAlt)
      }
      if (s.detail.length > 0) {
        Text(s.detail)
          .fontSize(this.ty().label)
          .fontColor(this.pal().textMuted)
          .width('100%')
      }

      this.beforeAfter(s, Adaptation.preview(s.change, this.profile, this.tiles, this.appsHidden))

      this.decisionRow(() => this.decideSugg(s, true), () => this.decideSugg(s, false))
    }
    .padding(TilesTheme.SPACE_L)
    .borderRadius(TilesTheme.RADIUS_TILE)
    .backgroundColor(this.pal().surface)
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ x: 80 })))
  }

  @Builder
  beforeAfter(s: Suggestion, after: PreviewState) {
    Row({ space: 4 }) {
      Column({ space: 6 }) {
        Text('Now')
          .fontSize(this.ty().caption)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().textMuted)
        MiniHome({
          tiles: this.tiles,
          profile: this.profile,
          dark: this.dark,
          appsHidden: this.appsHidden,
          highlight: Adaptation.focusTile(s.change),
          maxTiles: 6,
          frameWidth: 140
        })
      }
      .layoutWeight(1)

      SymbolGlyph($r('sys.symbol.arrow_right'))
        .fontSize(20)
        .fontColor([this.pal().textMuted])

      Column({ space: 6 }) {
        Text('After')
          .fontSize(this.ty().caption)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().success)
        MiniHome({
          tiles: after.tiles,
          profile: after.profile,
          dark: this.dark,
          appsHidden: after.appsHidden,
          highlight: s.change.startsWith('remove:') ? '' : Adaptation.focusTile(s.change),
          maxTiles: 6,
          frameWidth: 140
        })
      }
      .layoutWeight(1)
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
  }

  @Builder
  decisionRow(onApprove: () => void, onDecline: () => void) {
    Row({ space: TilesTheme.SPACE_M }) {
      Row({ space: 6 }) {
        SymbolGlyph($r('sys.symbol.xmark'))
          .fontSize(18)
          .fontColor([this.pal().text])
        Text('Decline')
          .fontSize(17)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().text)
      }
      .justifyContent(FlexAlign.Center)
      .layoutWeight(1)
      .height(56)
      .borderRadius(28)
      .border({ width: 2, color: this.pal().border })
      .onClick(onDecline)
      .accessibilityText('Decline')

      Row({ space: 6 }) {
        SymbolGlyph($r('sys.symbol.checkmark'))
          .fontSize(18)
          .fontColor([this.pal().onSuccess])
        Text('Approve')
          .fontSize(17)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().onSuccess)
      }
      .justifyContent(FlexAlign.Center)
      .layoutWeight(1)
      .height(56)
      .borderRadius(28)
      .backgroundColor(this.pal().success)
      .onClick(onApprove)
      .accessibilityText('Approve')
    }
    .width('100%')
  }

  @Builder
  pillButton(label: string, primary: boolean, onTap: () => void) {
    Text(label)
      .fontSize(17)
      .fontWeight(FontWeight.Bold)
      .fontColor(primary ? this.pal().onSuccess : this.pal().text)
      .textAlign(TextAlign.Center)
      .width('100%')
      .height(56)
      .borderRadius(28)
      .backgroundColor(primary ? this.pal().success : this.pal().surface)
      .onClick(onTap)
  }

  @Builder
  simulateCard() {
    Column({ space: TilesTheme.SPACE_M }) {
      Row({ space: 8 }) {
        Text('DEMO')
          .fontSize(11)
          .fontWeight(FontWeight.Bolder)
          .fontColor('#3D2C00')
          .padding({ left: 8, right: 8, top: 3, bottom: 3 })
          .borderRadius(999)
          .backgroundColor('#FFC83D')
        Text('Simulate a day of use')
          .fontSize(this.ty().body)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().text)
          .layoutWeight(1)
      }
      .width('100%')
      Text('Feeds simulated usage into the adaptation engine: 11 missed taps on small targets, the morning tile ' +
        'opened first, some tiles never opened. Real taps on the home are counted the same way.')
        .fontSize(this.ty().caption)
        .fontColor(this.pal().textMuted)
        .width('100%')
      if (this.simResult.length > 0) {
        Text(this.simResult)
          .fontSize(this.ty().label)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.pal().text)
          .width('100%')
          .padding(10)
          .borderRadius(TilesTheme.RADIUS_INNER)
          .backgroundColor(this.pal().surfaceAlt)
          .transition(TransitionEffect.OPACITY)
      }
      Row({ space: 8 }) {
        if (this.simulating) {
          LoadingProgress()
            .width(24)
            .height(24)
            .color(this.pal().text)
        } else {
          SymbolGlyph($r('sys.symbol.play_fill'))
            .fontSize(18)
            .fontColor([this.pal().text])
        }
        Text(this.simulating ? 'Simulating a day…' : 'Simulate a day of use')
          .fontSize(17)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pal().text)
      }
      .justifyContent(FlexAlign.Center)
      .width('100%')
      .height(56)
      .borderRadius(28)
      .border({ width: 2, color: this.pal().text, style: BorderStyle.Dashed })
      .enabled(!this.simulating)
      .onClick(() => this.simulate())
      .accessibilityText('Demo: simulate a day of use')
    }
    .padding(TilesTheme.SPACE_L)
    .borderRadius(TilesTheme.RADIUS_TILE)
    .backgroundColor(this.pal().surface)
  }
}
