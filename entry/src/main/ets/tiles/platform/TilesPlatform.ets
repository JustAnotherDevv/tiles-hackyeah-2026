import { common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { UIContext } from '@kit.ArkUI';

/** AppStorage keys owned by the platform layer (read by the UI). */
export class PlatformKeys {
  /** Tile to open (set by notifications, reminders, the widget and TileActions 'open'). Consumers reset it to ''. */
  static readonly OPEN_TILE_ID: string = 'tiles.openTileId';
  /** Route to open for TileActions 'navigate' (e.g. 'guardian', 'caregiver', 'settings'). Consumers reset it to ''. */
  static readonly NAVIGATE: string = 'tiles.navigate';
  /** Text currently being "read aloud" ('' when idle). Drives the visual speaking state. */
  static readonly SPEAKING: string = 'tiles.speaking';
  /** Tile id that is currently being read aloud ('' when idle). */
  static readonly SPEAKING_TILE: string = 'tiles.speakingTileId';
  /** Notification Kit permission state. */
  static readonly NOTIF_ENABLED: string = 'tiles.notifEnabled';
  /** JSON map tileId -> reminderId of reminders scheduled through reminderAgentManager. */
  static readonly REMINDERS: string = 'tiles.reminders';
  /** Last platform event shown to the user (debug / caregiver feed), e.g. "Reminder set for 8:00". */
  static readonly LAST_EVENT: string = 'tiles.lastEvent';
}

/** Want parameter carrying the tile id (notifications, reminders, the home-screen widget). */
export const PARAM_TILE_ID: string = 'tileId';

const DOMAIN: number = 0x7A11;
const TAG: string = 'TilesPlatform';

export class TLog {
  static info(msg: string): void {
    hilog.info(DOMAIN, TAG, '%{public}s', msg);
  }

  static warn(msg: string): void {
    hilog.warn(DOMAIN, TAG, '%{public}s', msg);
  }
}

/**
 * Holds the ability context and UI context for the non-UI platform services (set by EntryAbility).
 * Services degrade gracefully (log + no-op) while these are not set yet.
 */
export class TilesPlatform {
  private static ctx: common.UIAbilityContext | null = null;
  private static ui: UIContext | null = null;

  static setContext(ctx: common.UIAbilityContext): void {
    TilesPlatform.ctx = ctx;
  }

  static setUIContext(ui: UIContext): void {
    TilesPlatform.ui = ui;
  }

  static context(): common.UIAbilityContext | null {
    return TilesPlatform.ctx;
  }

  static uiContext(): UIContext | null {
    return TilesPlatform.ui;
  }

  static bundleName(): string {
    const c: common.UIAbilityContext | null = TilesPlatform.ctx;
    return c === null ? '' : c.applicationInfo.name;
  }

  /** Short on-screen confirmation of a platform action. Never throws. */
  static toast(message: string): void {
    TLog.info('toast: ' + message);
    AppStorage.setOrCreate<string>(PlatformKeys.LAST_EVENT, message);
    const ui: UIContext | null = TilesPlatform.ui;
    if (ui === null) {
      return;
    }
    try {
      ui.getPromptAction().showToast({ message: message, duration: 2500 });
    } catch (e) {
      TLog.warn('toast failed: ' + JSON.stringify(e));
    }
  }

  /** Stable positive 31-bit id for a string (notification ids). */
  static idFor(key: string): number {
    let h: number = 7;
    for (let i = 0; i < key.length; i++) {
      h = (h * 31 + key.charCodeAt(i)) % 1000000007;
    }
    return h % 2000000000;
  }
}
