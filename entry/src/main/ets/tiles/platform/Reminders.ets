import { reminderAgentManager } from '@kit.BackgroundTasksKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { TileSpec } from '../model/Tile';
import { PARAM_TILE_ID, PlatformKeys, TilesPlatform, TLog } from './TilesPlatform';
import { TileNotifications } from './TileNotifications';

/** reminderAgentManager: per-app limit reached. Ordinary HarmonyOS apps without the agent-reminder entitlement
 * (granted via AppGallery) get a limit of 0, which is what the debug-signed build sees on the emulator. */
export const ERR_REMINDER_LIMIT: number = 1700002;
/** schedule() result when the system refused and the in-app fallback timer was set instead. */
export const REMINDER_IN_APP: number = -2;

/** Parsed reminder time: a clock time (alarm, optionally on one weekday) or a delay in seconds (countdown). */
export class ReminderWhen {
  hour: number = -1;
  minute: number = -1;
  /** 1 = Monday … 7 = Sunday (reminderAgentManager daysOfWeek); 0 = next occurrence of the time. */
  dayOfWeek: number = 0;
  delaySec: number = 0;

  isClock(): boolean {
    return this.hour >= 0 && this.minute >= 0;
  }

  label(): string {
    if (this.isClock()) {
      const t: string = this.hour.toString() + ':' + (this.minute < 10 ? '0' : '') + this.minute.toString();
      return this.dayOfWeek > 0 ? DAY_NAMES[this.dayOfWeek - 1] + ' ' + t : t;
    }
    return this.delaySec >= 60 ? Math.round(this.delaySec / 60).toString() + ' min' :
      this.delaySec.toString() + ' s';
  }
}

const DAY_NAMES: string[] = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
/** EN + PL weekday prefixes, index = dayOfWeek - 1. */
const DAY_KEYS: string[][] = [['mon', 'pon'], ['tue', 'wt'], ['wed', 'sr', 'śr'], ['thu', 'czw'], ['fri', 'pt', 'pią'],
  ['sat', 'sob'], ['sun', 'nd', 'niedz']];

/**
 * Background Tasks Kit agent-powered reminders (reminderAgentManager, ohos.permission.PUBLISH_AGENT_REMINDER):
 * the system shows the reminder at the given time even when Tiles is closed. Pills tiles repeat daily.
 * Tapping the reminder opens the tile (want parameter `tileId`). Requires notifications to be enabled.
 *
 * Accepted times (TileAction.arg, else found in the tile): "8:00", "08:00", "19:30", "at:08:00",
 * "tue-18:00" (weekly on that day), "15" (minutes from now), "+30s", "+10m" (countdown, handy for demos).
 */
export class Reminders {
  /** Parses a time string; returns null when none is found. */
  static parse(raw: string, allowBareMinutes: boolean = false): ReminderWhen | null {
    const s: string = raw.trim().toLowerCase();
    if (allowBareMinutes && new RegExp('^\\d{1,4}$').test(s)) {
      const w: ReminderWhen = new ReminderWhen();
      w.delaySec = parseInt(s) * 60;
      return w.delaySec > 0 ? w : null;
    }
    const rel: RegExpMatchArray | null = s.match(new RegExp('^\\+\\s*(\\d{1,4})\\s*(s|sec|m|min)?$'));
    if (rel !== null) {
      const w: ReminderWhen = new ReminderWhen();
      const n: number = parseInt(rel[1]);
      w.delaySec = rel[2] !== undefined && rel[2].startsWith('s') ? n : n * 60;
      return w.delaySec > 0 ? w : null;
    }
    const m: RegExpMatchArray | null = s.match(new RegExp('(\\d{1,2})[:.](\\d{2})'));
    if (m !== null) {
      const h: number = parseInt(m[1]);
      const min: number = parseInt(m[2]);
      if (h >= 0 && h < 24 && min >= 0 && min < 60) {
        const w: ReminderWhen = new ReminderWhen();
        w.hour = h;
        w.minute = min;
        for (let d = 0; d < DAY_KEYS.length; d++) {
          for (const k of DAY_KEYS[d]) {
            if (s.startsWith(k)) {
              w.dayOfWeek = d + 1;
            }
          }
        }
        return w;
      }
    }
    return null;
  }

  /** Finds the reminder time for a tile: explicit arg first, then big/timer blocks, then title/subtitle. */
  static whenFor(tile: TileSpec, arg: string): ReminderWhen | null {
    if (arg.length > 0) {
      const direct: ReminderWhen | null = Reminders.parse(arg, true);
      if (direct !== null) {
        return direct;
      }
    }
    const candidates: string[] = [];
    for (const b of tile.blocks) {
      if (b.kind === 'big' || b.kind === 'timer') {
        candidates.push(b.value);
      }
    }
    candidates.push(tile.title);
    candidates.push(tile.subtitle);
    for (const b of tile.blocks) {
      candidates.push(b.text);
    }
    for (const c of candidates) {
      if (c.length > 0) {
        const w: ReminderWhen | null = Reminders.parse(c);
        if (w !== null) {
          return w;
        }
      }
    }
    return null;
  }

  /**
   * Schedules (or re-schedules) the reminder for a tile. Resolves to the reminder id, or -1 on failure.
   * Pills tiles repeat every day; other clock reminders fire once at the next occurrence.
   */
  static async schedule(tile: TileSpec, when: ReminderWhen, text: string = ''): Promise<number> {
    const bundle: string = TilesPlatform.bundleName();
    if (bundle.length === 0) {
      return -1;
    }
    // One clock reminder and one countdown per tile: re-scheduling replaces the same kind only.
    const key: string = tile.id + (when.isClock() ? ':clock' : ':countdown');
    await Reminders.cancelMatching(tile.id, key);
    const params: Record<string, Object> = { 'tileId': tile.id, 'reminderKey': key };
    const title: string = tile.title.length > 0 ? tile.title : 'Tiles reminder';
    const content: string = text.length > 0 ? text :
      (tile.type === 'pills' ? 'Time for your pills. Tap when taken.' : (tile.subtitle.length > 0 ? tile.subtitle :
        'Reminder from Tiles'));
    let req: reminderAgentManager.ReminderRequest;
    if (when.isClock()) {
      const alarm: reminderAgentManager.ReminderRequestAlarm = {
        reminderType: reminderAgentManager.ReminderType.REMINDER_TYPE_ALARM,
        hour: when.hour,
        minute: when.minute,
        title: title,
        content: content,
        expiredContent: 'Missed: ' + title,
        snoozeContent: 'Snoozed: ' + title,
        actionButton: [
          { title: 'Done', type: reminderAgentManager.ActionButtonType.ACTION_BUTTON_TYPE_CLOSE },
          { title: 'Later', type: reminderAgentManager.ActionButtonType.ACTION_BUTTON_TYPE_SNOOZE }
        ],
        wantAgent: { pkgName: bundle, abilityName: 'EntryAbility', parameters: params },
        ringDuration: 5,
        snoozeTimes: 2,
        timeInterval: 5 * 60,
        notificationId: TilesPlatform.idFor('reminder:' + key)
      };
      if (when.dayOfWeek > 0) {
        alarm.daysOfWeek = [when.dayOfWeek];
      } else if (tile.type === 'pills') {
        alarm.daysOfWeek = [1, 2, 3, 4, 5, 6, 7];
      }
      req = alarm;
    } else {
      const timer: reminderAgentManager.ReminderRequestTimer = {
        reminderType: reminderAgentManager.ReminderType.REMINDER_TYPE_TIMER,
        triggerTimeInSeconds: when.delaySec,
        title: title,
        content: content,
        actionButton: [
          { title: 'Done', type: reminderAgentManager.ActionButtonType.ACTION_BUTTON_TYPE_CLOSE }
        ],
        wantAgent: { pkgName: bundle, abilityName: 'EntryAbility', parameters: params },
        ringDuration: 3,
        notificationId: TilesPlatform.idFor('reminder:' + key)
      };
      req = timer;
    }
    Reminders.lastWasInApp = false;
    try {
      const id: number = await reminderAgentManager.publishReminder(req);
      Reminders.remember(tile.id, id);
      TLog.info('reminder ' + id + ' scheduled for ' + PARAM_TILE_ID + '=' + tile.id + ' at ' + when.label());
      return id;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      TLog.warn('publishReminder failed: ' + err.code + ' ' + err.message);
      // Fallback (labelled): an in-app timer that publishes a Notification Kit notification while Tiles runs.
      return Reminders.scheduleInApp(tile, when, key, title, content) ? REMINDER_IN_APP : -1;
    }
  }

  private static fallbackTimers: Map<string, number> = new Map<string, number>();

  /** True when the last schedule() fell back to the in-app timer. */
  static lastWasInApp: boolean = false;

  private static scheduleInApp(tile: TileSpec, when: ReminderWhen, key: string, title: string,
    content: string): boolean {
    let ms: number = 0;
    if (when.isClock()) {
      const now: Date = new Date();
      const at: Date = new Date(now.getFullYear(), now.getMonth(), now.getDate(), when.hour, when.minute, 0, 0);
      let delta: number = at.getTime() - now.getTime();
      if (delta <= 0) {
        delta += 24 * 3600 * 1000;
      }
      if (when.dayOfWeek > 0) {
        const today: number = now.getDay() === 0 ? 7 : now.getDay();
        let days: number = (when.dayOfWeek - today + 7) % 7;
        if (days === 0 && at.getTime() <= now.getTime()) {
          days = 7;
        }
        delta = at.getTime() - now.getTime() + days * 24 * 3600 * 1000;
      }
      ms = delta;
    } else {
      ms = when.delaySec * 1000;
    }
    if (!(ms > 0) || ms > 7 * 24 * 3600 * 1000) {
      return false;
    }
    const prev: number | undefined = Reminders.fallbackTimers.get(key);
    if (prev !== undefined) {
      clearTimeout(prev);
    }
    const tileId: string = tile.id;
    const timer: number = setTimeout(() => {
      Reminders.fallbackTimers.delete(key);
      TileNotifications.notifyTile(tileId, title, content);
    }, ms);
    Reminders.fallbackTimers.set(key, timer);
    Reminders.lastWasInApp = true;
    TLog.info('in-app reminder for ' + key + ' in ' + Math.round(ms / 1000).toString() + ' s');
    return true;
  }

  private static clearInApp(tileId: string, key: string): void {
    const keys: string[] = key.length > 0 ? [key] : [tileId + ':clock', tileId + ':countdown'];
    for (const k of keys) {
      const t: number | undefined = Reminders.fallbackTimers.get(k);
      if (t !== undefined) {
        clearTimeout(t);
        Reminders.fallbackTimers.delete(k);
      }
    }
  }

  /** Cancels every valid reminder this app scheduled for the tile. */
  static async cancelForTile(tileId: string): Promise<void> {
    await Reminders.cancelMatching(tileId, '');
    Reminders.forget(tileId);
  }

  /** Cancels only the tile's countdown reminder (e.g. a paused focus timer). */
  static async cancelCountdown(tileId: string): Promise<void> {
    await Reminders.cancelMatching(tileId, tileId + ':countdown');
  }

  /** Cancels the tile's reminders; with a non-empty `key` only those scheduled with that reminderKey. */
  private static async cancelMatching(tileId: string, key: string): Promise<void> {
    Reminders.clearInApp(tileId, key);
    try {
      const all: reminderAgentManager.ReminderInfo[] = await reminderAgentManager.getAllValidReminders();
      for (const r of all) {
        const p: Record<string, Object> | undefined =
          r.reminderReq.wantAgent !== undefined ? r.reminderReq.wantAgent.parameters : undefined;
        if (p !== undefined && p['tileId'] === tileId && (key.length === 0 || p['reminderKey'] === key)) {
          await reminderAgentManager.cancelReminder(r.reminderId);
        }
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      TLog.warn('cancel reminders failed: ' + err.code);
    }
  }

  /** Number of reminders currently scheduled by Tiles (system state). */
  static async count(): Promise<number> {
    try {
      const all: reminderAgentManager.ReminderInfo[] = await reminderAgentManager.getAllValidReminders();
      return all.length;
    } catch (e) {
      return 0;
    }
  }

  private static remember(tileId: string, id: number): void {
    const m: Record<string, number> = Reminders.map();
    m[tileId] = id;
    AppStorage.setOrCreate<string>(PlatformKeys.REMINDERS, JSON.stringify(m));
  }

  private static forget(tileId: string): void {
    const m: Record<string, number> = Reminders.map();
    if (m[tileId] !== undefined) {
      const out: Record<string, number> = {};
      for (const k of Object.keys(m)) {
        if (k !== tileId) {
          out[k] = m[k];
        }
      }
      AppStorage.setOrCreate<string>(PlatformKeys.REMINDERS, JSON.stringify(out));
    }
  }

  private static map(): Record<string, number> {
    const raw: string | undefined = AppStorage.get<string>(PlatformKeys.REMINDERS);
    if (raw === undefined || raw.length === 0) {
      return {};
    }
    try {
      return JSON.parse(raw) as Record<string, number>;
    } catch (e) {
      return {};
    }
  }
}
