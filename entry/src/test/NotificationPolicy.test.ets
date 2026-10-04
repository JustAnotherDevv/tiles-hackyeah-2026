import { describe, it, expect } from '@ohos/hypium';
import {
  ERR_DIALOG_ALREADY_SHOWN,
  ERR_NOTIFICATION_DISABLED,
  NO_ERROR,
  shouldOpenSettings
} from '../main/ets/platform/NotificationPolicy';

// When the Settings "Enable" button must fall back to the app's notification settings sheet.
export default function notificationPolicyTest() {
  describe('NotificationPolicy', () => {
    it('deniedOnTapOpensSettings', 0, () => {
      expect(shouldOpenSettings(ERR_NOTIFICATION_DISABLED, true, true)).assertTrue();
    });

    it('silentNoDialogOnTapOpensSettings', 0, () => {
      expect(shouldOpenSettings(NO_ERROR, true, true)).assertTrue();
    });

    it('grantedDoesNotOpenSettings', 0, () => {
      expect(shouldOpenSettings(NO_ERROR, false, true)).assertFalse();
    });

    it('launchTimeRequestNeverOpensSettings', 0, () => {
      expect(shouldOpenSettings(ERR_NOTIFICATION_DISABLED, true, false)).assertFalse();
      expect(shouldOpenSettings(NO_ERROR, true, false)).assertFalse();
    });

    it('otherErrorsDoNotOpenSettings', 0, () => {
      expect(shouldOpenSettings(ERR_DIALOG_ALREADY_SHOWN, true, true)).assertFalse();
      expect(shouldOpenSettings(1600001, true, true)).assertFalse();
      expect(shouldOpenSettings(401, true, true)).assertFalse();
    });
  });
}
