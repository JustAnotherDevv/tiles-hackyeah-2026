// 4x4 "Big buttons" Tiles widget for seniors: Call (e.g. Kasia), Pills, SOS as three very large targets.
// Each opens that tile in the app (postCardAction router, params.tileId + params.widgetAction; the app's tile
// actions then place the call / mark pills taken). Data: formBindingData from platform/WidgetBridge.ets.
// Living Light (direction C) skin: "Senior 4x4 big buttons" — palette-gradient tiles (radius 26, soft shadow), big
// icon top-left, label + sub bottom-left, on the pale LL page gradient. Call = leaf, Pills = sun, SOS = rose.
// Palette inlined (form pages cannot import app modules). No animation (widget constraints).
let bigButtonsStorage = new LocalStorage();

// One object-literal argument = @Builder pass-by-reference, so buttons update when formBindingData arrives.
class BigArgs {
  id: string = '';
  action: string = 'open'; // call | open | sos
  title: string = '';
  sub: string = '';
  c1: string = '';
  c2: string = '';
  on: string = '';
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
    Column() {
      SymbolGlyph(bigSymbol(a.action))
        .fontSize(44)
        .fontColor([a.on])
      Blank()
      Text(a.title)
        .fontSize(22)
        .fontWeight(FontWeight.Bold)
        .letterSpacing(-0.26)
        .lineHeight(25)
        .fontColor(a.on)
        .maxLines(2)
        .minFontSize(16)
        .maxFontSize(22)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      if (a.sub.length > 0) {
        Text(a.sub)
          .fontSize(15)
          .fontColor(a.on)
          .opacity(0.85)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 2 })
      }
    }
    .layoutWeight(1)
    .height('100%')
    .alignItems(HorizontalAlign.Start)
    .padding(18)
    .borderRadius(26)
    .linearGradient({ angle: 135, colors: [[a.c1, 0.0], [a.c2, 1.0]] })
    .shadow({ radius: 20, color: '#4028326E', offsetX: 0, offsetY: 12 })
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
      Text(this.profileName.length > 0 ? 'TILES · ' + this.profileName.toUpperCase() : 'TILES')
        .fontSize(12)
        .fontWeight(FontWeight.Bold)
        .letterSpacing(1.4)
        .fontColor('#5B6283')
        .width('100%')
        .padding({ left: 4 })
      Row({ space: 10 }) {
        this.bigButton({
          id: this.bCallId, action: 'call', title: this.hasData ? this.bCallTitle : 'Call family',
          sub: this.hasData ? this.bCallSub : 'Open Tiles to set up',
          c1: '#D2F3D8', c2: '#9FDFB3', on: '#0E3B1F'
        })
        this.bigButton({
          id: this.bPillsId, action: 'open', title: this.bPillsTitle, sub: this.bPillsSub,
          c1: '#FFE48F', c2: '#FFB870', on: '#3B2500'
        })
      }
      .width('100%')
      .layoutWeight(1)
      Row() {
        this.bigButton({
          id: this.bSosId, action: 'sos', title: this.bSosTitle, sub: this.bSosSub,
          c1: '#FFD6DE', c2: '#FFADBE', on: '#5A1424'
        })
      }
      .width('100%')
      .layoutWeight(1)
    }
    .width('100%')
    .height('100%')
    .padding(14)
    .borderRadius(26)
    .linearGradient({ angle: 165, colors: [['#EDF1FC', 0.0], ['#F6F0FA', 0.5], ['#FFF3EA', 1.0]] })
  }
}
