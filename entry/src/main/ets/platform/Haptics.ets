import { vibrator } from '@kit.SensorServiceKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { Log } from '../common/Format';

/**
 * Sensor Service Kit vibrator: short, distinct haptic cues for approve / deny / new request.
 * Prefers the system's preset effects (`haptic.notice.*`) when the motor supports them and
 * falls back to a timed pulse. Requires ohos.permission.VIBRATE (system_grant). Silently does
 * nothing on devices without a vibrator (the DevEco emulator has none).
 */
export class Haptics {
  /** Approved / authentication verified. */
  static success(): void {
    Haptics.play('haptic.notice.success', 30, 'touch');
  }

  /** Denied or a refused vote. */
  static failure(): void {
    Haptics.play('haptic.notice.fail', 60, 'touch');
  }

  /** A new approval request arrived while the app is open. */
  static notice(): void {
    Haptics.play('haptic.notice.warning', 45, 'notification');
  }

  private static play(effectId: string, fallbackMs: number, usage: vibrator.Usage): void {
    let effect: vibrator.VibrateEffect = { type: 'time', duration: fallbackMs };
    try {
      if (vibrator.isSupportEffectSync(effectId)) {
        effect = { type: 'preset', effectId: effectId, count: 1 };
      }
    } catch (e) {
      // isSupportEffectSync is unavailable or the device has no vibrator: keep the timed pulse.
    }
    try {
      vibrator.startVibration(effect, { usage: usage }).catch((e: BusinessError) => {
        Log.info('vibration skipped: ' + e.code);
      });
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.info('vibration unavailable: ' + err.code);
    }
  }
}
