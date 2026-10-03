// 2x4 "AI posture" service widget. Data arrives through formBindingData (see platform/WidgetBridge.ets).
let postureWideStorage = new LocalStorage();

@Entry(postureWideStorage)
@Component
struct PostureWideCard {
  @LocalStorageProp('pending') pending: number = 3;
  @LocalStorageProp('blocked') blocked: number = 37;
  @LocalStorageProp('redacted') redacted: number = 212;
  @LocalStorageProp('budgetLeftPct') budgetLeftPct: number = 63;
  @LocalStorageProp('spendToday') spendToday: string = '$148';
  @LocalStorageProp('topRequest') topRequest: string = 'Buy MarketPulse Pro ($50)';
  @LocalStorageProp('mode') mode: string = 'MOCK';
  @LocalStorageProp('updated') updated: string = '--:--';

  @Builder
  stat(value: string, label: string, color: string) {
    Column() {
      Text(value).fontSize(16).fontWeight(FontWeight.Bold).fontColor(color)
      Text(label).fontSize(10).fontColor('#8A97AD')
    }
    .alignItems(HorizontalAlign.Start)
    .layoutWeight(1)
  }

  build() {
    Column() {
      Row() {
        Text('AEGIS POCKET')
          .fontSize(11)
          .fontWeight(FontWeight.Bold)
          .fontColor('#8A97AD')
          .letterSpacing(1.5)
        Blank()
        Text(this.mode + '  ' + this.updated)
          .fontSize(9)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.mode === 'LIVE' ? '#2FD08A' : '#F5B544')
          .padding({ left: 6, right: 6, top: 2, bottom: 2 })
          .borderRadius(6)
          .backgroundColor(this.mode === 'LIVE' ? '#123326' : '#3A2C12')
      }
      .width('100%')

      Row() {
        Text(this.pending.toString())
          .fontSize(34)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pending > 0 ? '#A78BFA' : '#2FD08A')
        Column() {
          Text(this.pending === 1 ? 'approval waiting' : 'approvals waiting')
            .fontSize(11)
            .fontColor('#E6EDF7')
          Text(this.topRequest)
            .fontSize(11)
            .fontColor('#8A97AD')
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .alignItems(HorizontalAlign.Start)
        .margin({ left: 10 })
        .layoutWeight(1)
      }
      .width('100%')
      .margin({ top: 6 })

      Blank()

      Row() {
        this.stat(this.blocked.toString(), 'threats blocked', '#FF5A6A')
        this.stat(this.redacted.toString(), 'PII redacted', '#F5B544')
        this.stat(this.budgetLeftPct.toString() + '%', 'budget left', '#2FD08A')
        this.stat(this.spendToday, 'spent today', '#E6EDF7')
      }
      .width('100%')

      Progress({ value: 100 - this.budgetLeftPct, total: 100, type: ProgressType.Linear })
        .color(this.budgetLeftPct < 20 ? '#FF5A6A' : '#4F8CFF')
        .backgroundColor('#243047')
        .width('100%')
        .height(4)
        .margin({ top: 6 })
    }
    .width('100%')
    .height('100%')
    .padding(12)
    .backgroundColor('#131A26')
    .onClick(() => {
      postCardAction(this, {
        action: 'router',
        abilityName: 'EntryAbility',
        params: { aegisTarget: 'inbox' }
      });
    })
  }
}
