import { workScheduler } from '@kit.BackgroundTasksKit';
import { formInfo, formProvider } from '@kit.FormKit';
import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { ApprovalItem, PostureStats } from '../model/Models';
import { ApprovalsPage } from '../data/ApprovalsRepository';
import { LiveRepository } from '../data/LiveRepository';
import { AppSettings, PREFS_NAME, SettingsStore } from './SettingsStore';
import { WidgetBridge, WidgetSnapshot } from './WidgetBridge';
import { NotificationService } from './NotificationService';
import { Log } from '../common/Format';

export const REFRESH_WORK_ID: number = 4242;
export const REFRESH_ABILITY: string = 'RefreshWorkAbility';
/** Repeat cycle requested from WorkScheduler; the system may run it less often (app activity group). */
export const REFRESH_CYCLE_MS: number = 2 * 60 * 60 * 1000;
const KNOWN_PENDING_KEY: string = 'knownPendingIds';
const MAX_BG_NOTIFICATIONS: number = 3;

/**
 * Background Tasks Kit (WorkScheduler deferred task) + Form Kit: keeps the home-screen widget's
 * pending count current and raises notifications for new requests while the app is closed.
 *
 * - schedule(): registers a repeating, network-gated deferred task (ordinary apps, no permission).
 * - refreshOnce(): run by RefreshWorkAbility (and by the widget's own onUpdateForm). In live mode it
 *   polls the Aegis gateway, saves the snapshot, updates every placed widget and notifies about
 *   pending requests the user has not seen yet. In mock mode there is no gateway, so it re-sends the
 *   last snapshot the app saved.
 */
export class BackgroundRefresh {
  static schedule(ctx: common.Context): void {
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
      Log.info('Background refresh scheduled every ' + (REFRESH_CYCLE_MS / 60000) + ' min');
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      // 9700004/9700005 are also returned when the same work id is already registered.
      Log.info('Background refresh not (re)scheduled: ' + err.code + ' ' + err.message);
    }
  }

  /** Fetches the gateway (live mode) or reloads the last snapshot (mock mode) and pushes it to widgets. */
  static async refreshOnce(ctx: common.Context, notify: boolean): Promise<WidgetSnapshot> {
    let snap: WidgetSnapshot = WidgetBridge.loadSnapshot(ctx);
    const settings: AppSettings = SettingsStore.load(ctx);
    if (settings.mode === 'live') {
      try {
        const repo: LiveRepository = new LiveRepository(settings.baseUrl);
        const stats: PostureStats = await repo.getStats(settings.persona);
        const page: ApprovalsPage = await repo.listApprovals(settings.persona);
        const pending: ApprovalItem[] = [];
        for (const it of page.items) {
          if (it.status === 'pending') {
            pending.push(it);
          }
        }
        let top: string = '';
        if (pending.length > 0) {
          const first: ApprovalItem = pending[0];
          top = first.amountUsd > 0 ? first.title + ' ($' + first.amountUsd.toFixed(0) + ')' : first.title;
        }
        stats.source = 'live';
        snap = WidgetBridge.build(stats, page.pending, top);
        WidgetBridge.saveSnapshot(ctx, snap);
        if (notify) {
          await BackgroundRefresh.notifyUnseen(ctx, pending);
        }
      } catch (e) {
        Log.warn('Background live refresh failed, keeping the last snapshot');
      }
    }
    await BackgroundRefresh.updateAllForms(snap);
    return snap;
  }

  /** The app records which pending ids the user already saw, so background runs only notify new ones. */
  static saveKnownPending(ctx: common.Context, ids: string[]): void {
    try {
      const p: preferences.Preferences = preferences.getPreferencesSync(ctx, { name: PREFS_NAME });
      p.putSync(KNOWN_PENDING_KEY, ids.join(','));
      p.flush().catch((e: Error) => {
        Log.warn('known ids flush failed: ' + e.message);
      });
    } catch (e) {
      Log.warn('known ids save failed: ' + JSON.stringify(e));
    }
  }

  private static loadKnownPending(ctx: common.Context): string[] {
    try {
      preferences.removePreferencesFromCacheSync(ctx, PREFS_NAME);
      const p: preferences.Preferences = preferences.getPreferencesSync(ctx, { name: PREFS_NAME });
      const raw: string = p.getSync(KNOWN_PENDING_KEY, '') as string;
      return raw.length > 0 ? raw.split(',') : [];
    } catch (e) {
      return [];
    }
  }

  private static async notifyUnseen(ctx: common.Context, pending: ApprovalItem[]): Promise<void> {
    const known: string[] = BackgroundRefresh.loadKnownPending(ctx);
    const ids: string[] = [];
    let sent: number = 0;
    for (const it of pending) {
      ids.push(it.id);
      if (known.indexOf(it.id) < 0 && sent < MAX_BG_NOTIFICATIONS) {
        await NotificationService.notifyApproval(ctx, it);
        sent++;
      }
    }
    BackgroundRefresh.saveKnownPending(ctx, ids);
    if (sent > 0) {
      Log.info('Background refresh notified ' + sent + ' new request(s)');
    }
  }

  private static async updateAllForms(snap: WidgetSnapshot): Promise<void> {
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
      Log.warn('getPublishedRunningFormInfos failed: ' + err.code);
    }
  }
}
