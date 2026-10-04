import { formBindingData, FormExtensionAbility, formInfo } from '@kit.FormKit';
import { Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { TilesWidgetData, WidgetBridge } from '../platform/WidgetBridge';
import { BackgroundRefresh } from '../platform/BackgroundRefresh';

const DOMAIN: number = 0x7A12;
const TAG: string = 'TilesWidget';

/**
 * Form Kit provider for the Tiles home-screen widgets (file name kept for the module.json5 srcEntry):
 * - "Next up" 2x2: the next reminder / pills tile, tap opens it in the app (want param tileId).
 * - "My tiles" 2x4: the top 3 pinned tiles as colorful chips.
 * - "Big buttons" 4x4 (senior): Call / Pills / SOS.
 * onAddForm builds the data from the tiles the app last published (WidgetBridge.publish); with none it
 * shows "Open Tiles". onUpdateForm (every 30 min, form_config.json) recomputes "Next up" from the clock.
 * A WorkScheduler deferred task (workscheduler/RefreshWorkAbility.ets) does the same while the app is closed.
 */
export default class TilesFormAbility extends FormExtensionAbility {
  onAddForm(want: Want): formBindingData.FormBindingData {
    const data: TilesWidgetData = WidgetBridge.load(this.context);
    const name: Object | undefined = want.parameters?.[formInfo.FormParam.NAME_KEY];
    hilog.info(DOMAIN, TAG, '%{public}s', 'Widget added: ' + JSON.stringify(name ?? '') + ' hasData ' + data.hasData);
    return WidgetBridge.bindingData(data);
  }

  onCastToNormalForm(formId: string): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'Widget cast to normal: ' + formId);
  }

  onUpdateForm(formId: string): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'Widget update requested: ' + formId);
    BackgroundRefresh.refreshOnce(this.context).catch((e: Error) => {
      hilog.warn(DOMAIN, TAG, '%{public}s', 'Widget refresh failed: ' + e.message);
    });
  }

  onFormEvent(formId: string, message: string): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'Widget event ' + formId + ': ' + message);
  }

  onRemoveForm(formId: string): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'Widget removed: ' + formId);
  }

  onAcquireFormState(want: Want): formInfo.FormState {
    return formInfo.FormState.READY;
  }
}
