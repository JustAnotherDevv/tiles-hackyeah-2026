// 2x2 "AI posture" service widget. Data arrives through formBindingData (see platform/WidgetBridge.ets).
let postureStorage = new LocalStorage();

@Entry(postureStorage)
@Component
struct PostureCard {
  @LocalStorageProp('pending') pending: number = 3;
  @LocalStorageProp('blocked') blocked: number = 37;
  @LocalStorageProp('redacted') redacted: number = 212;
  @LocalStorageProp('budgetLeftPct') budgetLeftPct: number = 63;
  @LocalStorageProp('mode') mode: string = 'MOCK';
  @LocalStorageProp('updated') updated: string = '--:--';

  build() {
    Column() {
      Row() {
        Text('AEGIS')
          .fontSize(11)
          .fontWeight(FontWeight.Bold)
          .fontColor('#8A97AD')
          .letterSpacing(1.5)
        Blank()
        Text(this.mode)
          .fontSize(9)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.mode === 'LIVE' ? '#2FD08A' : '#F5B544')
          .padding({ left: 6, right: 6, top: 2, bottom: 2 })
          .borderRadius(6)
          .backgroundColor(this.mode === 'LIVE' ? '#123326' : '#3A2C12')
      }
      .width('100%')

      Column() {
        Text(this.pending.toString())
          .fontSize(40)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pending > 0 ? '#A78BFA' : '#2FD08A')
        Text(this.pending === 1 ? 'approval waiting' : 'approvals waiting')
          .fontSize(11)
          .fontColor('#E6EDF7')
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
      .margin({ top: 4 })

      Blank()

      Row() {
        Column() {
          Text(this.blocked.toString()).fontSize(13).fontWeight(FontWeight.Bold).fontColor('#FF5A6A')
          Text('blocked').fontSize(9).fontColor('#8A97AD')
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Column() {
          Text(this.redacted.toString()).fontSize(13).fontWeight(FontWeight.Bold).fontColor('#F5B544')
          Text('redacted').fontSize(9).fontColor('#8A97AD')
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Column() {
          Text(this.budgetLeftPct.toString() + '%').fontSize(13).fontWeight(FontWeight.Bold).fontColor('#2FD08A')
          Text('budget').fontSize(9).fontColor('#8A97AD')
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
      }
      .width('100%')
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
