import { formBindingData, formInfo, formProvider } from '@kit.FormKit';
import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { Profile, TileBlock, TileSpec } from '../tiles/model/Tile';
import { TileColors, TilesTheme } from '../tiles/theme/TilesTheme';
import { profileFor, seedTilesFor } from '../tiles/data/SeedTiles';

/** TileStore's default profile before onboarding / any change (its constructor seeds it). */
const DEFAULT_PROFILE_ID: string = 'everyday';

const DOMAIN: number = 0x7A12;
const TAG: string = 'TilesWidget';
/** Own Preferences file shared by the UI, FormExtension and WorkScheduler processes. */
const PREFS_FILE: string = 'tiles_widget';
const KEY_TILES: string = 'widget.tiles';
const KEY_PROFILE: string = 'widget.profile';

function logInfo(msg: string): void {
  hilog.info(DOMAIN, TAG, '%{public}s', msg);
}

function logWarn(msg: string): void {
  hilog.warn(DOMAIN, TAG, '%{public}s', msg);
}

/**
 * Data bound to the Tiles home-screen widgets (formBindingData). Flat fields: each key must match an
 * @LocalStorageProp in widget/pages/NextUpCard.ets, MyTilesCard.ets or BigButtonsCard.ets.
 * hasData=false means the app has not published its tiles yet ("Open Tiles to set up").
 */
export class TilesWidgetData {
  hasData: boolean = false;
  profileName: string = '';
  profileId: string = 'everyday';
  updated: string = '--:--';
  // 2x2 "Next up"
  nId: string = '';
  nLabel: string = 'NEXT UP';
  nBig: string = '';
  nTitle: string = 'Open Tiles';
  nSub: string = 'Your next reminder shows here';
  nBg: string = '#3DA5FF';
  nOn: string = '#06243F';
  nIcon: string = '';
  nType: string = 'custom';
  // 2x4 "My tiles" (top 3 pinned / first tiles)
  tCount: number = 0;
  t1Id: string = '';
  t1Title: string = '';
  t1Sub: string = '';
  t1Bg: string = '#FFC83D';
  t1On: string = '#3D2C00';
  t1Icon: string = '';
  t1Type: string = 'custom';
  t2Id: string = '';
  t2Title: string = '';
  t2Sub: string = '';
  t2Bg: string = '#FF6B5A';
  t2On: string = '#3B0E08';
  t2Icon: string = '';
  t2Type: string = 'custom';
  t3Id: string = '';
  t3Title: string = '';
  t3Sub: string = '';
  t3Bg: string = '#2ED3A0';
  t3On: string = '#04362A';
  t3Icon: string = '';
  t3Type: string = 'custom';
  // 4x4 "Big buttons" (senior): call / pills / SOS
  bCallId: string = '';
  bCallTitle: string = 'Call';
  bCallSub: string = '';
  bPillsId: string = '';
  bPillsTitle: string = 'Pills';
  bPillsSub: string = '';
  bSosId: string = '';
  bSosTitle: string = 'SOS';
  bSosSub: string = 'Call for help';
}

/** A tile's time of day (minutes since midnight) and day offset; minutes < 0 = no time found. */
class TileTime {
  minutes: number = -1;
  dayOffset: number = 0;
  label: string = '';
  raw: string = '';
}

const WEEKDAYS: string[] = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const WEEKDAY_NAMES: string[] = ['SUNDAY', 'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY'];
/** Tile types that carry a clock time worth surfacing as "Next up" (timer values are durations). */
const TIMED_TYPES: string[] = ['pills', 'reminder', 'plan', 'homework', 'note', 'call', 'adventure', 'custom'];
/** Preferred when nothing has a time (most actionable first). */
const PREFERRED_TYPES: string[] = ['pills', 'reminder', 'plan', 'homework', 'call', 'commute', 'timer'];

function pad2(v: number): string {
  return v < 10 ? '0' + v.toString() : v.toString();
}

function hhmm(ms: number): string {
  const d: Date = new Date(ms);
  return pad2(d.getHours()) + ':' + pad2(d.getMinutes());
}

/** First "H:MM"/"HH:MM" clock time (hours < 24) in the text, or null. */
function findClock(text: string): TileTime | null {
  const re: RegExp = new RegExp('(^|[^0-9])([0-9]{1,2})[:.]([0-9]{2})(?![0-9])');
  const m: RegExpExecArray | null = re.exec(text);
  if (m === null) {
    return null;
  }
  const h: number = Number(m[2]);
  const min: number = Number(m[3]);
  if (!(h >= 0 && h < 24 && min >= 0 && min < 60)) {
    return null;
  }
  const t: TileTime = new TileTime();
  t.minutes = h * 60 + min;
  t.label = h.toString() + ':' + pad2(min);
  t.raw = m[0].substring(m[1].length);
  return t;
}

/** Day offset (0..6) from an English weekday word in the text ("Fri", "Sunday"), today/none = 0. */
function weekdayOffset(text: string, today: number): number {
  const words: string[] = text.toLowerCase().split(new RegExp('[^a-z]+'));
  for (const w of words) {
    if (w.length < 3) {
      continue;
    }
    if (w === 'tomorrow') {
      return 1;
    }
    const idx: number = WEEKDAYS.indexOf(w.substring(0, 3));
    const full: boolean = w.length === 3 || w.endsWith('day') || w === 'tues' || w === 'thurs';
    if (idx >= 0 && full) {
      return (idx - today + 7) % 7;
    }
  }
  return 0;
}

function timeOf(t: TileSpec, today: number): TileTime | null {
  if (TIMED_TYPES.indexOf(t.type) < 0) {
    return null;
  }
  let found: TileTime | null = findClock(t.title);
  if (found === null) {
    for (const b of t.blocks) {
      if (b.kind === 'big' || b.kind === 'timer') {
        const v: string = b.value.startsWith('at:') ? b.value.substring(3) : b.value;
        if (b.kind === 'timer' && !b.value.startsWith('at:')) {
          continue; // focus-timer duration, not a clock time
        }
        found = findClock(v);
        if (found !== null) {
          break;
        }
      }
    }
  }
  if (found === null) {
    found = findClock(t.subtitle);
  }
  if (found === null) {
    return null;
  }
  found.dayOffset = weekdayOffset(t.title + ' ' + t.subtitle, today);
  return found;
}

/** "Pills 8:00" -> "Pills", "Walk at 17:00" -> "Walk" (the time is shown big next to it). */
function stripTime(title: string, raw: string): string {
  if (raw.length === 0 || title.indexOf(raw) < 0) {
    return title;
  }
  let s: string = title.replace(raw, '').trim();
  for (const tail of [' at', ' o', ' @', ' -', ' ·']) {
    if (s.endsWith(tail)) {
      s = s.substring(0, s.length - tail.length).trim();
    }
  }
  return s.length > 0 ? s : title;
}

function firstText(t: TileSpec): string {
  for (const b of t.blocks) {
    if ((b.kind === 'text' || b.kind === 'big') && b.text.length > 0) {
      return b.text;
    }
  }
  return '';
}

function bigValue(t: TileSpec): string {
  for (const b of t.blocks) {
    if ((b.kind === 'big' || b.kind === 'weather') && b.value.length > 0 && b.value.length <= 8) {
      return b.value;
    }
  }
  return '';
}

/** Pure: builds the widget data from the app's tiles + profile at `nowMs` (Next up depends on the clock). */
export function buildWidgetData(tiles: TileSpec[], profile: Profile, nowMs: number): TilesWidgetData {
  const d: TilesWidgetData = new TilesWidgetData();
  d.hasData = true;
  d.profileId = profile.id;
  d.profileName = profile.name;
  d.updated = hhmm(nowMs);
  const hc: boolean = profile.highContrast;
  const now: Date = new Date(nowMs);
  const today: number = now.getDay();
  const nowMin: number = now.getHours() * 60 + now.getMinutes();

  // Next up: the soonest upcoming clock time (today first, then later days, then past times = tomorrow).
  let next: TileSpec | null = null;
  let nextTime: TileTime | null = null;
  let bestScore: number = Number.MAX_VALUE;
  for (const t of tiles) {
    const tt: TileTime | null = timeOf(t, today);
    if (tt === null) {
      continue;
    }
    let days: number = tt.dayOffset;
    if (days === 0 && tt.minutes < nowMin) {
      days = 7; // already passed today: same time on a later day
      if (t.type === 'pills' || t.type === 'reminder') {
        days = 1; // daily reminders come back tomorrow
      }
    }
    const score: number = days * 1440 + tt.minutes;
    if (score < bestScore) {
      bestScore = score;
      next = t;
      nextTime = tt;
      nextTime.dayOffset = days;
    }
  }
  if (next === null) {
    for (const ty of PREFERRED_TYPES) {
      for (const t of tiles) {
        if (next === null && t.type === ty) {
          next = t;
        }
      }
    }
  }
  if (next === null && tiles.length > 0) {
    next = tiles[0];
  }
  if (next !== null) {
    const c: TileColors = TilesTheme.tile(next.color, hc, false);
    d.nId = next.id;
    d.nTitle = next.title;
    d.nSub = next.subtitle.length > 0 ? next.subtitle : firstText(next);
    d.nBg = c.bg;
    d.nOn = c.on;
    d.nIcon = next.icon;
    d.nType = next.type;
    if (nextTime !== null) {
      d.nBig = nextTime.label;
      d.nTitle = stripTime(next.title, nextTime.raw);
      d.nLabel = nextTime.dayOffset === 0 ? 'NEXT UP' :
        (nextTime.dayOffset === 1 ? 'TOMORROW' : WEEKDAY_NAMES[(today + nextTime.dayOffset) % 7]);
    } else {
      d.nBig = bigValue(next);
      d.nLabel = 'NEXT UP';
    }
  } else {
    d.nTitle = 'No tiles yet';
    d.nSub = 'Ask Tiles to make one';
  }

  // My tiles: pinned first, then the home-grid order.
  const top: TileSpec[] = [];
  for (const t of tiles) {
    if (t.pinned && top.length < 3) {
      top.push(t);
    }
  }
  for (const t of tiles) {
    if (!t.pinned && top.length < 3) {
      top.push(t);
    }
  }
  d.tCount = top.length;
  if (top.length > 0) {
    const c1: TileColors = TilesTheme.tile(top[0].color, hc, false);
    d.t1Id = top[0].id;
    d.t1Title = top[0].title;
    d.t1Sub = top[0].subtitle;
    d.t1Bg = c1.bg;
    d.t1On = c1.on;
    d.t1Icon = top[0].icon;
    d.t1Type = top[0].type;
  }
  if (top.length > 1) {
    const c2: TileColors = TilesTheme.tile(top[1].color, hc, false);
    d.t2Id = top[1].id;
    d.t2Title = top[1].title;
    d.t2Sub = top[1].subtitle;
    d.t2Bg = c2.bg;
    d.t2On = c2.on;
    d.t2Icon = top[1].icon;
    d.t2Type = top[1].type;
  }
  if (top.length > 2) {
    const c3: TileColors = TilesTheme.tile(top[2].color, hc, false);
    d.t3Id = top[2].id;
    d.t3Title = top[2].title;
    d.t3Sub = top[2].subtitle;
    d.t3Bg = c3.bg;
    d.t3On = c3.on;
    d.t3Icon = top[2].icon;
    d.t3Type = top[2].type;
  }

  // Big buttons: first call / pills / sos tile of the current profile.
  for (const t of tiles) {
    if (d.bCallId.length === 0 && t.type === 'call') {
      d.bCallId = t.id;
      d.bCallTitle = t.title;
      d.bCallSub = t.subtitle;
    } else if (d.bPillsId.length === 0 && t.type === 'pills') {
      d.bPillsId = t.id;
      d.bPillsTitle = t.title;
      d.bPillsSub = t.subtitle;
    } else if (d.bSosId.length === 0 && t.type === 'sos') {
      d.bSosId = t.id;
      d.bSosTitle = t.title;
      d.bSosSub = t.subtitle.length > 0 ? t.subtitle : 'Call for help';
    }
  }
  return d;
}

/**
 * Form Kit bridge for the Tiles widgets. The app publishes its tiles + profile (publish), which are
 * saved in Preferences so the FormExtension (onAddForm / onUpdateForm) and the WorkScheduler task can
 * rebuild the widget data in their own processes; "Next up" is recomputed from the clock on every refresh.
 */
export class WidgetBridge {
  private static gskv: number = -1;
  private static lastJson: string = '';

  private static options(): preferences.Options {
    if (WidgetBridge.gskv < 0) {
      let ok: boolean = false;
      try {
        ok = preferences.isStorageTypeSupported(preferences.StorageType.GSKV);
      } catch (e) {
        ok = false;
      }
      WidgetBridge.gskv = ok ? 1 : 0;
    }
    if (WidgetBridge.gskv === 1) {
      const o: preferences.Options = { name: PREFS_FILE + '_kv', storageType: preferences.StorageType.GSKV };
      return o;
    }
    const x: preferences.Options = { name: PREFS_FILE };
    return x;
  }

  private static open(ctx: common.Context, fresh: boolean): preferences.Preferences {
    const opts: preferences.Options = WidgetBridge.options();
    if (fresh && WidgetBridge.gskv !== 1) {
      preferences.removePreferencesFromCacheSync(ctx, opts);
    }
    return preferences.getPreferencesSync(ctx, opts);
  }

  /** Saves the tiles + profile for the widget/background processes. */
  static save(ctx: common.Context, tiles: TileSpec[], profile: Profile): void {
    try {
      const p: preferences.Preferences = WidgetBridge.open(ctx, false);
      p.putSync(KEY_TILES, JSON.stringify(tiles));
      p.putSync(KEY_PROFILE, JSON.stringify(profile));
      if (WidgetBridge.gskv !== 1) {
        p.flush().catch((e: Error) => {
          logWarn('widget prefs flush failed: ' + e.message);
        });
      }
    } catch (e) {
      logWarn('widget save failed: ' + JSON.stringify(e));
    }
  }

  /** Rebuilds the widget data from the saved tiles (any process). Nothing saved yet = hasData false. */
  static load(ctx: common.Context): TilesWidgetData {
    try {
      const p: preferences.Preferences = WidgetBridge.open(ctx, true);
      const rawTiles: preferences.ValueType = p.getSync(KEY_TILES, '');
      const rawProfile: preferences.ValueType = p.getSync(KEY_PROFILE, '');
      if (typeof rawTiles !== 'string' || rawTiles.length === 0) {
        // The app has not changed anything yet: it shows TileStore's seeded default profile, so do the same.
        return buildWidgetData(seedTilesFor(DEFAULT_PROFILE_ID), profileFor(DEFAULT_PROFILE_ID), Date.now());
      }
      const tiles: TileSpec[] = WidgetBridge.parseTiles(rawTiles as string);
      const profile: Profile = WidgetBridge.parseProfile(typeof rawProfile === 'string' ? rawProfile as string : '');
      return buildWidgetData(tiles, profile, Date.now());
    } catch (e) {
      logWarn('widget load failed: ' + JSON.stringify(e));
    }
    return new TilesWidgetData();
  }

  private static parseTiles(json: string): TileSpec[] {
    const out: TileSpec[] = [];
    try {
      const arr: TileSpec[] = JSON.parse(json) as TileSpec[];
      if (!Array.isArray(arr)) {
        return out;
      }
      for (const o of arr) {
        if (o === null || typeof o !== 'object' || typeof o.id !== 'string') {
          continue;
        }
        const t: TileSpec = new TileSpec();
        t.id = o.id;
        t.type = typeof o.type === 'string' ? o.type : 'custom';
        t.title = typeof o.title === 'string' ? o.title : '';
        t.subtitle = typeof o.subtitle === 'string' ? o.subtitle : '';
        t.icon = typeof o.icon === 'string' ? o.icon : '';
        t.color = typeof o.color === 'string' ? o.color : 'sky';
        t.pinned = o.pinned === true;
        const blocks: TileBlock[] = [];
        if (Array.isArray(o.blocks)) {
          for (const b of o.blocks) {
            if (b !== null && typeof b === 'object') {
              const nb: TileBlock = new TileBlock();
              nb.kind = typeof b.kind === 'string' ? b.kind : 'text';
              nb.text = typeof b.text === 'string' ? b.text : '';
              nb.value = typeof b.value === 'string' ? b.value : '';
              blocks.push(nb);
            }
          }
        }
        t.blocks = blocks;
        out.push(t);
      }
    } catch (e) {
      logWarn('widget tiles corrupt');
    }
    return out;
  }

  private static parseProfile(json: string): Profile {
    const p: Profile = new Profile();
    if (json.length === 0) {
      return p;
    }
    try {
      const o: Profile = JSON.parse(json) as Profile;
      if (o !== null && typeof o === 'object') {
        p.id = typeof o.id === 'string' ? o.id : 'everyday';
        p.name = typeof o.name === 'string' ? o.name : '';
        p.highContrast = o.highContrast === true;
      }
    } catch (e) {
      logWarn('widget profile corrupt');
    }
    return p;
  }

  static bindingData(data: TilesWidgetData): formBindingData.FormBindingData {
    return formBindingData.createFormBindingData(data);
  }

  /**
   * Updates every placed widget of this app. Returns true when there is no widget or at least one
   * update succeeded.
   */
  static async updateAll(data: TilesWidgetData): Promise<boolean> {
    try {
      const forms: formInfo.RunningFormInfo[] = await formProvider.getPublishedRunningFormInfos();
      if (forms.length === 0) {
        return true;
      }
      let ok: number = 0;
      for (const f of forms) {
        try {
          await formProvider.updateForm(f.formId, WidgetBridge.bindingData(data));
          ok++;
        } catch (e) {
          const err: BusinessError = e as BusinessError;
          logWarn('updateForm ' + f.formId + ' failed: ' + err.code);
        }
      }
      return ok > 0;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      logWarn('getPublishedRunningFormInfos failed: ' + err.code + ' ' + err.message);
    }
    return false;
  }

  /**
   * App side (UI process): call after the tiles or the profile change (e.g. TileStore persist) and when
   * the app goes to the background. Saves them for the widget processes and refreshes placed widgets.
   * Never throws.
   */
  static publish(ctx: common.Context, tiles: TileSpec[], profile: Profile): void {
    WidgetBridge.save(ctx, tiles, profile);
    const data: TilesWidgetData = buildWidgetData(tiles, profile, Date.now());
    const json: string = JSON.stringify(data);
    if (json === WidgetBridge.lastJson) {
      return;
    }
    WidgetBridge.updateAll(data).then((ok: boolean) => {
      if (ok) {
        WidgetBridge.lastJson = json;
        logInfo('widgets updated: next up ' + data.nId);
      }
    }).catch((e: Error) => {
      logWarn('widget publish failed: ' + e.message);
    });
  }

  /** Releases the cached Preferences instance (short-lived extension processes, GSKV recommendation). */
  static release(ctx: common.Context): void {
    try {
      preferences.removePreferencesFromCacheSync(ctx, WidgetBridge.options());
    } catch (e) {
      logWarn('widget prefs release failed');
    }
  }

  // ---- Legacy no-op shims: the old Aegis Pocket PocketStore still calls these until it is deleted. ----

  /** @deprecated Aegis Pocket only; kept so the old PocketStore compiles until cleanup removes it. */
  static build(stats: Object, pending: number, topRequest: string, failed: boolean = false): Object {
    return new Object();
  }

  /** @deprecated Aegis Pocket only; no-op. */
  static async push(ctx: common.Context, snap: Object): Promise<void> {
    return;
  }
}
