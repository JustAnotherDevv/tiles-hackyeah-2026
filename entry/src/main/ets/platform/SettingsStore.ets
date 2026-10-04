import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { Log } from '../common/Format';

export const PREFS_NAME: string = 'aegis_pocket';
export const DEFAULT_BASE_URL: string = 'http://10.0.2.2:8787';

export class AppSettings {
  mode: string = 'mock'; // mock | live
  baseUrl: string = DEFAULT_BASE_URL;
  persona: string = 'u_emily';
}

/** Persists the user's settings with ArkData Preferences (on-device only). */
export class SettingsStore {
  static load(ctx: common.Context): AppSettings {
    const s: AppSettings = new AppSettings();
    try {
      const p: preferences.Preferences = preferences.getPreferencesSync(ctx, { name: PREFS_NAME });
      s.mode = p.getSync('mode', 'mock') as string;
      s.baseUrl = p.getSync('baseUrl', DEFAULT_BASE_URL) as string;
      s.persona = p.getSync('persona', 'u_emily') as string;
    } catch (e) {
      Log.warn('Settings load failed: ' + JSON.stringify(e));
    }
    return s;
  }

  static save(ctx: common.Context, s: AppSettings): void {
    try {
      const p: preferences.Preferences = preferences.getPreferencesSync(ctx, { name: PREFS_NAME });
      p.putSync('mode', s.mode);
      p.putSync('baseUrl', s.baseUrl);
      p.putSync('persona', s.persona);
      p.flush().catch((e: Error) => {
        Log.warn('Settings flush failed: ' + e.message);
      });
    } catch (e) {
      Log.warn('Settings save failed: ' + JSON.stringify(e));
    }
  }
}
