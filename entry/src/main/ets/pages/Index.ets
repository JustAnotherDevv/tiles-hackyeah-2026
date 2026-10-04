import { common, ConfigurationConstant } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { Profile, TileSpec } from '../tiles/model/Tile';
import { K_ONBOARDED, K_PROFILE, TileStore } from '../tiles/data/TileStore';
import { ThemePalette, TilesTheme } from '../tiles/theme/TilesTheme';
import { PlatformKeys } from '../tiles/platform/TilesPlatform';
import { HomeView } from '../tiles/views/HomeView';
import { TileDetailView } from '../tiles/views/TileDetailView';
import { GuardianView } from '../tiles/views/GuardianView';
import { OnboardingView } from '../tiles/views/OnboardingView';
import { CaregiverView } from '../tiles/views/CaregiverView';
import { TilesSettingsView } from '../tiles/views/TilesSettingsView';
import { RenderPreview } from '../tiles/views/RenderPreview';
import { K_ASSISTANT_SEED, K_DARK } from '../tiles/views/ShellKeys';

/**
 * Tiles shell: one Navigation whose root is the Home grid. Routes (NavPathStack names):
 *   detail (param = tile id) · onboarding · caregiver · guardian · settings
 * The Assistant is a sheet on Home (not a route). Notifications / reminders / the widget open a tile through
 * AppStorage `tiles.openTileId`; 'navigate' tile actions arrive through `tiles.navigate`.
 */
@Entry
@Component
struct Index {
  @Provide('tilesNav') nav: NavPathStack = new NavPathStack();
  @StorageLink(K_PROFILE) profile: Profile = new Profile();
  @StorageProp(K_ONBOARDED) onboarded: boolean = false;
  @StorageProp(K_DARK) @Watch('onDarkChange') dark: boolean = false;
  @StorageProp(PlatformKeys.OPEN_TILE_ID) @Watch('onOpenTile') openTileId: string = '';
  @StorageProp(PlatformKeys.NAVIGATE) @Watch('onNavigate') navigateTo: string = '';

  aboutToAppear(): void {
    this.syncDark();
    this.styleSystemBars();
    if (!TileStore.get().isOnboarded()) {
      this.nav.pushPathByName('onboarding', '', false);
    }
    // Cold start from a notification / reminder / widget.
    if (this.openTileId.length > 0) {
      this.onOpenTile();
    }
    if (this.navigateTo.length > 0) {
      this.onNavigate();
    }
  }

  onPageShow(): void {
    this.syncDark();
    this.styleSystemBars();
  }

  onDarkChange(): void {
    this.styleSystemBars();
  }

  /**
   * Living Light chrome: status / navigation bars continue the page gradient with ink content (onInk in dark).
   * Re-applied after a short delay because the ability styles the window once content loads.
   */
  styleSystemBars(): void {
    this.applySystemBars();
    setTimeout(() => {
      this.applySystemBars();
    }, 400);
  }

  applySystemBars(): void {
    let ctx: common.UIAbilityContext;
    try {
      ctx = this.getUIContext().getHostContext() as common.UIAbilityContext;
    } catch (e) {
      return;
    }
    const dark: boolean = this.dark;
    const inkColor: string = dark ? '#F3F5FF' : '#1D2140';
    window.getLastWindow(ctx).then((win: window.Window) => {
      try {
        win.setWindowBackgroundColor(dark ? '#14162A' : '#EDF1FC');
      } catch (e) {
        // Background color is cosmetic.
      }
      // The window is not laid out full screen (full-screen layout pushed Navigation content under the clock),
      // so the bars take the gradient's end colors: top #EDF1FC, bottom #FFF3EA (dark: #1A1D38 / #1E1A30).
      win.setWindowSystemBarProperties({
        statusBarColor: dark ? '#1A1D38' : '#EDF1FC',
        statusBarContentColor: inkColor,
        navigationBarColor: dark ? '#1E1A30' : '#FFF3EA',
        navigationBarContentColor: inkColor
      }).catch(() => {
        // System bar styling is cosmetic.
      });
    }).catch(() => {
      // No window yet (e.g. preview).
    });
  }

  syncDark(): void {
    const userChoice: number | undefined = AppStorage.get<number>('tiles.darkUser');
    if (userChoice !== undefined && userChoice !== 0) {
      AppStorage.setOrCreate<boolean>(K_DARK, userChoice === 2);
      return;
    }
    let dark: boolean = false;
    try {
      const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
      dark = ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    } catch (e) {
      dark = false;
    }
    AppStorage.setOrCreate<boolean>(K_DARK, dark);
  }

  onOpenTile(): void {
    const id: string = this.openTileId;
    if (id.length === 0) {
      return;
    }
    AppStorage.setOrCreate<string>(PlatformKeys.OPEN_TILE_ID, '');
    const t: TileSpec | null = TileStore.get().tile(id);
    if (t === null) {
      return;
    }
    if (t.type === 'guardian') {
      this.nav.pushPathByName('guardian', id, true);
      return;
    }
    // Replace an already open detail instead of stacking several.
    const top: string[] = this.nav.getAllPathName();
    if (top.length > 0 && top[top.length - 1] === 'detail') {
      this.nav.replacePathByName('detail', id, true);
    } else {
      this.nav.pushPathByName('detail', id, true);
    }
  }

  onNavigate(): void {
    const route: string = this.navigateTo;
    if (route.length === 0) {
      return;
    }
    AppStorage.setOrCreate<string>(PlatformKeys.NAVIGATE, '');
    if (route === 'assistant') {
      this.nav.clear(false);
      AppStorage.setOrCreate<string>(K_ASSISTANT_SEED, 'open#' + Date.now().toString());
      return;
    }
    if (route === 'home') {
      this.nav.clear(true);
      return;
    }
    if (route === 'onboarding' || route === 'caregiver' || route === 'guardian' || route === 'settings' ||
      route === 'gallery') {
      this.nav.pushPathByName(route, '', true);
    }
  }

  @Builder
  pageMap(name: string, param: Object) {
    if (name === 'detail') {
      TileDetailView({ tileId: param as string })
    } else if (name === 'onboarding') {
      OnboardingView()
    } else if (name === 'caregiver') {
      CaregiverView()
    } else if (name === 'guardian') {
      GuardianView()
    } else if (name === 'settings') {
      TilesSettingsView()
    } else if (name === 'gallery') {
      RenderPreview()
    }
  }

  build() {
    Stack() {
      // Living Light page gradient, drawn under the (transparent) status and navigation bars.
      Column()
        .width('100%')
        .height('100%')
        .linearGradient({ angle: this.pal().bgGradient.angle, colors: this.pal().bgGradient.colors })
        .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])

      Navigation(this.nav) {
        HomeView()
      }
      .navDestination(this.pageMap)
      .hideTitleBar(true)
      .hideToolBar(true)
      .mode(NavigationMode.Stack)
      .backgroundColor(Color.Transparent)
      .width('100%')
      .height('100%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.pal().bg)
  }

  pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }
}
