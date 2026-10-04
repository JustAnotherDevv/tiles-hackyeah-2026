import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { Log } from '../common/Format';
import {
  AppSettings,
  DEFAULT_BASE_URL,
  DEFAULT_MODE,
  DEFAULT_PERSONA,
  PREFS_NAME,
  STORE_SETTINGS,
  prefsFileName
} from './PocketPersist';

export { AppSettings, DEFAULT_BASE_URL, PREFS_NAME };

const MIGRATED_KEY: string = 'legacySettingsMigrated';
const SETTINGS_KEYS: string[] = ['mode', 'baseUrl', 'persona'];

/**
 * One place that opens the app's Preferences, used by the UI process (SettingsStore, PocketStore via
 * WidgetBridge/BackgroundRefresh) and by the FormExtension and WorkScheduler extension processes.
 *
 * XML Preferences are not multi-process safe (ArkData guide "通过用户首选项实现数据持久化", XML模式约束限制),
 * so when the platform supports it (preferences.isStorageTypeSupported, API 18+) everything lives in one
 * GSKV file, which supports concurrent multi-process reads/writes and writes to disk in real time (no flush).
 * The storage mode of a file cannot be switched, so GSKV uses a new file name and the settings are
 * copied once from the legacy XML file. Without GSKV the stores are split: the settings XML file is
 * written only by the UI process, the snapshot/known-ids XML file is shared and always re-read from disk.
 */
export class PocketPrefs {
  private static gskvState: number = -1; // -1 unknown, 0 XML fallback, 1 GSKV
  private static migrated: boolean = false;

  static useGskv(): boolean {
    if (PocketPrefs.gskvState < 0) {
      let ok: boolean = false;
      try {
        ok = preferences.isStorageTypeSupported(preferences.StorageType.GSKV);
      } catch (e) {
        ok = false;
      }
      PocketPrefs.gskvState = ok ? 1 : 0;
      Log.info('Preferences storage: ' + (ok ? 'GSKV (multi-process safe)' : 'XML (split files)'));
    }
    return PocketPrefs.gskvState === 1;
  }

  static options(store: string): preferences.Options {
    const gskv: boolean = PocketPrefs.useGskv();
    const name: string = prefsFileName(store, gskv);
    if (gskv) {
      const o: preferences.Options = { name: name, storageType: preferences.StorageType.GSKV };
      return o;
    }
    const x: preferences.Options = { name: name };
    return x;
  }

  /**
   * Opens a store. `fresh` (XML only) drops this process's cached instance first so a value flushed by
   * another process is re-read; GSKV instances already see other processes' writes.
   */
  static open(ctx: common.Context, store: string, fresh: boolean): preferences.Preferences {
    const opts: preferences.Options = PocketPrefs.options(store);
    if (fresh && !PocketPrefs.useGskv()) {
      preferences.removePreferencesFromCacheSync(ctx, opts);
    }
    const p: preferences.Preferences = preferences.getPreferencesSync(ctx, opts);
    if (PocketPrefs.useGskv()) {
      PocketPrefs.migrateOnce(ctx, p);
    }
    return p;
  }

  /** Persists the writes: flush in XML mode; GSKV writes are already on disk. */
  static commit(p: preferences.Preferences, what: string): void {
    if (PocketPrefs.useGskv()) {
      return;
    }
    p.flush().catch((e: Error) => {
      Log.warn(what + ' flush failed: ' + e.message);
    });
  }

  /** GSKV: recommended once before an extension process exits (writes cached pages, faster next open). */
  static release(ctx: common.Context): void {
    if (!PocketPrefs.useGskv()) {
      return;
    }
    try {
      preferences.removePreferencesFromCacheSync(ctx, PocketPrefs.options(STORE_SETTINGS));
    } catch (e) {
      Log.warn('Preferences release failed: ' + JSON.stringify(e));
    }
  }

  /** Copies mode/baseUrl/persona from the legacy XML file without overwriting newer GSKV values. */
  private static migrateOnce(ctx: common.Context, p: preferences.Preferences): void {
    if (PocketPrefs.migrated) {
      return;
    }
    PocketPrefs.migrated = true;
    try {
      if (p.hasSync(MIGRATED_KEY)) {
        return;
      }
      const legacyOpts: preferences.Options = { name: PREFS_NAME };
      const legacy: preferences.Preferences = preferences.getPreferencesSync(ctx, legacyOpts);
      let copied: number = 0;
      for (const k of SETTINGS_KEYS) {
        if (legacy.hasSync(k) && !p.hasSync(k)) {
          const v: preferences.ValueType = legacy.getSync(k, '');
          if (typeof v === 'string') {
            p.putSync(k, v);
            copied++;
          }
        }
      }
      p.putSync(MIGRATED_KEY, true);
      preferences.removePreferencesFromCacheSync(ctx, legacyOpts);
      Log.info('Migrated ' + copied + ' setting(s) to GSKV preferences');
    } catch (e) {
      Log.warn('Settings migration failed: ' + JSON.stringify(e));
    }
  }
}

function str(v: preferences.ValueType): string {
  return typeof v === 'string' ? v : '';
}

/** Persists the user's settings with ArkData Preferences (on-device only). */
export class SettingsStore {
  /** Always re-reads (extension processes are long-lived) and sanitizes; defaults on any error. */
  static load(ctx: common.Context): AppSettings {
    try {
      const p: preferences.Preferences = PocketPrefs.open(ctx, STORE_SETTINGS, true);
      return AppSettings.sanitize(str(p.getSync('mode', DEFAULT_MODE)), str(p.getSync('baseUrl', DEFAULT_BASE_URL)),
        str(p.getSync('persona', DEFAULT_PERSONA)));
    } catch (e) {
      Log.warn('Settings load failed: ' + JSON.stringify(e));
    }
    return new AppSettings();
  }

  /** Written only by the UI process. Invalid values are replaced by defaults before they reach disk. */
  static save(ctx: common.Context, s: AppSettings): void {
    try {
      const clean: AppSettings = AppSettings.sanitize(s.mode, s.baseUrl, s.persona);
      const p: preferences.Preferences = PocketPrefs.open(ctx, STORE_SETTINGS, false);
      p.putSync('mode', clean.mode);
      p.putSync('baseUrl', clean.baseUrl);
      p.putSync('persona', clean.persona);
      PocketPrefs.commit(p, 'Settings');
    } catch (e) {
      Log.warn('Settings save failed: ' + JSON.stringify(e));
    }
  }
}
