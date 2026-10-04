import { notificationManager } from '@kit.NotificationKit';
import { common, Want, wantAgent, WantAgent } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { PARAM_TILE_ID, PlatformKeys, TilesPlatform, TLog } from './TilesPlatform';

/** requestEnableNotification: user denied (the dialog cannot be shown again). */
const ERR_NOTIFICATION_DISABLED: number = 1600004;

/**
 * Notification Kit for Tiles: tile reminders ("Time for your 8:00 pills") and caregiver alerts
 * ("Halina took her 8:00 pills", "Guardian: Mum may be on a scam call"). Tapping a notification starts
 * EntryAbility with want parameter `tileId`, which EntryAbility exposes as AppStorage `tiles.openTileId`.
 *
 * Caregiver alerts are published on THIS phone and labelled "to <caregiver> (demo)": in the demo the
 * caregiver's phone is simulated; no message leaves the device.
 */
export class TileNotifications {
  static async isEnabled(): Promise<boolean> {
    try {
      return await notificationManager.isNotificationEnabled();
    } catch (e) {
      return false;
    }
  }

  /**
   * System "Allow notifications?" dialog if not enabled yet. When `userInitiated` and the user denied
   * before, opens the app's notification settings instead. Resolves to the enabled state.
   */
  static async requestPermission(userInitiated: boolean = false): Promise<boolean> {
    const ctx: common.UIAbilityContext | null = TilesPlatform.context();
    let enabled: boolean = await TileNotifications.isEnabled();
    if (enabled || ctx === null) {
      AppStorage.setOrCreate<boolean>(PlatformKeys.NOTIF_ENABLED, enabled);
      return enabled;
    }
    let code: number = 0;
    try {
      await notificationManager.requestEnableNotification(ctx);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      code = err.code;
      TLog.warn('requestEnableNotification failed: ' + err.code + ' ' + err.message);
    }
    enabled = await TileNotifications.isEnabled();
    if (!enabled && userInitiated && (code === ERR_NOTIFICATION_DISABLED || code === 0)) {
      try {
        await notificationManager.openNotificationSettings(ctx);
      } catch (e) {
        const err: BusinessError = e as BusinessError;
        TLog.warn('openNotificationSettings failed: ' + err.code);
      }
      enabled = await TileNotifications.isEnabled();
    }
    AppStorage.setOrCreate<boolean>(PlatformKeys.NOTIF_ENABLED, enabled);
    return enabled;
  }

  /** A reminder-style notification for a tile (e.g. pills). */
  static async notifyTile(tileId: string, title: string, text: string): Promise<boolean> {
    return TileNotifications.publish('tile:' + tileId, tileId, title, text, 'Tiles',
      notificationManager.SlotType.SERVICE_INFORMATION);
  }

  /**
   * Caregiver alert, e.g. caregiver 'Kasia', text 'Halina took her 8:00 pills'.
   * `key` de-duplicates (same key replaces the previous alert).
   */
  static async caregiverAlert(caregiver: string, title: string, text: string, tileId: string,
    key: string = ''): Promise<boolean> {
    const who: string = caregiver.length > 0 ? caregiver : 'caregiver';
    return TileNotifications.publish('care:' + (key.length > 0 ? key : tileId + ':' + title), tileId, title, text,
      'Tiles · sent to ' + who + ' (demo)', notificationManager.SlotType.SOCIAL_COMMUNICATION);
  }

  static async cancelForTile(tileId: string): Promise<void> {
    try {
      await notificationManager.cancel(TilesPlatform.idFor('tile:' + tileId), 'tiles');
    } catch (e) {
      // already gone
    }
  }

  private static async publish(key: string, tileId: string, title: string, text: string, additional: string,
    slot: notificationManager.SlotType): Promise<boolean> {
    const ctx: common.UIAbilityContext | null = TilesPlatform.context();
    if (ctx === null) {
      TLog.warn('notify before context set');
      return false;
    }
    try {
      const id: number = TilesPlatform.idFor(key);
      const want: Want = {
        bundleName: ctx.applicationInfo.name,
        abilityName: 'EntryAbility',
        parameters: {
          'tileId': tileId
        }
      };
      const info: wantAgent.WantAgentInfo = {
        wants: [want],
        actionType: wantAgent.OperationType.START_ABILITY,
        requestCode: id,
        actionFlags: [wantAgent.WantAgentFlags.UPDATE_PRESENT_FLAG]
      };
      const agent: WantAgent = await wantAgent.getWantAgent(info);
      const request: notificationManager.NotificationRequest = {
        id: id,
        notificationSlotType: slot,
        content: {
          notificationContentType: notificationManager.ContentType.NOTIFICATION_CONTENT_BASIC_TEXT,
          normal: {
            title: title,
            text: text,
            additionalText: additional
          }
        },
        wantAgent: agent,
        tapDismissed: true,
        label: 'tiles'
      };
      await notificationManager.publish(request);
      TLog.info('published notification ' + key + ' (' + PARAM_TILE_ID + '=' + tileId + ')');
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      TLog.warn('publish failed: ' + err.code + ' ' + err.message);
      return false;
    }
  }
}
