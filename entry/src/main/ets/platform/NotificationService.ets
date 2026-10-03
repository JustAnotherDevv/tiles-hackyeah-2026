import { notificationManager } from '@kit.NotificationKit';
import { common, Want, wantAgent, WantAgent } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { ApprovalItem } from '../model/Models';
import { Fmt, Log } from '../common/Format';

export const PARAM_APPROVAL_ID: string = 'aegisApprovalId';
export const PARAM_TARGET: string = 'aegisTarget';

/**
 * Notification Kit integration: asks the user to enable notifications (system dialog) and
 * publishes a local notification for each new approval request. Tapping it starts
 * EntryAbility through a WantAgent carrying the approval id, which opens the detail screen.
 */
export class NotificationService {
  static async isEnabled(): Promise<boolean> {
    try {
      return await notificationManager.isNotificationEnabled();
    } catch (e) {
      return false;
    }
  }

  /** Shows the system "Allow notifications?" dialog if they are not enabled yet. */
  static async requestPermission(ctx: common.UIAbilityContext): Promise<boolean> {
    try {
      const enabled: boolean = await notificationManager.isNotificationEnabled();
      if (enabled) {
        return true;
      }
      await notificationManager.requestEnableNotification(ctx);
      return await notificationManager.isNotificationEnabled();
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.warn('requestEnableNotification failed: ' + err.code + ' ' + err.message);
      return false;
    }
  }

  static async notifyApproval(ctx: common.Context, item: ApprovalItem): Promise<void> {
    const id: number = NotificationService.idFor(item.id);
    try {
      const want: Want = {
        bundleName: ctx.applicationInfo.name,
        abilityName: 'EntryAbility',
        parameters: {
          'aegisApprovalId': item.id
        }
      };
      const info: wantAgent.WantAgentInfo = {
        wants: [want],
        actionType: wantAgent.OperationType.START_ABILITY,
        requestCode: id,
        actionFlags: [wantAgent.WantAgentFlags.UPDATE_PRESENT_FLAG]
      };
      const agent: WantAgent = await wantAgent.getWantAgent(info);
      const who: string = item.requesterAgent.length > 0 ? item.requesterAgent : item.requesterMember;
      let text: string = who + ' wants to: ' + item.title;
      if (item.amountUsd > 0) {
        text = text + ' (' + Fmt.usd(item.amountUsd) + ')';
      }
      const request: notificationManager.NotificationRequest = {
        id: id,
        notificationSlotType: notificationManager.SlotType.SOCIAL_COMMUNICATION,
        content: {
          notificationContentType: notificationManager.ContentType.NOTIFICATION_CONTENT_BASIC_TEXT,
          normal: {
            title: 'Approval needed: requires ' + item.requiredRole,
            text: text,
            additionalText: 'Aegis Pocket'
          }
        },
        wantAgent: agent,
        tapDismissed: true,
        label: 'approval'
      };
      await notificationManager.publish(request);
      Log.info('Published notification for ' + item.id);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.warn('publish notification failed: ' + err.code + ' ' + err.message);
    }
  }

  static async cancelFor(approvalId: string): Promise<void> {
    try {
      await notificationManager.cancel(NotificationService.idFor(approvalId), 'approval');
    } catch (e) {
      // already gone
    }
  }

  private static idFor(approvalId: string): number {
    let h: number = 7;
    for (let i = 0; i < approvalId.length; i++) {
      h = (h * 31 + approvalId.charCodeAt(i)) % 1000000007;
    }
    return h % 2000000000;
  }
}
