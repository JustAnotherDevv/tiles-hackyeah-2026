// 4x4 "Big buttons" Tiles widget for seniors: Call (e.g. Kasia), Pills, SOS as three very large targets.
// Each opens that tile in the app (postCardAction router, params.tileId + params.widgetAction; the app's tile
// actions then place the call / mark pills taken). Data: formBindingData from platform/WidgetBridge.ets.
let bigButtonsStorage = new LocalStorage();

// One object-literal argument = @Builder pass-by-reference, so buttons update when formBindingData arrives.
class BigArgs {
  id: string = '';
  action: string = 'open'; // call | open | sos
  title: string = '';
  sub: string = '';
  bg: string = '';
}

function bigSymbol(action: string): Resource {
  if (action === 'call') {
    return $r('sys.symbol.phone_fill');
  }
  if (action === 'sos') {
    return $r('sys.symbol.phone_sos');
  }
  return $r('sys.symbol.cross_case_fill');
}

@Entry(bigButtonsStorage)
@Component
struct BigButtonsCard {
  @LocalStorageProp('hasData') hasData: boolean = false;
  @LocalStorageProp('profileName') profileName: string = '';
  @LocalStorageProp('bCallId') bCallId: string = '';
  @LocalStorageProp('bCallTitle') bCallTitle: string = 'Call';
  @LocalStorageProp('bCallSub') bCallSub: string = '';
  @LocalStorageProp('bPillsId') bPillsId: string = '';
  @LocalStorageProp('bPillsTitle') bPillsTitle: string = 'Pills';
  @LocalStorageProp('bPillsSub') bPillsSub: string = '';
  @LocalStorageProp('bSosId') bSosId: string = '';
  @LocalStorageProp('bSosTitle') bSosTitle: string = 'SOS';
  @LocalStorageProp('bSosSub') bSosSub: string = 'Call for help';

  @Builder
  bigButton(a: BigArgs) {
    Row() {
      Stack() {
        SymbolGlyph(bigSymbol(a.action))
          .fontSize(30)
          .fontColor(['#FFFFFF'])
      }
      .width(56)
      .height(56)
      .borderRadius(28)
      .backgroundColor('#33FFFFFF')

      Column() {
        Text(a.title)
          .fontSize(24)
          .fontWeight(FontWeight.Bolder)
          .fontColor('#FFFFFF')
          .maxLines(1)
          .minFontSize(16)
          .maxFontSize(24)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        if (a.sub.length > 0) {
          Text(a.sub)
            .fontSize(13)
            .fontColor('#FFFFFF')
            .opacity(0.9)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
      }
      .layoutWeight(1)
      .alignItems(HorizontalAlign.Start)
      .margin({ left: 14 })
    }
    .width('100%')
    .layoutWeight(1)
    .padding({ left: 16, right: 16 })
    .borderRadius(24)
    .backgroundColor(a.bg)
    .accessibilityText(a.title + '. ' + a.sub)
    .onClick(() => {
      postCardAction(this, {
        action: 'router',
        abilityName: 'EntryAbility',
        params: { tileId: a.id, widget: 'bigButtons', widgetAction: a.action }
      });
    })
  }

  build() {
    Column({ space: 10 }) {
      Text(this.profileName.length > 0 ? 'Tiles · ' + this.profileName : 'Tiles')
        .fontSize(15)
        .fontWeight(FontWeight.Bold)
        .fontColor('#1C2230')
        .width('100%')
      this.bigButton({
        id: this.bCallId, action: 'call', title: this.hasData ? this.bCallTitle : 'Call family',
        sub: this.hasData ? this.bCallSub : 'Open Tiles to set up', bg: '#0B57D0'
      })
      this.bigButton({ id: this.bPillsId, action: 'open', title: this.bPillsTitle, sub: this.bPillsSub, bg: '#00664F' })
      this.bigButton({ id: this.bSosId, action: 'sos', title: this.bSosTitle, sub: this.bSosSub, bg: '#B3261E' })
    }
    .width('100%')
    .height('100%')
    .padding(14)
    .backgroundColor('#F6F3EE')
  }
}
