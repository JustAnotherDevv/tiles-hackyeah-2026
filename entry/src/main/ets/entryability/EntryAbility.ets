import { AbilityConstant, Configuration, ConfigurationConstant, UIAbility, Want } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { PARAM_TILE_ID, PlatformKeys, TilesPlatform, TLog } from '../tiles/platform/TilesPlatform';
import { TileNotifications } from '../tiles/platform/TileNotifications';
import { TileStore } from '../tiles/data/TileStore';
import { PlatformSelfTest } from '../tiles/platform/PlatformSelfTest';

/** Warm light / dark page backgrounds (TilesTheme.palette bg). */
const BG_LIGHT: string = '#F6F3EE';
const BG_DARK: string = '#14161C';

export default class EntryAbility extends UIAbility {
  private windowStage: window.WindowStage | null = null;

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    try {
      // Tiles follows the system light / dark setting.
      this.context.getApplicationContext().setColorMode(ConfigurationConstant.ColorMode.COLOR_MODE_NOT_SET);
    } catch (err) {
      TLog.warn('Failed to set colorMode: ' + JSON.stringify(err));
    }
    TilesPlatform.setContext(this.context);
    TileStore.get().init(this.context);
    AppStorage.setOrCreate<string>(PlatformKeys.OPEN_TILE_ID, '');
    AppStorage.setOrCreate<string>(PlatformKeys.NAVIGATE, '');
    AppStorage.setOrCreate<string>(PlatformKeys.SPEAKING, '');
    AppStorage.setOrCreate<string>(PlatformKeys.SPEAKING_TILE, '');
    this.handleWant(want);
    TLog.info('Ability onCreate');
  }

  /** A notification, reminder or the widget (postCardAction router) re-opens the running app. */
  onNewWant(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    this.handleWant(want);
  }

  onDestroy(): void {
    TLog.info('Ability onDestroy');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    this.windowStage = windowStage;
    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        TLog.warn('Failed to load the content: ' + JSON.stringify(err));
        return;
      }
      try {
        TilesPlatform.setUIContext(windowStage.getMainWindowSync().getUIContext());
      } catch (e) {
        TLog.warn('getUIContext failed: ' + JSON.stringify(e));
      }
      this.styleWindow();
      // Ask once for notification permission (system dialog): reminders and caregiver alerts need it.
      TileNotifications.requestPermission(false).then((ok: boolean) => {
        TLog.info('Notifications enabled: ' + ok);
      });
    });
  }

  onConfigurationUpdate(newConfig: Configuration): void {
    this.styleWindow();
  }

  onWindowStageDestroy(): void {
    this.windowStage = null;
  }

  onForeground(): void {
    TileNotifications.isEnabled().then((ok: boolean) => {
      AppStorage.setOrCreate<boolean>(PlatformKeys.NOTIF_ENABLED, ok);
    });
  }

  onBackground(): void {
    TLog.info('Ability onBackground');
  }

  private isDark(): boolean {
    try {
      return this.context.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    } catch (e) {
      return false;
    }
  }

  private styleWindow(): void {
    const stage: window.WindowStage | null = this.windowStage;
    if (stage === null) {
      return;
    }
    try {
      const dark: boolean = this.isDark();
      const bg: string = dark ? BG_DARK : BG_LIGHT;
      const fg: string = dark ? '#F4F1EC' : '#1C2230';
      const win: window.Window = stage.getMainWindowSync();
      win.setWindowBackgroundColor(bg);
      win.setWindowSystemBarProperties({
        statusBarColor: bg,
        statusBarContentColor: fg,
        navigationBarColor: bg,
        navigationBarContentColor: fg
      }).catch((e: Error) => {
        TLog.warn('system bar style failed: ' + e.message);
      });
    } catch (e) {
      TLog.warn('window styling failed: ' + JSON.stringify(e));
    }
  }

  /**
   * Want parameter `tileId` (notification / reminder WantAgent, or the widget's postCardAction 'router'
   * whose params arrive as a JSON string in want.parameters.params) -> AppStorage `tiles.openTileId`.
   */
  private handleWant(want: Want): void {
    const params: Record<string, Object> | undefined = want.parameters;
    if (params === undefined) {
      return;
    }
    // Developer self-test of the platform layer (aa start ... --ps tilesDebug notify|remind|action:<id>:<kind>:<arg>).
    const debug: Object | undefined = params['tilesDebug'];
    if (typeof debug === 'string' && (debug as string).length > 0) {
      const cmd: string = debug as string;
      setTimeout(() => PlatformSelfTest.run(cmd), 1500);
    }
    let tileId: Object | undefined = params[PARAM_TILE_ID];
    const cardParams: Object | undefined = params['params'];
    if (tileId === undefined && typeof cardParams === 'string') {
      try {
        const parsed: Record<string, Object> = JSON.parse(cardParams as string) as Record<string, Object>;
        tileId = parsed[PARAM_TILE_ID];
      } catch (e) {
        TLog.warn('Bad widget params');
      }
    }
    if (typeof tileId === 'string' && (tileId as string).length > 0) {
      TLog.info('open tile from want: ' + (tileId as string));
      // Reset first so opening the same tile twice still notifies @StorageLink watchers.
      AppStorage.setOrCreate<string>(PlatformKeys.OPEN_TILE_ID, '');
      AppStorage.setOrCreate<string>(PlatformKeys.OPEN_TILE_ID, tileId as string);
    }
  }
}
