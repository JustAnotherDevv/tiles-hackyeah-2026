/**
 * Pure mapping of User Authentication Kit result codes to step-up outcomes.
 *
 * Kept free of Kit imports so the fail-closed rules can be unit tested on the host. Code values are the documented
 * userAuth.UserAuthResultCode members (js-apis-useriam-userauth, "UserAuthResultCode"); 12500012 is not defined there.
 *
 * Security rule: 'unavailable' (which lets the UI offer the labelled manual fallback) is returned ONLY by
 * precheckOutcome, when the pre-check found no usable authenticator at all. Once an authenticator exists, every
 * non-SUCCESS code fails closed ('failed', or 'cancelled' for a user cancel) and never opens the fallback.
 */
export class AuthCode {
  static readonly SUCCESS: number = 12500000;
  static readonly FAIL: number = 12500001;
  static readonly GENERAL_ERROR: number = 12500002;
  static readonly CANCELED: number = 12500003;
  static readonly TIMEOUT: number = 12500004;
  static readonly TYPE_NOT_SUPPORT: number = 12500005;
  static readonly TRUST_LEVEL_NOT_SUPPORT: number = 12500006;
  static readonly BUSY: number = 12500007;
  static readonly INVALID_PARAMETERS: number = 12500008; // API 20+
  static readonly LOCKED: number = 12500009;
  static readonly NOT_ENROLLED: number = 12500010;
  static readonly CANCELED_FROM_WIDGET: number = 12500011;
  static readonly PIN_EXPIRED: number = 12500013;
  /** Common error code: permission denied (ohos.permission.ACCESS_BIOMETRIC). */
  static readonly PERMISSION_DENIED: number = 201;
}

/** Outcome of a step-up attempt. */
export class StepUpOutcome {
  /** 'verified' | 'cancelled' | 'failed' | 'unavailable' */
  status: string;
  /** Human label of the method that verified the user ('face', 'fingerprint', 'PIN'), or the reason. */
  detail: string;

  constructor(status: string, detail: string) {
    this.status = status;
    this.detail = detail;
  }
}

export class StepUpCodes {
  /**
   * Result of the availability pre-check (getAvailableStatus per type), before anything is started.
   * Returns undefined when at least one authenticator is usable (go ahead and start the auth widget).
   * Returns 'unavailable' only when every type failed with "no such authenticator / not enrolled / trust level"
   * (the emulator case). Any other pre-check failure (PIN expired, general error, permission) fails closed.
   */
  static precheckOutcome(usableTypes: number, failCodes: number[]): StepUpOutcome | undefined {
    if (usableTypes > 0) {
      return undefined;
    }
    let pinExpired: boolean = false;
    let other: number = 0;
    for (const c of failCodes) {
      if (c === AuthCode.PIN_EXPIRED) {
        pinExpired = true;
      } else if (c !== AuthCode.TYPE_NOT_SUPPORT && c !== AuthCode.TRUST_LEVEL_NOT_SUPPORT &&
        c !== AuthCode.NOT_ENROLLED) {
        other = c;
      }
    }
    if (pinExpired) {
      return new StepUpOutcome('failed', 'Your lock-screen PIN has expired: update it in Settings, then try again');
    }
    if (other !== 0) {
      return new StepUpOutcome('failed', 'Could not check device authentication (code ' + other + '), try again');
    }
    return new StepUpOutcome('unavailable', 'No face, fingerprint or PIN is available on this device');
  }

  /**
   * Maps a code returned by the auth widget (onResult) or thrown by getUserAuthInstance/start() to an outcome.
   * Never returns 'unavailable': by the time this runs the pre-check already found an authenticator.
   * @param method label of the method that verified the user, used only on SUCCESS
   */
  static outcomeOf(code: number, method: string): StepUpOutcome {
    if (code === AuthCode.SUCCESS) {
      return new StepUpOutcome('verified', method.length > 0 ? method : 'device credential');
    }
    if (code === AuthCode.CANCELED || code === AuthCode.CANCELED_FROM_WIDGET) {
      return new StepUpOutcome('cancelled', 'Authentication cancelled');
    }
    return new StepUpOutcome('failed', StepUpCodes.failureText(code));
  }

  static failureText(code: number): string {
    if (code === AuthCode.FAIL) {
      return 'Not recognised, try again';
    }
    if (code === AuthCode.TIMEOUT) {
      return 'Authentication timed out';
    }
    if (code === AuthCode.BUSY) {
      return 'Authentication service busy, try again';
    }
    if (code === AuthCode.LOCKED) {
      return 'Authentication locked after too many attempts: unlock with your PIN';
    }
    if (code === AuthCode.PIN_EXPIRED) {
      return 'Your lock-screen PIN has expired: update it in Settings';
    }
    if (code === AuthCode.NOT_ENROLLED) {
      return 'No credential enrolled for this method';
    }
    if (code === AuthCode.GENERAL_ERROR) {
      return 'Authentication error, try again';
    }
    if (code === AuthCode.PERMISSION_DENIED) {
      return 'Authentication permission denied';
    }
    return 'Authentication failed (code ' + code + ')';
  }
}
