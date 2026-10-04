// 2x2 "Next up" Tiles widget: the next reminder / pills tile, big and colorful. Tap opens that tile in the
// app (postCardAction router, params.tileId; EntryAbility reads want.parameters.params). Data arrives through
// formBindingData (platform/WidgetBridge.ets, TilesWidgetData). No animation (widget constraints).
// Living Light (direction C) skin: 174-vp palette-gradient card, radius 26, pill action at the bottom. Form pages
// cannot import app modules, so the LL palette (TilesTheme.ets basePair) is inlined here, keyed by the on-color.
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

// Living Light palette gradient (135deg) for a tile, recovered from its on-color (unique per LL palette key; the
// bridge sends a flat midpoint `bg`). Legacy on-colors map onto their LL successor. Unknown -> flat `bg`.
function nextUpGrad(bg: string, on: string): string[] {
  switch (on.toUpperCase()) {
    case '#3B2500': case '#3D2C00': return ['#FFE48F', '#FFB870']; // sun
    case '#0F2A5F': case '#06243F': return ['#D4E4FF', '#A9C4FF']; // sky
    case '#0E3B1F': case '#173A07': return ['#D2F3D8', '#9FDFB3']; // leaf
    case '#5A1424': case '#3B0E08': return ['#FFD6DE', '#FFADBE']; // rose (coral)
    case '#2B1A5E': case '#170B38': return ['#E6D9FF', '#C2ADFF']; // plum (grape)
    case '#3A2E1E': return ['#F7F0E6', '#E8DCCB']; // sand
    case '#F0F2FF': return ['#2A2E48', '#1B1E33']; // ink
    case '#0B3B35': case '#04362A': return ['#D3F5EF', '#9FE3DA']; // mint
    case '#4A2208': case '#3E1A05': return ['#FFDFC9', '#FFBE98']; // peach
    default: return [bg, bg];
  }
}

// LL on-color for legacy on-colors (so text keeps contrast on the pastel gradient).
function nextUpOn(on: string): string {
  switch (on.toUpperCase()) {
    case '#3D2C00': return '#3B2500';
    case '#06243F': return '#0F2A5F';
    case '#173A07': return '#0E3B1F';
    case '#3B0E08': return '#5A1424';
    case '#170B38': return '#2B1A5E';
    case '#04362A': return '#0B3B35';
    case '#3E1A05': return '#4A2208';
    default: return on;
  }
}

function nextUpButton(type: string): string {
  if (type === 'pills') {
    return 'Mark taken';
  }
  if (type === 'call') {
    return 'Call';
  }
  return 'Open';
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
  @LocalStorageProp('nBg') nBg: string = '#FFD17F';
  @LocalStorageProp('nOn') nOn: string = '#3B2500';
  @LocalStorageProp('nIcon') nIcon: string = '';
  @LocalStorageProp('nType') nType: string = 'custom';

  build() {
    Column({ space: 6 }) {
      Row({ space: 8 }) {
        SymbolGlyph(this.hasData ? nextUpSymbol(this.nIcon, this.nType) : $r('sys.symbol.star_fill'))
          .fontSize(24)
          .fontColor([this.fg()])
        Text(this.headline())
          .fontSize(17)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(-0.2)
          .fontColor(this.fg())
          .maxLines(1)
          .minFontSize(13)
          .maxFontSize(17)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
      }
      .width('100%')

      Text(this.subline())
        .fontSize(13)
        .lineHeight(17)
        .fontColor(this.fg())
        .opacity(0.85)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })

      Blank()

      Text(this.hasData ? nextUpButton(this.nType) : 'Open Tiles')
        .fontSize(15)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.fg())
        .textAlign(TextAlign.Center)
        .maxLines(1)
        .width('100%')
        .height(48)
        .borderRadius(999)
        .backgroundColor('#24000000')
    }
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Start)
    .padding(16)
    .borderRadius(26)
    .linearGradient({ angle: 135, colors: this.gradStops() })
    .accessibilityText(this.hasData ? 'Next up: ' + this.nTitle + ' ' + this.nBig + '. ' + this.nSub : 'Open Tiles')
    .onClick(() => {
      postCardAction(this, {
        action: 'router',
        abilityName: 'EntryAbility',
        params: { tileId: this.nId, widget: 'nextUp' }
      });
    })
  }

  fg(): string {
    return this.hasData ? nextUpOn(this.nOn) : '#3B2500';
  }

  gradStops(): Array<[ResourceColor, number]> {
    const g: string[] = this.hasData ? nextUpGrad(this.nBg, this.nOn) : ['#FFE48F', '#FFB870'];
    return [[g[0], 0.0], [g[1], 1.0]];
  }

  // Design: "Pills 8:00" — title then the due time on one line.
  headline(): string {
    if (!this.hasData) {
      return 'Tiles';
    }
    return this.nBig.length > 0 ? this.nTitle + ' ' + this.nBig : this.nTitle;
  }

  subline(): string {
    if (!this.hasData) {
      return 'Pick a profile to fill your widget';
    }
    if (this.nLabel.length > 0 && this.nLabel !== 'NEXT UP') {
      const day: string = this.nLabel.charAt(0) + this.nLabel.substring(1).toLowerCase();
      return this.nSub.length > 0 ? day + ' · ' + this.nSub : day;
    }
    return this.nSub;
  }
}
