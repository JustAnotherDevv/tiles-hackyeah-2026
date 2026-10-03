import { formBindingData, FormExtensionAbility, formInfo, formProvider } from '@kit.FormKit';
import { Want } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { WidgetBridge, WidgetSnapshot } from '../platform/WidgetBridge';
import { AppSettings, SettingsStore } from '../platform/SettingsStore';
import { LiveRepository } from '../data/LiveRepository';
import { ApprovalsPage } from '../data/ApprovalsRepository';
import { ApprovalItem, PostureStats } from '../model/Models';
import { Log } from '../common/Format';

/**
 * Form Kit provider for the "AI posture" home-screen widgets (2x2 and 2x4).
 * - onAddForm: returns the last snapshot the app saved (mock defaults on first install).
 * - onUpdateForm (every 30 min, `updateDuration: 1` in form_config.json): in live mode it polls the
 *   gateway (`/api/stats`, `/api/approvals`); otherwise it re-sends the last snapshot.
 * The app also pushes fresh data on every poll via formProvider.updateForm (WidgetBridge.push).
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
    let snap: WidgetSnapshot = WidgetBridge.loadSnapshot(this.context);
    const settings: AppSettings = SettingsStore.load(this.context);
    if (settings.mode === 'live') {
      try {
        const repo: LiveRepository = new LiveRepository(settings.baseUrl);
        const stats: PostureStats = await repo.getStats(settings.persona);
        const page: ApprovalsPage = await repo.listApprovals(settings.persona);
        let top: string = '';
        for (const it of page.items) {
          if (it.status === 'pending') {
            top = WidgetBridgeHelpers.titleOf(it);
            break;
          }
        }
        snap = WidgetBridge.build(stats, page.pending, top);
        WidgetBridge.saveSnapshot(this.context, snap);
      } catch (e) {
        Log.warn('Widget live refresh failed, keeping last snapshot');
      }
    }
    try {
      await formProvider.updateForm(formId, WidgetBridge.bindingData(snap));
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.warn('updateForm failed: ' + err.code);
    }
  }
}

class WidgetBridgeHelpers {
  static titleOf(it: ApprovalItem): string {
    if (it.amountUsd > 0) {
      return it.title + ' ($' + it.amountUsd.toFixed(0) + ')';
    }
    return it.title;
  }
}
