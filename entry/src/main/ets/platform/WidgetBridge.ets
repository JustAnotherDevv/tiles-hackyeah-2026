import { formBindingData, formInfo, formProvider } from '@kit.FormKit';
import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { PostureStats } from '../model/Models';
import { Fmt, Log } from '../common/Format';
import { PocketPrefs, SettingsStore } from './SettingsStore';
import {
  STORE_SHARED,
  WidgetSnapshot,
  buildSnapshot,
  emptySnapshot,
  parseSnapshot,
  shouldSaveSnapshot,
  snapshotKey
} from './PocketPersist';

export { WidgetSnapshot };

const SNAPSHOT_KEY: string = 'widgetSnapshot';

/**
 * Form Kit bridge: keeps the latest posture snapshot in Preferences (shared with the
 * FormExtensionAbility and WorkScheduler processes, see PocketPrefs) and pushes it to every placed
 * widget with formProvider.updateForm. With no synced data the widget shows "—", never sample numbers.
 */
export class WidgetBridge {
  /** JSON of the last snapshot that reached every placed widget (or when none is placed). */
  private static lastJson: string = '';
  private static lastSavedKey: string = '';
  private static lastSavedMs: number = 0;

  /** `failed`: the live fetch behind these stats failed, so the widget is labelled OFFLINE. */
  static build(stats: PostureStats, pending: number, topRequest: string, failed: boolean = false): WidgetSnapshot {
    return buildSnapshot(stats, pending, topRequest, Fmt.usd(stats.spendTodayUsd), failed, Date.now());
  }

  static saveSnapshot(ctx: common.Context, snap: WidgetSnapshot): void {
    try {
      const p: preferences.Preferences = PocketPrefs.open(ctx, STORE_SHARED, false);
      p.putSync(SNAPSHOT_KEY, JSON.stringify(snap));
      PocketPrefs.commit(p, 'snapshot');
    } catch (e) {
      Log.warn('snapshot save failed: ' + JSON.stringify(e));
    }
  }

  /**
   * Reads the snapshot written by any process (fresh from disk). Missing, corrupt or other-mode data
   * yields the empty snapshot labelled with the current settings mode.
   */
  static loadSnapshot(ctx: common.Context, settingsMode: string = ''): WidgetSnapshot {
    const mode: string = settingsMode.length > 0 ? settingsMode : SettingsStore.load(ctx).mode;
    try {
      const p: preferences.Preferences = PocketPrefs.open(ctx, STORE_SHARED, true);
      const v: preferences.ValueType = p.getSync(SNAPSHOT_KEY, '');
      return parseSnapshot(typeof v === 'string' ? v : '', mode);
    } catch (e) {
      Log.warn('snapshot load failed: ' + JSON.stringify(e));
    }
    return emptySnapshot(mode);
  }

  static bindingData(snap: WidgetSnapshot): formBindingData.FormBindingData {
    return formBindingData.createFormBindingData(snap);
  }

  /**
   * Updates every placed widget of this app. Returns true when there is no widget or at least one
   * update succeeded; false when nothing could be updated (the caller may retry with the same data).
   */
  static async updateAll(snap: WidgetSnapshot): Promise<boolean> {
    try {
      const forms: formInfo.RunningFormInfo[] = await formProvider.getPublishedRunningFormInfos();
      if (forms.length === 0) {
        return true;
      }
      let ok: number = 0;
      for (const f of forms) {
        try {
          await formProvider.updateForm(f.formId, WidgetBridge.bindingData(snap));
          ok++;
        } catch (e) {
          const err: BusinessError = e as BusinessError;
          Log.warn('updateForm ' + f.formId + ' failed: ' + err.code);
        }
      }
      return ok > 0;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.warn('getPublishedRunningFormInfos failed: ' + err.code + ' ' + err.message);
    }
    return false;
  }

  /**
   * App side: persists the snapshot (throttled: at once when pending/mode/top request change,
   * otherwise at most once a minute) and updates all placed widgets (skipped if unchanged; a failed
   * update is retried on the next call).
   */
  static async push(ctx: common.Context, snap: WidgetSnapshot): Promise<void> {
    const json: string = JSON.stringify(snap);
    if (json === WidgetBridge.lastJson) {
      return;
    }
    const key: string = snapshotKey(snap);
    const now: number = Date.now();
    if (shouldSaveSnapshot(WidgetBridge.lastSavedKey, key, WidgetBridge.lastSavedMs, now)) {
      WidgetBridge.lastSavedKey = key;
      WidgetBridge.lastSavedMs = now;
      WidgetBridge.saveSnapshot(ctx, snap);
    }
    if (await WidgetBridge.updateAll(snap)) {
      WidgetBridge.lastJson = json;
    }
  }
}
