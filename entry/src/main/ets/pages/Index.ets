import { Colors, Fonts, Radius, Space } from '../common/Theme';
import { HomeView } from '../views/HomeView';
import { InboxView } from '../views/InboxView';
import { PreviewView } from '../views/PreviewView';
import { SettingsView } from '../views/SettingsView';
import { DetailView } from '../views/DetailView';

class TabDef {
  index: number;
  label: string;
  glyph: string;

  constructor(index: number, label: string, glyph: string) {
    this.index = index;
    this.label = label;
    this.glyph = glyph;
  }
}

const TAB_HOME = 0;
const TAB_INBOX = 1;
const TAB_PREVIEW = 2;
const TAB_SETTINGS = 3;

const TABS: TabDef[] = [
  new TabDef(TAB_HOME, 'Home', '◉'),
  new TabDef(TAB_INBOX, 'Inbox', '≡'),
  new TabDef(TAB_PREVIEW, 'Preview', '◐'),
  new TabDef(TAB_SETTINGS, 'Settings', '⋯')
];

@Entry
@Component
struct Index {
  @Provide('pathStack') pathStack: NavPathStack = new NavPathStack();
  @State currentTab: number = TAB_HOME;
  @State bannerText: string = '';
  @StorageProp('pendingCount') pending: number = 0;
  @StorageProp('openApprovalId') @Watch('onOpenApproval') openApprovalId: string = '';
  @StorageProp('openTarget') @Watch('onOpenTarget') openTarget: string = '';
  @StorageProp('newRequestTitle') @Watch('onNewRequest') newRequest: string = '';
  private tabsController: TabsController = new TabsController();
  private bannerTimer: number = -1;

  aboutToAppear(): void {
    // A cold start from a notification or the widget sets these before the page exists.
    if (this.openApprovalId.length > 0) {
      this.onOpenApproval();
    }
    if (this.openTarget.length > 0) {
      this.onOpenTarget();
    }
  }

  onOpenApproval(): void {
    if (this.openApprovalId.length === 0) {
      return;
    }
    this.openDetail(this.openApprovalId.split('#')[0]);
  }

  onOpenTarget(): void {
    const target: string = this.openTarget.split('#')[0];
    if (target === 'inbox') {
      this.pathStack.clear();
      this.switchTab(TAB_INBOX);
    }
  }

  onNewRequest(): void {
    if (this.newRequest.length === 0) {
      return;
    }
    const text: string = this.newRequest.split('#')[0];
    this.getUIContext().animateTo({ duration: 320, curve: Curve.EaseOut }, () => {
      this.bannerText = text;
    });
    if (this.bannerTimer !== -1) {
      clearTimeout(this.bannerTimer);
    }
    this.bannerTimer = setTimeout(() => {
      this.getUIContext().animateTo({ duration: 260, curve: Curve.EaseIn }, () => {
        this.bannerText = '';
      });
      this.bannerTimer = -1;
    }, 5000);
  }

  openDetail(id: string): void {
    this.pathStack.pushPathByName('detail', id + '#' + Date.now().toString(), true);
  }

  switchTab(index: number): void {
    this.currentTab = index;
    this.tabsController.changeIndex(index);
  }

  @Builder
  pageMap(name: string, param: Object) {
    if (name === 'detail') {
      DetailView({ approvalId: param as string })
    }
  }

  @Builder
  tabBar(t: TabDef) {
    Column({ space: 3 }) {
      Stack({ alignContent: Alignment.TopEnd }) {
        Text(t.glyph)
          .fontSize(20)
          .fontColor(this.currentTab === t.index ? Colors.ACCENT : Colors.TEXT_FAINT)
          .width(36)
          .height(26)
          .textAlign(TextAlign.Center)
        if (t.index === TAB_INBOX && this.pending > 0) {
          Text(this.pending.toString())
            .fontSize(9)
            .fontWeight(FontWeight.Bold)
            .fontColor(Color.White)
            .backgroundColor(Colors.VIOLET)
            .borderRadius(8)
            .padding({ left: 4, right: 4 })
            .height(15)
            .constraintSize({ minWidth: 15 })
            .textAlign(TextAlign.Center)
            .transition(TransitionEffect.scale({ x: 0, y: 0 }).animation({ duration: 200 }))
        }
      }

      Text(t.label)
        .fontSize(10)
        .fontWeight(this.currentTab === t.index ? FontWeight.Bold : FontWeight.Normal)
        .fontColor(this.currentTab === t.index ? Colors.TEXT : Colors.TEXT_FAINT)
    }
    .width('100%')
    .height('100%')
    .justifyContent(FlexAlign.Center)
  }

  build() {
    Navigation(this.pathStack) {
      Stack({ alignContent: Alignment.Top }) {
        Tabs({ barPosition: BarPosition.End, index: this.currentTab, controller: this.tabsController }) {
          TabContent() {
            HomeView({
              onOpenApproval: (id: string) => this.openDetail(id),
              onOpenInbox: () => this.switchTab(TAB_INBOX)
            })
          }
          .tabBar(this.tabBar(TABS[TAB_HOME]))

          TabContent() {
            InboxView({ onOpenApproval: (id: string) => this.openDetail(id) })
          }
          .tabBar(this.tabBar(TABS[TAB_INBOX]))

          TabContent() {
            PreviewView()
          }
          .tabBar(this.tabBar(TABS[TAB_PREVIEW]))

          TabContent() {
            SettingsView()
          }
          .tabBar(this.tabBar(TABS[TAB_SETTINGS]))
        }
        .barHeight(60)
        .barBackgroundColor(Colors.SURFACE)
        .divider({ strokeWidth: 1, color: Colors.BORDER })
        .animationDuration(250)
        .onChange((index: number) => {
          this.currentTab = index;
        })
        .width('100%')
        .height('100%')

        if (this.bannerText.length > 0) {
          Row({ space: Space.MD }) {
            Circle()
              .width(10)
              .height(10)
              .fill(Colors.VIOLET)
            Column({ space: 2 }) {
              Text('New approval request')
                .fontSize(Fonts.TINY)
                .fontColor(Colors.VIOLET)
                .fontWeight(FontWeight.Bold)
              Text(this.bannerText)
                .fontSize(Fonts.SMALL)
                .fontColor(Colors.TEXT)
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Text('Review')
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.ACCENT)
          }
          .width('92%')
          .padding(Space.MD)
          .margin({ top: Space.SM })
          .borderRadius(Radius.LG)
          .backgroundColor(Colors.SURFACE_3)
          .border({ width: 1, color: Colors.VIOLET_SOFT })
          .shadow({ radius: 24, color: '#80000000', offsetY: 6 })
          .transition(TransitionEffect.move(TransitionEdge.TOP).combine(TransitionEffect.OPACITY))
          .onClick(() => {
            this.bannerText = '';
            this.switchTab(TAB_INBOX);
          })
        }
      }
      .width('100%')
      .height('100%')
    }
    .navDestination(this.pageMap)
    .hideTitleBar(true)
    .mode(NavigationMode.Stack)
    .backgroundColor(Colors.BG)
    .width('100%')
    .height('100%')
  }
}
