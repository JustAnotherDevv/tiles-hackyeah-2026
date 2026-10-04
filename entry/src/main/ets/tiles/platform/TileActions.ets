import { Profile, TileAction, TileBlock, TileSpec } from '../model/Tile';
import { cloneTile, TileStore } from '../data/TileStore';
import { Calls } from './Calls';
import { REMINDER_IN_APP, Reminders, ReminderWhen } from './Reminders';
import { Speech } from './Speech';
import { TileHaptics } from './TileHaptics';
import { TileNotifications } from './TileNotifications';
import { PlatformKeys, TilesPlatform, TLog } from './TilesPlatform';

/** In-app routes accepted by a 'navigate' action (anything else is treated as a place for directions). */
const ROUTES: string[] = ['guardian', 'caregiver', 'settings', 'onboarding', 'assistant'];

function pad2(v: number): string {
  return v < 10 ? '0' + v.toString() : v.toString();
}

function nowHHMM(): string {
  const d: Date = new Date();
  return d.getHours().toString() + ':' + pad2(d.getMinutes());
}

/**
 * Single dispatcher for every TileAction the renderer emits: `TileActions.handle(action, tile)`.
 *
 *  call     -> Telephony dial screen (no CALL_PHONE privilege)          arg = name or number
 *  remind   -> reminderAgentManager reminder (Background Tasks Kit)     arg = "08:30" | "tue-18:00" | "15" (min) | "+30s"
 *  speak    -> read aloud (screen reader announce + speaking state)    arg = text, or '' / keyword -> tile.speakText
 *  open     -> AppStorage tiles.openTileId = tile.id (Home opens the detail)
 *  navigate -> in-app route (AppStorage tiles.navigate) or directions to a place (labelled demo)
 *  done     -> mark done (+ caregiver notification for pills: "Halina took her 8:00 pills")
 *  vote     -> record the vote on a plan tile
 *  sos      -> caregiver alert notification + dial the caregiver
 *  dismiss  -> remove the tile; on a Guardian tile = "Hang up" + caregiver alert
 *  toggle   -> checklist item (arg "<block>:<item>")                    timer -> arg start|pause|done
 * Every action gives haptic feedback. Never throws.
 */
export class TileActions {
  static handle(action: TileAction, tile: TileSpec): void {
    try {
      TileActions.dispatch(action, tile);
    } catch (e) {
      TLog.warn('action ' + action.kind + ' failed: ' + JSON.stringify(e));
    }
  }

  private static dispatch(action: TileAction, tile: TileSpec): void {
    TLog.info('action ' + action.kind + ' arg=' + action.arg + ' tile=' + tile.id);
    switch (action.kind) {
      case 'call':
        TileHaptics.tap();
        TileActions.call(action, tile);
        break;
      case 'remind':
        TileHaptics.tap();
        TileActions.remind(action, tile);
        break;
      case 'speak':
        TileActions.speak(action, tile);
        break;
      case 'open':
        TileHaptics.tap();
        TileActions.openTile(tile.id);
        break;
      case 'navigate':
        TileHaptics.tap();
        TileActions.navigate(action, tile);
        break;
      case 'done':
        TileHaptics.success();
        TileActions.done(action, tile);
        break;
      case 'vote':
        TileHaptics.success();
        TileActions.vote(action, tile);
        break;
      case 'sos':
        TileHaptics.sos();
        TileActions.sos(action, tile);
        break;
      case 'dismiss':
        TileHaptics.tap();
        TileActions.dismiss(action, tile);
        break;
      case 'toggle':
        TileHaptics.tap();
        TileActions.toggle(action, tile);
        break;
      case 'timer':
        TileActions.timer(action, tile);
        break;
      default:
        TileHaptics.tap();
        TileActions.openTile(tile.id);
        break;
    }
  }

  /** Opens a tile's detail (Home watches AppStorage `tiles.openTileId` and resets it to ''). */
  static openTile(tileId: string): void {
    AppStorage.setOrCreate<string>(PlatformKeys.OPEN_TILE_ID, '');
    AppStorage.setOrCreate<string>(PlatformKeys.OPEN_TILE_ID, tileId);
  }

  /**
   * Guardian raised an alert (e.g. the simulated scam call is shown): notify the caregiver.
   * Call from the Guardian view when a demo scam is flagged.
   */
  static guardianAlert(tile: TileSpec, reason: string = ''): void {
    TileHaptics.warning();
    const p: Profile = TileStore.get().profile();
    const who: string = TileActions.personFor(p);
    const text: string = reason.length > 0 ? reason : 'Asks for money, pressure to act right now. Demo call.';
    TileNotifications.caregiverAlert(p.caregiver, 'Guardian: ' + who + ' may be on a scam call', text, tile.id,
      'guardian');
  }

  // ---------------------------------------------------------------- actions

  private static call(action: TileAction, tile: TileSpec): void {
    const who: string = action.arg.length > 0 ? action.arg : tile.title.replace('Call ', '');
    TilesPlatform.toast('Calling ' + who + '…');
    Calls.dial(who, who);
  }

  private static remind(action: TileAction, tile: TileSpec): void {
    const when: ReminderWhen | null = Reminders.whenFor(tile, action.arg);
    if (when === null) {
      TilesPlatform.toast('No time found for this reminder');
      return;
    }
    TileNotifications.requestPermission(false).then((ok: boolean) => {
      if (!ok) {
        TilesPlatform.toast('Turn on notifications so Tiles can remind you');
        return;
      }
      Reminders.schedule(tile, when).then((id: number) => {
        if (id >= 0 || id === REMINDER_IN_APP) {
          const label: string = when.isClock() ? (when.dayOfWeek > 0 ? 'every ' : '') + when.label() :
            'in ' + when.label();
          // In-app fallback: the system reminder service refused (no agent-reminder entitlement on this build).
          TilesPlatform.toast('Reminder set ' + (when.isClock() ? 'for ' : '') + label +
            (id === REMINDER_IN_APP ? ' (while Tiles is open)' : ''));
          if (TileStore.get().profile().readAloud) {
            Speech.speak('Reminder set ' + (when.isClock() ? 'for ' : '') + label, tile.id);
          }
        } else {
          TilesPlatform.toast('Could not set the reminder');
        }
      });
    });
  }

  private static speak(action: TileAction, tile: TileSpec): void {
    // A multi-word arg is the text itself; '' or a keyword ('messages') means "read this tile".
    const text: string = action.arg.indexOf(' ') > 0 ? action.arg : TileActions.speakTextFor(tile);
    Speech.speak(text, tile.id);
  }

  /** What "read aloud" says for a tile: speakText, else title + subtitle + text blocks. */
  static speakTextFor(tile: TileSpec): string {
    if (tile.speakText.length > 0) {
      return tile.speakText;
    }
    let s: string = tile.title;
    if (tile.subtitle.length > 0) {
      s = s + '. ' + tile.subtitle;
    }
    for (const b of tile.blocks) {
      if ((b.kind === 'text' || b.kind === 'alert') && b.text.length > 0) {
        s = s + '. ' + b.text;
      }
    }
    return s;
  }

  private static navigate(action: TileAction, tile: TileSpec): void {
    const arg: string = action.arg.trim();
    if (ROUTES.indexOf(arg.toLowerCase()) >= 0) {
      AppStorage.setOrCreate<string>(PlatformKeys.NAVIGATE, '');
      AppStorage.setOrCreate<string>(PlatformKeys.NAVIGATE, arg.toLowerCase());
      return;
    }
    const place: string = arg.length > 0 ? arg : tile.subtitle;
    // Walking directions need a maps app, which the emulator does not have: labelled demo.
    TilesPlatform.toast('Directions to ' + place + ' (demo — opens Maps on a phone)');
    if (TileStore.get().profile().readAloud) {
      Speech.speak('Directions to ' + place + '. Walk to the stop, it is on your right.', tile.id);
    }
  }

  private static done(action: TileAction, tile: TileSpec): void {
    const store: TileStore = TileStore.get();
    const p: Profile = store.profile();
    const c: TileSpec = cloneTile(tile);
    const at: string = nowHHMM();
    // Tick every checklist item and fill progress.
    for (const b of c.blocks) {
      if (b.kind === 'checklist') {
        b.checked = b.items.map((x: string) => true);
      } else if (b.kind === 'progress') {
        b.progress = 1;
      }
    }
    const isPills: boolean = c.type === 'pills';
    c.subtitle = (isPills ? 'Taken at ' : 'Done at ') + at;
    store.updateTile(c);
    TilesPlatform.toast(isPills ? 'Great — marked as taken' : 'Done');
    if (p.readAloud) {
      Speech.speak(isPills ? 'Well done. I told ' + (p.caregiver.length > 0 ? p.caregiver : 'your family') + '.' :
        'Done.', tile.id);
    }
    // Caregiver alert: "Halina took her 8:00 pills".
    if (p.caregiver.length > 0 && (isPills || c.type === 'homework' || c.type === 'sos')) {
      const when: ReminderWhen | null = Reminders.whenFor(tile, '');
      const slot: string = when !== null && when.isClock() ? when.label() + ' ' : '';
      const what: string = isPills ? (tile.title.toLowerCase().indexOf('drop') >= 0 ? 'eye drops' : 'pills') :
        tile.title.toLowerCase();
      const text: string = isPills ? p.name + ' took ' + TileActions.possessive(p) + ' ' + slot + what :
        p.name + ' finished: ' + what;
      TileNotifications.caregiverAlert(p.caregiver, text, 'Marked at ' + at + ' on ' + p.name + "'s Tiles", tile.id,
        'done:' + tile.id);
    }
    if (isPills) {
      TileNotifications.cancelForTile(tile.id);
    }
  }

  private static vote(action: TileAction, tile: TileSpec): void {
    const choice: string = action.arg.length > 0 ? action.arg : action.label;
    const c: TileSpec = cloneTile(tile);
    for (const b of c.blocks) {
      if (b.kind === 'list') {
        b.items = b.items.map((it: string) => TileActions.bumpVote(it, choice));
      }
      for (const a of b.actions) {
        if (a.kind === 'vote' && a.arg === choice) {
          a.label = 'Voted ' + choice + ' ✓';
        }
      }
    }
    c.subtitle = 'You voted ' + choice;
    TileStore.get().updateTile(c);
    TilesPlatform.toast('Vote for ' + choice + ' shared with the group (demo)');
  }

  /** "Veganda · ~62 zł · 2 votes" + vote for Veganda -> "... · 3 votes"; adds "· 1 vote" when absent. */
  private static bumpVote(item: string, choice: string): string {
    if (!item.toLowerCase().startsWith(choice.toLowerCase())) {
      return item;
    }
    const m: RegExpMatchArray | null = item.match(new RegExp('(\\d+) votes?'));
    if (m === null) {
      return item + ' · 1 vote';
    }
    const n: number = parseInt(m[1]) + 1;
    return item.replace(m[0], n.toString() + ' votes');
  }

  private static sos(action: TileAction, tile: TileSpec): void {
    const p: Profile = TileStore.get().profile();
    const who: string = action.arg.length > 0 ? action.arg : (p.caregiver.length > 0 ? p.caregiver : 'caregiver');
    TileNotifications.caregiverAlert(who, 'SOS from ' + (p.name.length > 0 ? p.name : 'Tiles'),
      p.name + ' asked for help at ' + nowHHMM() + '. Calling you now. (demo, no location sent)', tile.id, 'sos');
    Speech.speak('Calling ' + who + ' for help.', tile.id);
    Calls.dial(who, who);
  }

  private static dismiss(action: TileAction, tile: TileSpec): void {
    if (tile.type === 'guardian') {
      // "Hang up" on the simulated scam call: tell the caregiver, keep the Guardian tile.
      const p: Profile = TileStore.get().profile();
      TileActions.guardianAlert(tile, TileActions.personFor(p) + ' hung up on a suspicious demo call (asks for money, ' +
        'pressure to act now).');
      const c: TileSpec = cloneTile(tile);
      c.subtitle = 'You hung up at ' + nowHHMM() + ' · ' + (p.caregiver.length > 0 ? p.caregiver : 'family') +
        ' knows';
      TileStore.get().updateTile(c);
      TilesPlatform.toast('Call ended. ' + (p.caregiver.length > 0 ? p.caregiver + ' knows.' : 'You are safe.'));
      if (p.readAloud) {
        Speech.speak('Good. You hung up. ' + (p.caregiver.length > 0 ? p.caregiver + ' already knows.' : ''), tile.id);
      }
      return;
    }
    Reminders.cancelForTile(tile.id);
    TileNotifications.cancelForTile(tile.id);
    TileStore.get().removeTile(tile.id);
    TilesPlatform.toast('Tile removed');
  }

  private static toggle(action: TileAction, tile: TileSpec): void {
    const parts: string[] = action.arg.split(':');
    if (parts.length !== 2) {
      return;
    }
    const bi: number = parseInt(parts[0]);
    const ii: number = parseInt(parts[1]);
    if (isNaN(bi) || isNaN(ii)) {
      return;
    }
    const store: TileStore = TileStore.get();
    store.toggleCheck(tile.id, bi, ii);
    // All items ticked on a pills / homework tile counts as done.
    const t: TileSpec | null = store.tile(tile.id);
    if (t !== null && bi < t.blocks.length) {
      const bl: TileBlock = t.blocks[bi];
      const all: boolean = bl.checked.length > 0 && bl.checked.every((v: boolean) => v);
      if (all && (t.type === 'pills' || t.type === 'homework')) {
        const a: TileAction = new TileAction();
        a.kind = 'done';
        TileActions.done(a, t);
      }
    }
  }

  private static timer(action: TileAction, tile: TileSpec): void {
    if (action.arg === 'start') {
      TileHaptics.tap();
      const minutes: number = TileActions.timerMinutes(tile);
      if (minutes > 0) {
        // System countdown reminder: rings even if the app is closed while the timer runs.
        const w: ReminderWhen = new ReminderWhen();
        w.delaySec = minutes * 60;
        Reminders.schedule(tile, w, 'Focus time is over. Take a break!');
      }
    } else if (action.arg === 'pause') {
      TileHaptics.tap();
      Reminders.cancelCountdown(tile.id);
    } else if (action.arg === 'done') {
      TileHaptics.success();
      Reminders.cancelCountdown(tile.id);
      TilesPlatform.toast('Focus time done — take a break');
      const p: Profile = TileStore.get().profile();
      if (p.readAloud) {
        Speech.speak('Focus time is over. Take a break.', tile.id);
      }
    }
  }

  private static timerMinutes(tile: TileSpec): number {
    for (const b of tile.blocks) {
      if (b.kind === 'timer' && !b.value.startsWith('at:')) {
        const m: RegExpMatchArray | null = b.value.match(new RegExp('^(\\d{1,3})'));
        if (m !== null) {
          return parseInt(m[1]);
        }
      }
    }
    return 0;
  }

  /** How a caregiver refers to the person: Kasia's "Mum", Mum's "Zosia", else the name. */
  private static personFor(p: Profile): string {
    if (p.caregiverRole === 'daughter' || p.caregiverRole === 'son') {
      return 'Mum';
    }
    return p.name.length > 0 ? p.name : 'Your family member';
  }

  private static possessive(p: Profile): string {
    return p.id === 'lowvision' || p.id === 'everyday' ? 'his' : 'her';
  }
}
