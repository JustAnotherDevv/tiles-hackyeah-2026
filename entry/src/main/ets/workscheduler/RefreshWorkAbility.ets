import { workScheduler, WorkSchedulerExtensionAbility } from '@kit.BackgroundTasksKit';
import { BackgroundRefresh } from '../platform/BackgroundRefresh';
import { PocketPrefs } from '../platform/SettingsStore';
import { Log } from '../common/Format';

/**
 * Background Tasks Kit deferred-task callback. The system starts this extension in its own process
 * when the WorkScheduler conditions are met (network available, cycle elapsed) and gives it up to
 * two minutes. It refreshes the widget snapshot from the Aegis gateway (live mode) and notifies about
 * new pending approvals while the app itself is not running.
 * Manual trigger for testing: `hdc shell hidumper -s 1904 -a '-t com.hackyeah.aegispocket RefreshWorkAbility'`.
 */
export default class RefreshWorkAbility extends WorkSchedulerExtensionAbility {
  onWorkStart(work: workScheduler.WorkInfo): void {
    Log.info('RefreshWorkAbility start, work ' + work.workId);
    BackgroundRefresh.refreshOnce(this.context, true).then(() => {
      Log.info('RefreshWorkAbility done');
    }).catch((e: Error) => {
      Log.warn('RefreshWorkAbility failed: ' + e.message);
    }).finally(() => {
      // GSKV: release the cached instance before this short-lived process exits (ArkData recommendation).
      PocketPrefs.release(this.context);
    });
  }

  onWorkStop(work: workScheduler.WorkInfo): void {
    Log.info('RefreshWorkAbility stop, work ' + work.workId);
  }
}
