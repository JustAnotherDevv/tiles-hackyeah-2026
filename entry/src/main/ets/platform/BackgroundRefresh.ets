import { workScheduler } from '@kit.BackgroundTasksKit';
import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { ApprovalItem, PostureStats } from '../model/Models';
import { ApprovalsPage } from '../data/ApprovalsRepository';
import { LiveRepository } from '../data/LiveRepository';
import { AppSettings, PocketPrefs, SettingsStore } from './SettingsStore';
import { WidgetBridge, WidgetSnapshot } from './WidgetBridge';
import { STORE_SHARED, markOffline, parseIdList } from './PocketPersist';
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
  /**
   * Registers the repeating deferred task once. getWorkStatus resolves when the work id already exists
   * and rejects (9700004, "work does not exist") otherwise; only then is startWork called, so a
   * startWork error is a real failure (e.g. 9700005: limit of 10 works per uid, cycle < 20 min).
   */
  static schedule(ctx: common.Context): void {
    BackgroundRefresh.scheduleAsync(ctx).catch((e: Error) => {
      Log.warn('Background refresh scheduling failed: ' + e.message);
    });
  }

  private static async scheduleAsync(ctx: common.Context): Promise<void> {
    try {
      const existing: workScheduler.WorkInfo = await workScheduler.getWorkStatus(REFRESH_WORK_ID);
      Log.info('Background refresh already registered (work ' + existing.workId + ')');
      return;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      if (err.code !== 9700004) {
        Log.warn('Background refresh status unknown: ' + err.code + ' ' + err.message);
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
      Log.info('Background refresh scheduled every ' + (REFRESH_CYCLE_MS / 60000) + ' min');
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.warn('Background refresh not scheduled: ' + err.code + ' ' + err.message);
    }
  }

  /** Fetches the gateway (live mode) or reloads the last snapshot (mock mode) and pushes it to widgets. */
  static async refreshOnce(ctx: common.Context, notify: boolean): Promise<WidgetSnapshot> {
    const settings: AppSettings = SettingsStore.load(ctx);
    let snap: WidgetSnapshot = WidgetBridge.loadSnapshot(ctx, settings.mode);
    let fresh: ApprovalItem[] | null = null;
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
        fresh = pending;
      } catch (e) {
        // Keep the last good numbers but label them OFFLINE; never present them as a fresh LIVE count.
        Log.warn('Background live refresh failed, widget marked OFFLINE');
        snap = markOffline(snap);
        WidgetBridge.saveSnapshot(ctx, snap);
      }
    }
    await WidgetBridge.updateAll(snap);
    if (notify && fresh !== null) {
      try {
        await BackgroundRefresh.notifyUnseen(ctx, fresh);
      } catch (e) {
        Log.warn('Background notify failed: ' + JSON.stringify(e));
      }
    }
    return snap;
  }

  /** The app records which pending ids the user already saw, so background runs only notify new ones. */
  static saveKnownPending(ctx: common.Context, ids: string[]): void {
    try {
      const p: preferences.Preferences = PocketPrefs.open(ctx, STORE_SHARED, false);
      p.putSync(KNOWN_PENDING_KEY, ids.join(','));
      PocketPrefs.commit(p, 'known ids');
    } catch (e) {
      Log.warn('known ids save failed: ' + JSON.stringify(e));
    }
  }

  private static loadKnownPending(ctx: common.Context): string[] {
    try {
      const p: preferences.Preferences = PocketPrefs.open(ctx, STORE_SHARED, true);
      const raw: preferences.ValueType = p.getSync(KNOWN_PENDING_KEY, '');
      return parseIdList(typeof raw === 'string' ? raw : '');
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
}
