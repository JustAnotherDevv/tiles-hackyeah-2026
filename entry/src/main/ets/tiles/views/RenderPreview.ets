import { TileGallery } from '../components/TileGallery';

/**
 * Debug route 'gallery': the tile renderer QA gallery (every block kind / size / palette, profile + dark toggles).
 * Root is its own NavDestination per the Index routing convention.
 */
@Component
export struct RenderPreview {
  @Consume('tilesNav') nav: NavPathStack;

  build() {
    NavDestination() {
      Column() {
        Row() {
          Text('‹ Back')
            .fontSize(16)
            .fontWeight(FontWeight.Bold)
            .fontColor('#0B57D0')
            .height(48)
            .padding({ left: 16, right: 16 })
            .onClick(() => {
              this.nav.pop();
            })
          Text('Tile renderer gallery')
            .fontSize(18)
            .fontWeight(FontWeight.Bold)
            .fontColor('#1C2230')
        }
        .width('100%')

        TileGallery()
          .layoutWeight(1)
      }
      .width('100%')
      .height('100%')
      .backgroundColor('#F6F3EE')
    }
    .hideTitleBar(true)
  }
}
