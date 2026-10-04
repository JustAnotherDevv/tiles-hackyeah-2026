import { userAuth } from '@kit.UserAuthenticationKit';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { Log } from '../common/Format';

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

const TYPE_ORDER: userAuth.UserAuthType[] = [
  userAuth.UserAuthType.FACE,
  userAuth.UserAuthType.FINGERPRINT,
  userAuth.UserAuthType.PIN
];

/**
 * User Authentication Kit (userIAM.userAuth) step-up before risky approvals.
 *
 * Uses the system authentication widget (face / fingerprint / lock-screen PIN, ATL3) with a random
 * challenge. Requires ohos.permission.ACCESS_BIOMETRIC (system_grant, normal APL: ordinary apps).
 * When no credential is enrolled or the device has no authenticator (for example the DevEco
 * emulator, which cannot simulate biometrics), it returns 'unavailable' and the caller shows an
 * explicitly labelled manual-confirmation fallback.
 */
export class StepUpAuth {
  /** Authentication types this device can use right now at ATL3 (empty on most emulators). */
  static availableTypes(): userAuth.UserAuthType[] {
    const out: userAuth.UserAuthType[] = [];
    for (const t of TYPE_ORDER) {
      try {
        userAuth.getAvailableStatus(t, userAuth.AuthTrustLevel.ATL3);
        out.push(t);
      } catch (e) {
        const err: BusinessError = e as BusinessError;
        Log.info('userAuth type ' + t + ' unavailable: ' + err.code);
      }
    }
    return out;
  }

  /** Short label for the settings / detail screens, e.g. "face, PIN" or "none". */
  static describeAvailable(): string {
    const types: userAuth.UserAuthType[] = StepUpAuth.availableTypes();
    if (types.length === 0) {
      return 'none';
    }
    const names: string[] = [];
    for (const t of types) {
      names.push(StepUpAuth.typeName(t));
    }
    return names.join(', ');
  }

  static typeName(t: userAuth.UserAuthType | undefined): string {
    if (t === userAuth.UserAuthType.FACE) {
      return 'face';
    }
    if (t === userAuth.UserAuthType.FINGERPRINT) {
      return 'fingerprint';
    }
    if (t === userAuth.UserAuthType.PIN) {
      return 'PIN';
    }
    return 'device credential';
  }

  /** Shows the system authentication sheet. Never rejects; inspect StepUpOutcome.status. */
  static authenticate(title: string): Promise<StepUpOutcome> {
    return new Promise<StepUpOutcome>((resolve: (o: StepUpOutcome) => void) => {
      const types: userAuth.UserAuthType[] = StepUpAuth.availableTypes();
      if (types.length === 0) {
        resolve(new StepUpOutcome('unavailable', 'No face, fingerprint or PIN is available on this device'));
        return;
      }
      let settled: boolean = false;
      const finish = (o: StepUpOutcome): void => {
        if (!settled) {
          settled = true;
          resolve(o);
        }
      };
      try {
        const authParam: userAuth.AuthParam = {
          challenge: StepUpAuth.challenge(),
          authType: types,
          authTrustLevel: userAuth.AuthTrustLevel.ATL3
        };
        const widgetParam: userAuth.WidgetParam = {
          title: title.length > 0 ? title.substring(0, 480) : 'Confirm approval'
        };
        const instance: userAuth.UserAuthInstance = userAuth.getUserAuthInstance(authParam, widgetParam);
        instance.on('result', {
          onResult: (result: userAuth.UserAuthResult) => {
            try {
              instance.off('result');
            } catch (e) {
              // already unsubscribed
            }
            finish(StepUpAuth.outcomeOf(result.result, result.authType));
          }
        });
        instance.start();
      } catch (e) {
        const err: BusinessError = e as BusinessError;
        Log.warn('userAuth start failed: ' + err.code + ' ' + err.message);
        finish(StepUpAuth.outcomeOf(err.code, undefined));
      }
    });
  }

  /** Maps a UserAuthResultCode to an outcome. Exported for unit tests. */
  static outcomeOf(code: number, authType: userAuth.UserAuthType | undefined): StepUpOutcome {
    if (code === userAuth.UserAuthResultCode.SUCCESS) {
      return new StepUpOutcome('verified', StepUpAuth.typeName(authType));
    }
    if (code === userAuth.UserAuthResultCode.CANCELED || code === userAuth.UserAuthResultCode.CANCELED_FROM_WIDGET) {
      return new StepUpOutcome('cancelled', 'Authentication cancelled');
    }
    if (code === userAuth.UserAuthResultCode.TYPE_NOT_SUPPORT ||
      code === userAuth.UserAuthResultCode.TRUST_LEVEL_NOT_SUPPORT ||
      code === userAuth.UserAuthResultCode.NOT_ENROLLED ||
      code === userAuth.UserAuthResultCode.GENERAL_ERROR) {
      return new StepUpOutcome('unavailable', 'Device authentication unavailable (code ' + code + ')');
    }
    if (code === userAuth.UserAuthResultCode.LOCKED) {
      return new StepUpOutcome('failed', 'Authentication locked: too many attempts');
    }
    if (code === userAuth.UserAuthResultCode.TIMEOUT) {
      return new StepUpOutcome('failed', 'Authentication timed out');
    }
    return new StepUpOutcome('failed', 'Authentication failed (code ' + code + ')');
  }

  private static challenge(): Uint8Array {
    try {
      const rand: cryptoFramework.Random = cryptoFramework.createRandom();
      return rand.generateRandomSync(32).data;
    } catch (e) {
      const out: Uint8Array = new Uint8Array(32);
      for (let i = 0; i < out.length; i++) {
        out[i] = Math.floor(Math.random() * 256);
      }
      return out;
    }
  }
}
