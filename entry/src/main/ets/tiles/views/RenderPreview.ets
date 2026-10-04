import { TileGallery } from '../components/TileGallery';
import { LL_FONT_FAMILY, ThemePalette, TilesTheme } from '../theme/TilesTheme';
import { K_DARK, LLPageMotion } from './ShellKeys';

/**
 * Debug route 'gallery': the tile renderer QA gallery (every block kind / size / palette, profile + dark toggles).
 * Root is its own NavDestination per the Index routing convention. Living Light chrome + page motion.
 */
@Component
export struct RenderPreview {
  @Consume('tilesNav') nav: NavPathStack;
  @StorageProp(K_DARK) dark: boolean = false;
  @State llMotion: LLPageMotion = new LLPageMotion();

  pal(): ThemePalette {
    return TilesTheme.palette(this.dark, false);
  }

  build() {
    NavDestination() {
      Column() {
        Row({ space: 10 }) {
          Row() {
            SymbolGlyph($r('sys.symbol.chevron_left'))
              .fontSize(18)
              .fontColor([this.pal().ink])
          }
          .width(44)
          .height(44)
          .borderRadius(999)
          .justifyContent(FlexAlign.Center)
          .backgroundColor(this.pal().surface)
          .shadow(TilesTheme.LL_SHADOW_SOFT)
          .accessibilityText('Back')
          .onClick(() => {
            this.nav.pop();
          })

          Text('Tile gallery')
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(22)
            .fontWeight(FontWeight.Bold)
            .letterSpacing(TilesTheme.letterSpacing(22))
            .fontColor(this.pal().ink)
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: 8, bottom: 8 })

        TileGallery()
          .layoutWeight(1)
      }
      .width('100%')
      .height('100%')
    }
    .hideTitleBar(true)
    .linearGradient({ angle: this.pal().bgGradient.angle, colors: this.pal().bgGradient.colors })
    .opacity(this.llMotion.opacity)
    .scale({ x: this.llMotion.scale, y: this.llMotion.scale })
    .translate({ y: this.llMotion.ty })
    .customTransition((op: NavigationOperation, isEnter: boolean) =>
      this.llMotion.transitions(this.getUIContext(), op, isEnter))
  }
}
