import { vibrator } from '@kit.SensorServiceKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { TLog } from './TilesPlatform';

/**
 * Sensor Service Kit vibrator (ohos.permission.VIBRATE, system_grant), adapted from platform/Haptics.ets so the
 * Tiles layer does not depend on the old Aegis Pocket files. Prefers system preset effects, falls back to a timed
 * pulse, and silently does nothing without a vibrator (the emulator has none).
 */
export class TileHaptics {
  /** Light confirmation of a tap / toggle. */
  static tap(): void {
    TileHaptics.play('haptic.effect.soft', 15, 'touch');
  }

  /** Task done, pills taken, vote sent. */
  static success(): void {
    TileHaptics.play('haptic.notice.success', 30, 'touch');
  }

  /** Guardian warning, reminder due. */
  static warning(): void {
    TileHaptics.play('haptic.notice.warning', 45, 'notification');
  }

  /** SOS: one long, unmistakable pulse. */
  static sos(): void {
    TileHaptics.play('', 400, 'alarm');
  }

  private static play(effectId: string, fallbackMs: number, usage: vibrator.Usage): void {
    let effect: vibrator.VibrateEffect = { type: 'time', duration: fallbackMs };
    try {
      if (effectId.length > 0 && vibrator.isSupportEffectSync(effectId)) {
        effect = { type: 'preset', effectId: effectId, count: 1 };
      }
    } catch (e) {
      // No preset support or no vibrator: keep the timed pulse.
    }
    try {
      vibrator.startVibration(effect, { usage: usage }).catch((e: BusinessError) => {
        TLog.info('vibration skipped: ' + e.code);
      });
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      TLog.info('vibration unavailable: ' + err.code);
    }
  }
}
