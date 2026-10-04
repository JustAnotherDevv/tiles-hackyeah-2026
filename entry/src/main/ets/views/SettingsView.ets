import { Colors, Fonts, Radius, Space } from '../common/Theme';
import { PersonaSwitcher, ScreenHeader } from '../components/Common';
import { PocketStore } from '../data/PocketStore';
import { ConnectionInfo } from '../data/ApprovalsRepository';
import { DEFAULT_BASE_URL } from '../platform/SettingsStore';

/** Data source (mock / live), gateway URL with connection test, persona, notifications, about. */
@Component
export struct SettingsView {
  @StorageProp('mode') mode: string = 'mock';
  @StorageProp('baseUrl') baseUrl: string = '';
  @StorageProp('notifEnabled') notifEnabled: boolean = false;
  @State urlDraft: string = '';
  @State testing: boolean = false;
  @State testResult: string = '';
  @State testOk: boolean = false;

  aboutToAppear(): void {
    this.urlDraft = this.baseUrl.length > 0 ? this.baseUrl : DEFAULT_BASE_URL;
  }

  build() {
    Scroll() {
      Column({ space: Space.LG }) {
        ScreenHeader({ title: 'Settings', subtitle: '' })

        Column({ space: Space.LG }) {
          this.section('DATA SOURCE')
          Column({ space: Space.MD }) {
            Row({ space: 4 }) {
              this.modeButton('mock', 'Mock (on-device demo)')
              this.modeButton('live', 'Live gateway')
            }
            .width('100%')
            .padding(4)
            .borderRadius(Radius.MD)
            .backgroundColor(Colors.SURFACE_2)

            Text(this.mode === 'mock' ?
              'Mock mode simulates the Aegis gateway on this phone: seeded requests, a new simulated agent ' +
                'request every 20-30 s and drifting posture numbers. All mock data is fictional.' :
              'Live mode polls the Aegis gateway every 4 s: GET /api/approvals, /api/stats; votes go to ' +
                'POST /api/approvals/{id}/approve|deny with the X-Aegis-View-As header.')
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.TEXT_DIM)

            Text('Gateway URL')
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.TEXT)
            TextInput({ placeholder: DEFAULT_BASE_URL, text: $$this.urlDraft })
              .type(InputType.URL)
              .fontSize(Fonts.BODY)
              .fontColor(Colors.TEXT)
              .placeholderColor(Colors.TEXT_FAINT)
              .backgroundColor(Colors.SURFACE_2)
              .borderRadius(Radius.MD)
              .height(44)
            Text('From the emulator, your computer is usually reachable at 10.0.2.2; on a phone use the ' +
              'computer\'s LAN IP. The gateway listens on port 8787.')
              .fontSize(Fonts.TINY)
              .fontColor(Colors.TEXT_FAINT)

            Row({ space: Space.SM }) {
              Button('Save URL')
                .fontSize(Fonts.SMALL)
                .fontColor(Colors.TEXT)
                .backgroundColor(Colors.SURFACE_3)
                .height(36)
                .onClick(() => {
                  if (!this.validUrl(this.urlDraft)) {
                    this.testOk = false;
                    this.testResult = 'Enter a URL starting with http:// or https://';
                    return;
                  }
                  PocketStore.get().setBaseUrl(this.urlDraft);
                  this.getUIContext().getPromptAction().showToast({ message: 'Gateway URL saved', duration: 1500 });
                })
              Button(this.testing ? 'Testing…' : 'Test connection')
                .fontSize(Fonts.SMALL)
                .fontColor(Color.White)
                .backgroundColor(Colors.ACCENT)
                .height(36)
                .enabled(!this.testing)
                .onClick(() => this.test())
            }

            if (this.testResult.length > 0) {
              Text(this.testResult)
                .fontSize(Fonts.SMALL)
                .fontColor(this.testOk ? Colors.GOOD : Colors.BAD)
                .padding(Space.MD)
                .width('100%')
                .borderRadius(Radius.MD)
                .backgroundColor(this.testOk ? Colors.GOOD_SOFT : Colors.BAD_SOFT)
                .transition(TransitionEffect.OPACITY.animation({ duration: 200 }))
            }
          }
          .padding(Space.LG)
          .borderRadius(Radius.LG)
          .backgroundColor(Colors.SURFACE)
          .alignItems(HorizontalAlign.Start)

          this.section('VIEW AS (X-AEGIS-VIEW-AS)')
          Column({ space: Space.SM }) {
            PersonaSwitcher()
            Text('Members approve small actions for agents they sponsor, admins approve mid-size spend and ' +
              'sensitive data access, the owner approves large spend and budget raises. The gateway enforces ' +
              'this; the app only shows why a button is locked.')
              .fontSize(Fonts.TINY)
              .fontColor(Colors.TEXT_FAINT)
          }

          this.section('NOTIFICATIONS')
          Row() {
            Column({ space: 2 }) {
              Text(this.notifEnabled ? 'Enabled' : 'Disabled')
                .fontSize(Fonts.BODY)
                .fontColor(this.notifEnabled ? Colors.GOOD : Colors.WARN)
              Text('A notification is posted for every new approval request; tap it to open the request.')
                .fontSize(Fonts.TINY)
                .fontColor(Colors.TEXT_FAINT)
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)

            if (!this.notifEnabled) {
              Button('Enable')
                .fontSize(Fonts.SMALL)
                .fontColor(Color.White)
                .backgroundColor(Colors.ACCENT)
                .height(34)
                .onClick(() => {
                  PocketStore.get().requestNotifications();
                })
            }
          }
          .padding(Space.LG)
          .width('100%')
          .borderRadius(Radius.LG)
          .backgroundColor(Colors.SURFACE)

          this.section('ABOUT')
          Column({ space: Space.SM }) {
            Text('Aegis Pocket 1.0 · HarmonyOS (API 20+)')
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.TEXT)
            Text('Uses Notification Kit (local notifications + WantAgent), Form Kit (home-screen service ' +
              'widgets), Network Kit (HTTP to the gateway), ArkData Preferences (settings) and ArkUI. ' +
              'Personal data in the preview never leaves the device.')
              .fontSize(Fonts.TINY)
              .fontColor(Colors.TEXT_DIM)
          }
          .alignItems(HorizontalAlign.Start)
          .padding(Space.LG)
          .width('100%')
          .borderRadius(Radius.LG)
          .backgroundColor(Colors.SURFACE)
          .margin({ bottom: Space.XL })
        }
        .padding({ left: Space.PAGE, right: Space.PAGE })
      }
    }
    .scrollBar(BarState.Off)
    .edgeEffect(EdgeEffect.Spring)
    .align(Alignment.Top)
    .width('100%')
    .height('100%')
  }

  @Builder
  section(title: string) {
    Text(title)
      .fontSize(Fonts.TINY)
      .fontColor(Colors.TEXT_DIM)
      .letterSpacing(1)
      .width('100%')
  }

  @Builder
  modeButton(id: string, label: string) {
    Text(label)
      .fontSize(Fonts.SMALL)
      .fontWeight(this.mode === id ? FontWeight.Bold : FontWeight.Normal)
      .fontColor(this.mode === id ? Colors.TEXT : Colors.TEXT_DIM)
      .textAlign(TextAlign.Center)
      .padding({ top: 8, bottom: 8 })
      .layoutWeight(1)
      .borderRadius(Radius.SM)
      .backgroundColor(this.mode === id ? (id === 'live' ? Colors.GOOD_SOFT : Colors.WARN_SOFT) : Color.Transparent)
      .animation({ duration: 200 })
      .onClick(() => {
        if (id === 'live' && !this.validUrl(this.urlDraft)) {
          this.testOk = false;
          this.testResult = 'Enter a valid gateway URL first';
          return;
        }
        if (id === 'live') {
          PocketStore.get().setBaseUrl(this.urlDraft);
        }
        PocketStore.get().setMode(id);
      })
  }

  private validUrl(u: string): boolean {
    const t: string = u.trim();
    return (t.startsWith('http://') || t.startsWith('https://')) && t.length > 10;
  }

  private test(): void {
    if (!this.validUrl(this.urlDraft)) {
      this.testOk = false;
      this.testResult = 'Enter a URL starting with http:// or https://';
      return;
    }
    this.testing = true;
    this.testResult = '';
    PocketStore.get().testConnection(this.urlDraft.trim()).then((r: ConnectionInfo) => {
      this.testing = false;
      this.testOk = r.ok;
      this.testResult = r.message;
    });
  }
}
