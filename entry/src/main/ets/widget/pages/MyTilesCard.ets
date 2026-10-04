// 2x4 "My tiles" Tiles widget: the top 3 pinned tiles as colorful chips. Tap a chip -> opens that tile in the
// app (postCardAction router, params.tileId). Data: formBindingData from platform/WidgetBridge.ets.
let myTilesStorage = new LocalStorage();

// Symbol for a tile's icon key (SeedTiles / Composer names) or, if unknown, its type. Literal $r only (widget).
function myTilesSymbol(icon: string, type: string): Resource {
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

// One object-literal argument = @Builder pass-by-reference, so chips update when formBindingData arrives.
class ChipArgs {
  id: string = '';
  title: string = '';
  sub: string = '';
  bg: string = '';
  on: string = '';
  icon: string = '';
  type: string = '';
}

@Entry(myTilesStorage)
@Component
struct MyTilesCard {
  @LocalStorageProp('hasData') hasData: boolean = false;
  @LocalStorageProp('profileName') profileName: string = '';
  @LocalStorageProp('tCount') tCount: number = 0;
  @LocalStorageProp('t1Id') t1Id: string = '';
  @LocalStorageProp('t1Title') t1Title: string = '';
  @LocalStorageProp('t1Sub') t1Sub: string = '';
  @LocalStorageProp('t1Bg') t1Bg: string = '#FFC83D';
  @LocalStorageProp('t1On') t1On: string = '#3D2C00';
  @LocalStorageProp('t1Icon') t1Icon: string = '';
  @LocalStorageProp('t1Type') t1Type: string = 'custom';
  @LocalStorageProp('t2Id') t2Id: string = '';
  @LocalStorageProp('t2Title') t2Title: string = '';
  @LocalStorageProp('t2Sub') t2Sub: string = '';
  @LocalStorageProp('t2Bg') t2Bg: string = '#FF6B5A';
  @LocalStorageProp('t2On') t2On: string = '#3B0E08';
  @LocalStorageProp('t2Icon') t2Icon: string = '';
  @LocalStorageProp('t2Type') t2Type: string = 'custom';
  @LocalStorageProp('t3Id') t3Id: string = '';
  @LocalStorageProp('t3Title') t3Title: string = '';
  @LocalStorageProp('t3Sub') t3Sub: string = '';
  @LocalStorageProp('t3Bg') t3Bg: string = '#2ED3A0';
  @LocalStorageProp('t3On') t3On: string = '#04362A';
  @LocalStorageProp('t3Icon') t3Icon: string = '';
  @LocalStorageProp('t3Type') t3Type: string = 'custom';

  @Builder
  chip(a: ChipArgs) {
    Column() {
      SymbolGlyph(myTilesSymbol(a.icon, a.type))
        .fontSize(22)
        .fontColor([a.on])
      Blank()
      Text(a.title)
        .fontSize(14)
        .fontWeight(FontWeight.Bold)
        .fontColor(a.on)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Text(a.sub)
        .fontSize(10)
        .fontColor(a.on)
        .opacity(0.8)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
    }
    .layoutWeight(1)
    .height('100%')
    .alignItems(HorizontalAlign.Start)
    .padding(10)
    .borderRadius(18)
    .backgroundColor(a.bg)
    .accessibilityText(a.title + '. ' + a.sub)
    .onClick(() => {
      postCardAction(this, {
        action: 'router',
        abilityName: 'EntryAbility',
        params: { tileId: a.id, widget: 'myTiles' }
      });
    })
  }

  build() {
    Column() {
      Row() {
        Text('My tiles')
          .fontSize(13)
          .fontWeight(FontWeight.Bold)
          .fontColor('#1C2230')
        Blank()
        Text(this.profileName.length > 0 ? this.profileName : 'Tiles')
          .fontSize(11)
          .fontColor('#5B6170')
          .maxLines(1)
      }
      .width('100%')
      .margin({ bottom: 8 })

      if (this.hasData && this.tCount > 0) {
        Row({ space: 8 }) {
          this.chip({ id: this.t1Id, title: this.t1Title, sub: this.t1Sub, bg: this.t1Bg, on: this.t1On, icon: this.t1Icon, type: this.t1Type })
          if (this.tCount > 1) {
            this.chip({ id: this.t2Id, title: this.t2Title, sub: this.t2Sub, bg: this.t2Bg, on: this.t2On, icon: this.t2Icon, type: this.t2Type })
          }
          if (this.tCount > 2) {
            this.chip({ id: this.t3Id, title: this.t3Title, sub: this.t3Sub, bg: this.t3Bg, on: this.t3On, icon: this.t3Icon, type: this.t3Type })
          }
        }
        .width('100%')
        .layoutWeight(1)
      } else {
        Column() {
          Text('Open Tiles to pick your profile')
            .fontSize(15)
            .fontWeight(FontWeight.Bold)
            .fontColor('#3D2C00')
          Text('Your pinned tiles will show here')
            .fontSize(11)
            .fontColor('#3D2C00')
            .opacity(0.8)
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Start)
        .padding(12)
        .borderRadius(18)
        .backgroundColor('#FFC83D')
        .onClick(() => {
          postCardAction(this, {
            action: 'router',
            abilityName: 'EntryAbility',
            params: { tileId: '', widget: 'myTiles' }
          });
        })
      }
    }
    .width('100%')
    .height('100%')
    .padding(12)
    .backgroundColor('#F6F3EE')
  }
}
