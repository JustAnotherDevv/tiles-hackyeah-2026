/**
 * Pure decision logic for the notification permission flow (no kit imports, so it is host-unit-testable).
 *
 * Per the Notification Kit guide "请求通知授权" (notification-enable): once the user has denied the
 * requestEnableNotification dialog it cannot be shown again, and error 1600004 means "denied". To ask
 * again the app must open its notification settings sheet (notificationManager.openNotificationSettings,
 * API 13+; the guide's openNotificationSettingsWithResult is not in the API 24 SDK installed here).
 */

/** requestEnableNotification: notification disabled (user denied). */
export const ERR_NOTIFICATION_DISABLED: number = 1600004;
/** requestEnableNotification: a notification dialog box is already displayed. */
export const ERR_DIALOG_ALREADY_SHOWN: number = 1600013;
/** openNotificationSettings: the notification settings window is already displayed. */
export const ERR_SETTINGS_ALREADY_SHOWN: number = 1600018;
/** Pseudo-code used when requestEnableNotification resolved without throwing. */
export const NO_ERROR: number = 0;

/**
 * Whether to open the app's notification settings sheet after a requestEnableNotification attempt.
 *
 * @param errCode BusinessError code thrown by requestEnableNotification, or NO_ERROR if it resolved.
 * @param stillDisabled isNotificationEnabled() result after the attempt was false.
 * @param userInitiated true when the user tapped "Enable"; the automatic launch-time request never
 *   opens settings, so a user who denied once is not nagged on every start.
 */
export function shouldOpenSettings(errCode: number, stillDisabled: boolean, userInitiated: boolean): boolean {
  if (!userInitiated) {
    return false;
  }
  if (errCode === ERR_NOTIFICATION_DISABLED) {
    return true;
  }
  // The dialog can no longer be shown after a denial; some builds resolve silently instead of throwing.
  return errCode === NO_ERROR && stillDisabled;
}
