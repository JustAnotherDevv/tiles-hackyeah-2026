import { userAuth } from '@kit.UserAuthenticationKit';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { Log } from '../common/Format';
import { StepUpCodes, StepUpOutcome } from './StepUpCodes';

/** Gives up on the auth widget if it never reports a result (the promise must always settle). */
const AUTH_TIMEOUT_MS: number = 90000;

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
 * Only when the pre-check finds no enrolled authenticator at all (for example the DevEco emulator,
 * which cannot simulate biometrics) does it return 'unavailable', and the caller shows an explicitly
 * labelled manual-confirmation fallback. Any failure after that point fails closed.
 */
export class StepUpAuth {
  /** Authentication types this device can use right now at ATL3 (empty on most emulators). */
  static availableTypes(): userAuth.UserAuthType[] {
    return StepUpAuth.probe([]);
  }

  /** Checks each type at ATL3; usable types are returned, failure codes are appended to failCodes. */
  private static probe(failCodes: number[]): userAuth.UserAuthType[] {
    const out: userAuth.UserAuthType[] = [];
    for (const t of TYPE_ORDER) {
      try {
        userAuth.getAvailableStatus(t, userAuth.AuthTrustLevel.ATL3);
        out.push(t);
      } catch (e) {
        const err: BusinessError = e as BusinessError;
        failCodes.push(err.code);
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

  /**
   * Shows the system authentication sheet. Never rejects; inspect StepUpOutcome.status.
   * 'unavailable' is returned only when the pre-check finds no usable authenticator; after that every
   * non-success result fails closed (see StepUpCodes).
   */
  static authenticate(title: string): Promise<StepUpOutcome> {
    return new Promise<StepUpOutcome>((resolve: (o: StepUpOutcome) => void) => {
      const failCodes: number[] = [];
      const types: userAuth.UserAuthType[] = StepUpAuth.probe(failCodes);
      const pre: StepUpOutcome | undefined = StepUpCodes.precheckOutcome(types.length, failCodes);
      if (pre !== undefined) {
        resolve(pre);
        return;
      }
      let settled: boolean = false;
      let started: boolean = false;
      let instance: userAuth.UserAuthInstance | undefined = undefined;
      let timer: number = -1;
      const finish = (o: StepUpOutcome): void => {
        if (settled) {
          return;
        }
        settled = true;
        if (timer !== -1) {
          clearTimeout(timer);
          timer = -1;
        }
        if (instance !== undefined) {
          try {
            instance.off('result');
          } catch (e) {
            // already unsubscribed
          }
        }
        resolve(o);
      };
      timer = setTimeout(() => {
        timer = -1;
        if (settled) {
          return;
        }
        Log.warn('userAuth: no result after ' + AUTH_TIMEOUT_MS + ' ms, cancelling');
        if (instance !== undefined && started) {
          try {
            instance.cancel(); // documented as valid only after start()
          } catch (e) {
            const err: BusinessError = e as BusinessError;
            Log.warn('userAuth cancel failed: ' + err.code);
          }
        }
        finish(new StepUpOutcome('failed', 'Authentication timed out'));
      }, AUTH_TIMEOUT_MS);
      try {
        const authParam: userAuth.AuthParam = {
          challenge: StepUpAuth.challenge(),
          authType: types,
          authTrustLevel: userAuth.AuthTrustLevel.ATL3
        };
        const widgetParam: userAuth.WidgetParam = {
          title: title.length > 0 ? title.substring(0, 480) : 'Confirm approval'
        };
        const inst: userAuth.UserAuthInstance = userAuth.getUserAuthInstance(authParam, widgetParam);
        instance = inst;
        inst.on('result', {
          onResult: (result: userAuth.UserAuthResult) => {
            finish(StepUpAuth.outcomeOf(result.result, result.authType));
          }
        });
        inst.start();
        started = true;
      } catch (e) {
        const err: BusinessError = e as BusinessError;
        Log.warn('userAuth start failed: ' + err.code + ' ' + err.message);
        // An authenticator exists (pre-check passed), so a thrown code fails closed: never 'unavailable'.
        finish(StepUpAuth.outcomeOf(err.code, undefined));
      }
    });
  }

  /** Maps a UserAuthResultCode to an outcome (never 'unavailable'). Pure rules live in StepUpCodes. */
  static outcomeOf(code: number, authType: userAuth.UserAuthType | undefined): StepUpOutcome {
    return StepUpCodes.outcomeOf(code, StepUpAuth.typeName(authType));
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
