// 2x2 "Next up" Tiles widget: the next reminder / pills tile, big and colorful. Tap opens that tile in the
// app (postCardAction router, params.tileId; EntryAbility reads want.parameters.params). Data arrives through
// formBindingData (platform/WidgetBridge.ets, TilesWidgetData). No animation (widget constraints).
let nextUpStorage = new LocalStorage();

// Symbol for a tile's icon key (SeedTiles / Composer names) or, if unknown, its type. Literal $r only (widget).
function nextUpSymbol(icon: string, type: string): Resource {
  switch (icon) {
    case 'cross_case_fill': return $r('sys.symbol.cross_case_fill');
    case 'drop_fill': return $r('sys.symbol.drop_fill');
    case 'phone_fill': return $r('sys.symbol.phone_fill');
    case 'heart_fill': return $r('sys.symbol.heart_fill');
    case 'umbrella': return $r('sys.symbol.umbrella');
    case 'cloud_sun_fill': return $r('sys.symbol.cloud_sun_fill');
    case 'exclamationmark_shield_fill': return $r('sys.symbol.exclamationmark_shield_fill');
    case 'checkmark_shield_fill': return $r('sys.symbol.checkmark_shield_fill');
    case 'calendar_fill': return $r('sys.symbol.calendar_fill');
    case 'figure_walk': return $r('sys.symbol.figure_walk');
    case 'phone_sos': return $r('sys.symbol.phone_sos');
    case 'house_fill': return $r('sys.symbol.house_fill');
    case 'book_pages_fill': return $r('sys.symbol.book_pages_fill');
    case 'timer': return $r('sys.symbol.timer');
    case 'hourglass': return $r('sys.symbol.hourglass');
    case 'leaf': return $r('sys.symbol.leaf');
    case 'bell_fill': return $r('sys.symbol.bell_fill');
    case 'person_2_fill': return $r('sys.symbol.person_2_fill');
    case 'bus_fill': return $r('sys.symbol.bus_fill');
    case 'tram_fill': return $r('sys.symbol.tram_fill');
    case 'speaker_wave_3': return $r('sys.symbol.speaker_wave_3');
    case 'fork_knife': return $r('sys.symbol.fork_knife');
    case 'list_bullet': return $r('sys.symbol.list_bullet');
    case 'flag': return $r('sys.symbol.flag');
    default: break;
  }
  switch (type) {
    case 'pills': return $r('sys.symbol.cross_case_fill');
    case 'call': return $r('sys.symbol.phone_fill');
    case 'weather': return $r('sys.symbol.cloud_sun_fill');
    case 'guardian': return $r('sys.symbol.checkmark_shield_fill');
    case 'plan': return $r('sys.symbol.fork_knife');
    case 'timer': return $r('sys.symbol.timer');
    case 'homework': return $r('sys.symbol.book_pages_fill');
    case 'screentime': return $r('sys.symbol.hourglass');
    case 'reminder': return $r('sys.symbol.bell_fill');
    case 'note': return $r('sys.symbol.doc_text');
    case 'sos': return $r('sys.symbol.phone_sos');
    case 'commute': return $r('sys.symbol.bus_fill');
    case 'adventure': return $r('sys.symbol.leaf');
    default: return $r('sys.symbol.star_fill');
  }
}

@Entry(nextUpStorage)
@Component
struct NextUpCard {
  @LocalStorageProp('hasData') hasData: boolean = false;
  @LocalStorageProp('nId') nId: string = '';
  @LocalStorageProp('nLabel') nLabel: string = 'NEXT UP';
  @LocalStorageProp('nBig') nBig: string = '';
  @LocalStorageProp('nTitle') nTitle: string = 'Open Tiles';
  @LocalStorageProp('nSub') nSub: string = 'Your next reminder shows here';
  @LocalStorageProp('nBg') nBg: string = '#FFC83D';
  @LocalStorageProp('nOn') nOn: string = '#3D2C00';
  @LocalStorageProp('nIcon') nIcon: string = '';
  @LocalStorageProp('nType') nType: string = 'custom';

  build() {
    Column() {
      Row() {
        Stack() {
          SymbolGlyph(this.hasData ? nextUpSymbol(this.nIcon, this.nType) : $r('sys.symbol.star_fill'))
            .fontSize(20)
            .fontColor([this.nOn])
        }
        .width(36)
        .height(36)
        .borderRadius(18)
        .backgroundColor('#33FFFFFF')

        Blank()

        Text(this.hasData ? this.nLabel : 'TILES')
          .fontSize(10)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(1)
          .fontColor(this.nOn)
          .opacity(0.8)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
          .textAlign(TextAlign.End)
          .margin({ left: 6 })
      }
      .width('100%')

      Blank()

      if (this.nBig.length > 0) {
        Text(this.nBig)
          .fontSize(40)
          .fontWeight(FontWeight.Bolder)
          .fontColor(this.nOn)
          .maxLines(1)
          .minFontSize(24)
          .maxFontSize(40)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      Text(this.hasData ? this.nTitle : 'Open Tiles')
        .fontSize(this.nBig.length > 0 ? 16 : 22)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.nOn)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Text(this.hasData ? this.nSub : 'Pick a profile to fill your widget')
        .fontSize(11)
        .fontColor(this.nOn)
        .opacity(0.8)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .margin({ top: 2 })
    }
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Start)
    .padding(14)
    .backgroundColor(this.hasData ? this.nBg : '#FFC83D')
    .accessibilityText(this.hasData ? 'Next up: ' + this.nTitle + ' ' + this.nBig + '. ' + this.nSub : 'Open Tiles')
    .onClick(() => {
      postCardAction(this, {
        action: 'router',
        abilityName: 'EntryAbility',
        params: { tileId: this.nId, widget: 'nextUp' }
      });
    })
  }
}
