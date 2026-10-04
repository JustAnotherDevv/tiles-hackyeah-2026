import { PERSONAS, PostureStats, budgetLeftPctOf } from '../model/Models';

/**
 * Pure (no Kit imports) persistence rules shared by SettingsStore, WidgetBridge and BackgroundRefresh.
 * Kept free of system APIs so the host-side Local Test can cover it (Local Test cannot call system APIs).
 */

export const DEFAULT_BASE_URL: string = 'http://10.0.2.2:8787';
export const DEFAULT_MODE: string = 'mock';
export const DEFAULT_PERSONA: string = 'u_emily';

/** Legacy XML file (<= this fix). With GSKV it is only read once to migrate the settings. */
export const PREFS_NAME: string = 'aegis_pocket';
/** GSKV file shared by the UI, FormExtension and WorkScheduler processes (multi-process safe). */
export const PREFS_NAME_KV: string = 'aegis_pocket_kv';
/** XML fallback only: snapshot + known ids, kept apart from the settings file the UI process owns. */
export const PREFS_NAME_SHARED: string = 'aegis_pocket_shared';
export const STORE_SETTINGS: string = 'settings';
export const STORE_SHARED: string = 'shared';

/** Widget labels. OFFLINE = live mode, but the last gateway fetch failed (numbers are the last good ones). */
export const WIDGET_MOCK: string = 'MOCK';
export const WIDGET_LIVE: string = 'LIVE';
export const WIDGET_OFFLINE: string = 'OFFLINE';
export const WIDGET_NO_DATA_TEXT: string = 'No data yet. Open Aegis Pocket to sync';
/** A live snapshot older than this is shown as OFFLINE. */
export const LIVE_STALE_MS: number = 5 * 60 * 1000;
/** The app re-saves an unchanged-looking snapshot at most this often (mock mode ticks every 4 s). */
export const SNAPSHOT_SAVE_MIN_MS: number = 60 * 1000;

export class AppSettings {
  mode: string = DEFAULT_MODE; // mock | live
  baseUrl: string = DEFAULT_BASE_URL;
  persona: string = DEFAULT_PERSONA;

  /** Whitelists persisted values; anything unexpected falls back to the default for that field. */
  static sanitize(mode: string, baseUrl: string, persona: string): AppSettings {
    const s: AppSettings = new AppSettings();
    s.mode = mode === 'live' || mode === 'mock' ? mode : DEFAULT_MODE;
    const url: string = baseUrl.trim();
    s.baseUrl = isHttpUrl(url) ? url : DEFAULT_BASE_URL;
    let known: boolean = false;
    for (const p of PERSONAS) {
      if (p.id === persona) {
        known = true;
      }
    }
    s.persona = known ? persona : DEFAULT_PERSONA;
    return s;
  }
}

/** http(s)://host[...] with a non-empty host and no whitespace. */
export function isHttpUrl(url: string): boolean {
  let rest: string = '';
  if (url.startsWith('http://')) {
    rest = url.substring(7);
  } else if (url.startsWith('https://')) {
    rest = url.substring(8);
  } else {
    return false;
  }
  if (rest.length === 0 || rest.startsWith('/') || rest.startsWith(':')) {
    return false;
  }
  return !new RegExp('\\s').test(url);
}

/** Preferences file for a logical store ('settings' | 'shared'). */
export function prefsFileName(store: string, gskv: boolean): string {
  if (gskv) {
    return PREFS_NAME_KV;
  }
  return store === STORE_SETTINGS ? PREFS_NAME : PREFS_NAME_SHARED;
}

export function parseIdList(raw: string): string[] {
  const out: string[] = [];
  for (const id of raw.split(',')) {
    if (id.length > 0) {
      out.push(id);
    }
  }
  return out;
}

/**
 * Data bound to the home-screen service widgets. Field names must match the
 * @LocalStorageProp keys in widget/pages/PostureCard.ets and PostureWideCard.ets.
 * hasData=false means "nothing synced yet": the cards show "—" instead of numbers.
 */
export class WidgetSnapshot {
  hasData: boolean = false;
  pending: number = 0;
  blocked: number = 0;
  redacted: number = 0;
  budgetLeftPct: number = 0;
  spendToday: string = '—';
  topRequest: string = WIDGET_NO_DATA_TEXT;
  mode: string = WIDGET_MOCK;
  updated: string = '--:--';
}

/** 'live' -> LIVE, anything else -> MOCK. */
export function widgetLabelFor(settingsMode: string): string {
  return settingsMode === 'live' ? WIDGET_LIVE : WIDGET_MOCK;
}

export function emptySnapshot(settingsMode: string): WidgetSnapshot {
  const s: WidgetSnapshot = new WidgetSnapshot();
  s.mode = widgetLabelFor(settingsMode);
  return s;
}

function pad2(v: number): string {
  return v < 10 ? '0' + v.toString() : v.toString();
}

export function hhmm(ms: number): string {
  if (!(ms > 0)) {
    return '--:--';
  }
  const d: Date = new Date(ms);
  return pad2(d.getHours()) + ':' + pad2(d.getMinutes());
}

function isCount(v: number): boolean {
  return typeof v === 'number' && isFinite(v) && v >= 0;
}

function clampPct(v: number): number {
  return Math.max(0, Math.min(100, Math.round(v)));
}

/**
 * Builds the widget snapshot from the app's (or the background task's) latest stats.
 * Stats that never came from a repository (updatedAtMs 0) produce an empty snapshot, not zeros
 * presented as real data. `failed`, or a live snapshot older than LIVE_STALE_MS, yields OFFLINE.
 */
export function buildSnapshot(stats: PostureStats, pending: number, topRequest: string, spendToday: string,
  failed: boolean, nowMs: number): WidgetSnapshot {
  const live: boolean = stats.source === 'live';
  const s: WidgetSnapshot = emptySnapshot(live ? 'live' : 'mock');
  if (stats.updatedAtMs > 0) {
    s.hasData = true;
    s.pending = isCount(pending) ? Math.round(pending) : 0;
    s.blocked = isCount(stats.blocked) ? Math.round(stats.blocked) : 0;
    s.redacted = isCount(stats.redacted) ? Math.round(stats.redacted) : 0;
    const left: number = budgetLeftPctOf(stats);
    s.budgetLeftPct = isFinite(left) ? clampPct(left) : 0;
    s.spendToday = spendToday.length > 0 ? spendToday : '—';
    s.topRequest = topRequest.length > 0 ? topRequest : 'No pending requests';
    s.updated = hhmm(stats.updatedAtMs);
  }
  if (live && (failed || (s.hasData && nowMs - stats.updatedAtMs > LIVE_STALE_MS))) {
    s.mode = WIDGET_OFFLINE;
  }
  return s;
}

/** The last good data, relabelled OFFLINE (live fetch failed). */
export function markOffline(snap: WidgetSnapshot): WidgetSnapshot {
  const s: WidgetSnapshot = copySnapshot(snap);
  s.mode = WIDGET_OFFLINE;
  return s;
}

export function copySnapshot(o: WidgetSnapshot): WidgetSnapshot {
  const s: WidgetSnapshot = new WidgetSnapshot();
  s.hasData = o.hasData;
  s.pending = o.pending;
  s.blocked = o.blocked;
  s.redacted = o.redacted;
  s.budgetLeftPct = o.budgetLeftPct;
  s.spendToday = o.spendToday;
  s.topRequest = o.topRequest;
  s.mode = o.mode;
  s.updated = o.updated;
  return s;
}

/**
 * Parses a persisted snapshot. Missing, corrupt or pre-fix (no hasData) JSON yields the empty
 * snapshot labelled for the current settings mode. A snapshot from the other mode (e.g. mock data
 * after the user switched to live) is discarded too, so mock numbers never appear as LIVE.
 */
export function parseSnapshot(json: string, settingsMode: string): WidgetSnapshot {
  const out: WidgetSnapshot = emptySnapshot(settingsMode);
  if (json.length === 0) {
    return out;
  }
  let o: WidgetSnapshot | null = null;
  try {
    o = JSON.parse(json) as WidgetSnapshot;
  } catch (e) {
    return out;
  }
  if (o === null || typeof o !== 'object' || o.hasData !== true) {
    return out;
  }
  const live: boolean = settingsMode === 'live';
  const modeOk: boolean = live ? (o.mode === WIDGET_LIVE || o.mode === WIDGET_OFFLINE) : o.mode === WIDGET_MOCK;
  if (!modeOk || !isCount(o.pending) || !isCount(o.blocked) || !isCount(o.redacted) ||
    !isCount(o.budgetLeftPct) || typeof o.spendToday !== 'string' || typeof o.topRequest !== 'string' ||
    typeof o.updated !== 'string') {
    return out;
  }
  out.hasData = true;
  out.pending = Math.round(o.pending);
  out.blocked = Math.round(o.blocked);
  out.redacted = Math.round(o.redacted);
  out.budgetLeftPct = clampPct(o.budgetLeftPct);
  out.spendToday = o.spendToday;
  out.topRequest = o.topRequest;
  out.mode = o.mode;
  out.updated = o.updated;
  return out;
}

/** Fields whose change must reach disk at once; other drift (mock stats, minute) is throttled. */
export function snapshotKey(s: WidgetSnapshot): string {
  return s.mode + '|' + (s.hasData ? '1' : '0') + '|' + s.pending.toString() + '|' + s.topRequest;
}

export function shouldSaveSnapshot(lastKey: string, key: string, lastSavedMs: number, nowMs: number): boolean {
  return key !== lastKey || nowMs - lastSavedMs >= SNAPSHOT_SAVE_MIN_MS;
}
