import { accessibility } from '@kit.AccessibilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { PlatformKeys, TilesPlatform, TLog } from './TilesPlatform';

/**
 * Read-aloud for tiles.
 *
 * The spec asks for Core Speech Kit text-to-speech. That kit (`@kit.CoreSpeechKit`) ships only in the
 * HarmonyOS SDK; this project builds with the public OpenHarmony 6.1 SDK (API 23), which has no TTS module,
 * so the engine cannot be linked. What we do instead, with real platform APIs:
 *  1. Accessibility Kit `sendAccessibilityEvent('announceForAccessibility')`: when the system screen reader
 *     is on, the system speaks the text with its own TTS voice.
 *  2. A visual "Speaking…" state (AppStorage `tiles.speaking` / `tiles.speakingTileId`) for the UI, plus a
 *     toast labelled as a fallback when no screen reader is running (e.g. on the emulator).
 */
export class Speech {
  private static timer: number = -1;

  /** Speaks `text` (screen reader announcement) and shows the speaking state for a duration based on length. */
  static speak(text: string, tileId: string = ''): void {
    const t: string = text.trim();
    if (t.length === 0) {
      return;
    }
    AppStorage.setOrCreate<string>(PlatformKeys.SPEAKING, t);
    AppStorage.setOrCreate<string>(PlatformKeys.SPEAKING_TILE, tileId);
    if (Speech.timer >= 0) {
      clearTimeout(Speech.timer);
    }
    // ~14 chars/s reading speed, clamped to 2..12 s.
    const ms: number = Math.max(2000, Math.min(12000, Math.round(t.length * 70)));
    Speech.timer = setTimeout(() => {
      Speech.timer = -1;
      Speech.stop();
    }, ms);

    // The UI shows its own speaking state; keep the toast to one short line and never cover the Guardian call
    // screen (its hang-up button sits where toasts appear).
    const quiet: boolean = tileId.indexOf('guardian') >= 0;
    if (Speech.screenReaderOn()) {
      Speech.announce(t);
      if (!quiet) {
        TilesPlatform.toast('Reading aloud');
      }
    } else if (!quiet) {
      TilesPlatform.toast('Reading aloud · voice needs the screen reader');
    }
  }

  static stop(): void {
    AppStorage.setOrCreate<string>(PlatformKeys.SPEAKING, '');
    AppStorage.setOrCreate<string>(PlatformKeys.SPEAKING_TILE, '');
  }

  static isSpeaking(): boolean {
    const s: string | undefined = AppStorage.get<string>(PlatformKeys.SPEAKING);
    return s !== undefined && s.length > 0;
  }

  static screenReaderOn(): boolean {
    try {
      return accessibility.isScreenReaderOpenSync();
    } catch (e) {
      return false;
    }
  }

  private static announce(text: string): void {
    try {
      const ev: accessibility.EventInfo = new accessibility.EventInfo('announceForAccessibility',
        TilesPlatform.bundleName(), 'common');
      ev.textAnnouncedForAccessibility = text;
      accessibility.sendAccessibilityEvent(ev).then(() => {
        TLog.info('announced for accessibility');
      }).catch((e: BusinessError) => {
        TLog.warn('announce failed: ' + e.code + ' ' + e.message);
      });
    } catch (e) {
      TLog.warn('announce unavailable: ' + JSON.stringify(e));
    }
  }

  private static short(t: string): string {
    return t.length > 60 ? t.substring(0, 57) + '…' : t;
  }
}
