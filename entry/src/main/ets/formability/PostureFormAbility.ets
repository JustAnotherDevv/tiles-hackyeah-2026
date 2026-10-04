import { formBindingData, FormExtensionAbility, formInfo } from '@kit.FormKit';
import { Want } from '@kit.AbilityKit';
import { WidgetBridge, WidgetSnapshot } from '../platform/WidgetBridge';
import { BackgroundRefresh } from '../platform/BackgroundRefresh';
import { Log } from '../common/Format';

/**
 * Form Kit provider for the "AI posture" home-screen widgets (2x2 and 2x4).
 * - onAddForm: returns the last snapshot the app saved (mock defaults on first install).
 * - onUpdateForm (every 30 min, `updateDuration: 1` in form_config.json): in live mode it polls the
 *   gateway (`/api/stats`, `/api/approvals`); otherwise it re-sends the last snapshot.
 * The app also pushes fresh data on every poll via formProvider.updateForm (WidgetBridge.push), and a
 * WorkScheduler deferred task (workscheduler/RefreshWorkAbility.ets) refreshes it while the app is closed.
 */
export default class PostureFormAbility extends FormExtensionAbility {
  onAddForm(want: Want): formBindingData.FormBindingData {
    const snap: WidgetSnapshot = WidgetBridge.loadSnapshot(this.context);
    Log.info('Widget added: ' + JSON.stringify(want.parameters?.[formInfo.FormParam.NAME_KEY] ?? ''));
    return WidgetBridge.bindingData(snap);
  }

  onCastToNormalForm(formId: string): void {
    Log.info('Widget cast to normal: ' + formId);
  }

  onUpdateForm(formId: string): void {
    this.refresh(formId).catch((e: Error) => {
      Log.warn('Widget refresh failed: ' + e.message);
    });
  }

  onFormEvent(formId: string, message: string): void {
    Log.info('Widget event ' + formId + ': ' + message);
  }

  onRemoveForm(formId: string): void {
    Log.info('Widget removed: ' + formId);
  }

  onAcquireFormState(want: Want): formInfo.FormState {
    return formInfo.FormState.READY;
  }

  private async refresh(formId: string): Promise<void> {
    // Shared with the WorkScheduler deferred task (platform/BackgroundRefresh.ets): live mode polls the
    // gateway, mock mode re-sends the last snapshot; every placed widget (including formId) is updated.
    Log.info('Widget update requested: ' + formId);
    await BackgroundRefresh.refreshOnce(this.context, false);
  }
}
