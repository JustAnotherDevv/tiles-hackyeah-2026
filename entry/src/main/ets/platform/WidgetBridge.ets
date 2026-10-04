import { formBindingData, formInfo, formProvider } from '@kit.FormKit';
import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { PostureStats, budgetLeftPctOf } from '../model/Models';
import { Fmt, Log } from '../common/Format';
import { PREFS_NAME } from './SettingsStore';

/**
 * Data bound to the home-screen service widgets. Field names must match the
 * @LocalStorageProp keys in widget/pages/PostureCard.ets and PostureWideCard.ets.
 */
export class WidgetSnapshot {
  pending: number = 3;
  blocked: number = 37;
  redacted: number = 212;
  budgetLeftPct: number = 63;
  spendToday: string = '$148';
  topRequest: string = 'Buy MarketPulse Pro ($50)';
  mode: string = 'MOCK';
  updated: string = '--:--';
}

/**
 * Form Kit bridge: keeps the latest posture snapshot in Preferences (shared with the
 * FormExtensionAbility process) and pushes it to every placed widget with formProvider.updateForm.
 */
export class WidgetBridge {
  private static lastJson: string = '';

  static build(stats: PostureStats, pending: number, topRequest: string): WidgetSnapshot {
    const s: WidgetSnapshot = new WidgetSnapshot();
    s.pending = pending;
    s.blocked = stats.blocked;
    s.redacted = stats.redacted;
    s.budgetLeftPct = Math.round(budgetLeftPctOf(stats));
    s.spendToday = Fmt.usd(stats.spendTodayUsd);
    s.topRequest = topRequest.length > 0 ? topRequest : 'No pending requests';
    s.mode = stats.source === 'live' ? 'LIVE' : 'MOCK';
    const d: Date = new Date();
    s.updated = Fmt.pad2(d.getHours()) + ':' + Fmt.pad2(d.getMinutes());
    return s;
  }

  static saveSnapshot(ctx: common.Context, snap: WidgetSnapshot): void {
    try {
      const p: preferences.Preferences = preferences.getPreferencesSync(ctx, { name: PREFS_NAME });
      p.putSync('widgetSnapshot', JSON.stringify(snap));
      p.flush().catch((e: Error) => {
        Log.warn('snapshot flush failed: ' + e.message);
      });
    } catch (e) {
      Log.warn('snapshot save failed: ' + JSON.stringify(e));
    }
  }

  /** Reads the snapshot written by the app (fresh from disk, the extension runs in another process). */
  static loadSnapshot(ctx: common.Context): WidgetSnapshot {
    const out: WidgetSnapshot = new WidgetSnapshot();
    try {
      preferences.removePreferencesFromCacheSync(ctx, PREFS_NAME);
      const p: preferences.Preferences = preferences.getPreferencesSync(ctx, { name: PREFS_NAME });
      const json: string = p.getSync('widgetSnapshot', '') as string;
      if (json.length > 0) {
        const o: WidgetSnapshot = JSON.parse(json) as WidgetSnapshot;
        out.pending = o.pending ?? out.pending;
        out.blocked = o.blocked ?? out.blocked;
        out.redacted = o.redacted ?? out.redacted;
        out.budgetLeftPct = o.budgetLeftPct ?? out.budgetLeftPct;
        out.spendToday = o.spendToday ?? out.spendToday;
        out.topRequest = o.topRequest ?? out.topRequest;
        out.mode = o.mode ?? out.mode;
        out.updated = o.updated ?? out.updated;
      }
    } catch (e) {
      Log.warn('snapshot load failed: ' + JSON.stringify(e));
    }
    return out;
  }

  static bindingData(snap: WidgetSnapshot): formBindingData.FormBindingData {
    return formBindingData.createFormBindingData(snap);
  }

  /** Persists the snapshot and updates all placed widgets of this app (skips if unchanged). */
  static async push(ctx: common.Context, snap: WidgetSnapshot): Promise<void> {
    const json: string = JSON.stringify(snap);
    if (json === WidgetBridge.lastJson) {
      return;
    }
    WidgetBridge.lastJson = json;
    WidgetBridge.saveSnapshot(ctx, snap);
    try {
      const forms: formInfo.RunningFormInfo[] = await formProvider.getPublishedRunningFormInfos();
      for (const f of forms) {
        try {
          await formProvider.updateForm(f.formId, WidgetBridge.bindingData(snap));
        } catch (e) {
          const err: BusinessError = e as BusinessError;
          Log.warn('updateForm ' + f.formId + ' failed: ' + err.code);
        }
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.warn('getPublishedRunningFormInfos failed: ' + err.code + ' ' + err.message);
    }
  }
}
