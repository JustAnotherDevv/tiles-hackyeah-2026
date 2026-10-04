import { workScheduler } from '@kit.BackgroundTasksKit';
import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { TilesWidgetData, WidgetBridge } from './WidgetBridge';

export const REFRESH_WORK_ID: number = 4242;
export const REFRESH_ABILITY: string = 'RefreshWorkAbility';
/** Repeat cycle requested from WorkScheduler; the system may run it less often (app activity group). */
export const REFRESH_CYCLE_MS: number = 30 * 60 * 1000;

const DOMAIN: number = 0x7A12;
const TAG: string = 'TilesWidget';

/**
 * Background Tasks Kit (WorkScheduler deferred task) + Form Kit: keeps the Tiles home-screen widgets
 * current while the app is closed. "Next up" depends on the clock (8:00 pills done -> 17:00 walk), so a
 * repeating deferred task (RefreshWorkAbility) and the widget's own onUpdateForm rebuild the widget data
 * from the tiles the app last published (WidgetBridge.publish) and push it to every placed widget.
 */
export class BackgroundRefresh {
  /**
   * Registers the repeating deferred task once. getWorkStatus resolves when the work id already exists
   * and rejects (9700004, "work does not exist") otherwise; only then is startWork called.
   */
  static schedule(ctx: common.Context): void {
    BackgroundRefresh.scheduleAsync(ctx).catch((e: Error) => {
      hilog.warn(DOMAIN, TAG, '%{public}s', 'Background refresh scheduling failed: ' + e.message);
    });
  }

  private static async scheduleAsync(ctx: common.Context): Promise<void> {
    try {
      const existing: workScheduler.WorkInfo = await workScheduler.getWorkStatus(REFRESH_WORK_ID);
      hilog.info(DOMAIN, TAG, '%{public}s', 'Background refresh already registered (work ' + existing.workId + ')');
      return;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      if (err.code !== 9700004) {
        hilog.warn(DOMAIN, TAG, '%{public}s', 'Background refresh status unknown: ' + err.code);
      }
    }
    const work: workScheduler.WorkInfo = {
      workId: REFRESH_WORK_ID,
      bundleName: ctx.applicationInfo.name,
      abilityName: REFRESH_ABILITY,
      networkType: workScheduler.NetworkType.NETWORK_TYPE_ANY,
      isRepeat: true,
      repeatCycleTime: REFRESH_CYCLE_MS,
      isPersisted: true
    };
    try {
      workScheduler.startWork(work);
      hilog.info(DOMAIN, TAG, '%{public}s', 'Background refresh scheduled every ' + (REFRESH_CYCLE_MS / 60000) + ' min');
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      hilog.warn(DOMAIN, TAG, '%{public}s', 'Background refresh not scheduled: ' + err.code + ' ' + err.message);
    }
  }

  /** Rebuilds the widget data from the last published tiles and pushes it to every placed widget. */
  static async refreshOnce(ctx: common.Context): Promise<TilesWidgetData> {
    const data: TilesWidgetData = WidgetBridge.load(ctx);
    await WidgetBridge.updateAll(data);
    hilog.info(DOMAIN, TAG, '%{public}s', 'Widgets refreshed, next up: ' + data.nId);
    return data;
  }

  /** @deprecated Aegis Pocket only; no-op kept so the old PocketStore compiles until cleanup removes it. */
  static saveKnownPending(ctx: common.Context, ids: string[]): void {
    return;
  }
}
