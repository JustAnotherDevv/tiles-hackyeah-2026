import { workScheduler, WorkSchedulerExtensionAbility } from '@kit.BackgroundTasksKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { BackgroundRefresh } from '../platform/BackgroundRefresh';
import { WidgetBridge } from '../platform/WidgetBridge';

const DOMAIN: number = 0x7A12;
const TAG: string = 'TilesWidget';

/**
 * Background Tasks Kit deferred-task callback. The system starts this extension in its own process when
 * the WorkScheduler conditions are met and gives it up to two minutes. It recomputes the Tiles widgets'
 * "Next up" from the clock and the tiles the app last published, so the home screen stays current while
 * the app is closed.
 * Manual trigger for testing: `hdc shell hidumper -s 1904 -a '-t <bundleName> RefreshWorkAbility'`.
 */
export default class RefreshWorkAbility extends WorkSchedulerExtensionAbility {
  onWorkStart(work: workScheduler.WorkInfo): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'RefreshWorkAbility start, work ' + work.workId);
    BackgroundRefresh.refreshOnce(this.context).then(() => {
      hilog.info(DOMAIN, TAG, '%{public}s', 'RefreshWorkAbility done');
    }).catch((e: Error) => {
      hilog.warn(DOMAIN, TAG, '%{public}s', 'RefreshWorkAbility failed: ' + e.message);
    }).finally(() => {
      WidgetBridge.release(this.context);
    });
  }

  onWorkStop(work: workScheduler.WorkInfo): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'RefreshWorkAbility stop, work ' + work.workId);
  }
}
