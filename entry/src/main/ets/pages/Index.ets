import { common, ConfigurationConstant } from '@kit.AbilityKit';
import { Profile, TileSpec } from '../tiles/model/Tile';
import { K_ONBOARDED, K_PROFILE, TileStore } from '../tiles/data/TileStore';
import { TilesTheme } from '../tiles/theme/TilesTheme';
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
  @StorageProp(K_DARK) dark: boolean = false;
  @StorageProp(PlatformKeys.OPEN_TILE_ID) @Watch('onOpenTile') openTileId: string = '';
  @StorageProp(PlatformKeys.NAVIGATE) @Watch('onNavigate') navigateTo: string = '';

  aboutToAppear(): void {
    this.syncDark();
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
    Navigation(this.nav) {
      HomeView()
    }
    .navDestination(this.pageMap)
    .hideTitleBar(true)
    .hideToolBar(true)
    .mode(NavigationMode.Stack)
    .backgroundColor(TilesTheme.palette(this.dark, this.profile.highContrast).bg)
    .width('100%')
    .height('100%')
  }
}
