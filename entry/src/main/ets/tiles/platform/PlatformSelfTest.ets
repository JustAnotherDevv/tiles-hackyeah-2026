import { TileAction, TileSpec } from '../model/Tile';
import { TileStore } from '../data/TileStore';
import { seedTilesFor } from '../data/SeedTiles';
import { Reminders, ReminderWhen } from './Reminders';
import { TileActions } from './TileActions';
import { TileNotifications } from './TileNotifications';
import { TLog } from './TilesPlatform';

/**
 * Developer self-test for the platform layer, triggered only by a launch parameter (never from the UI):
 *   hdc shell aa start -a EntryAbility -b <bundle> --ps tilesDebug notify      (caregiver + guardian notifications)
 *   hdc shell aa start -a EntryAbility -b <bundle> --ps tilesDebug remind      (pills reminders: +15 s and daily 8:00; -2 = in-app fallback)
 *   hdc shell aa start -a EntryAbility -b <bundle> --ps tilesDebug action:<tileId>:<kind>:<arg>
 * Results go to hilog (tag TilesPlatform). Uses the seeded demo data only.
 */
export class PlatformSelfTest {
  static run(cmd: string): void {
    TLog.info('selftest ' + cmd);
    if (cmd === 'notify') {
      PlatformSelfTest.notify();
    } else if (cmd === 'remind') {
      PlatformSelfTest.remind();
    } else if (cmd.startsWith('action:')) {
      PlatformSelfTest.action(cmd.substring(7));
    }
  }

  private static seniorPills(): TileSpec {
    for (const t of seedTilesFor('senior')) {
      if (t.type === 'pills') {
        return t;
      }
    }
    return new TileSpec();
  }

  private static async notify(): Promise<void> {
    const ok: boolean = await TileNotifications.requestPermission(false);
    TLog.info('selftest notifications enabled=' + ok);
    const pills: TileSpec = PlatformSelfTest.seniorPills();
    const a: boolean = await TileNotifications.caregiverAlert('Kasia', 'Halina took her 8:00 pills',
      'Marked at 8:02 on Halina\'s Tiles', pills.id, 'done:' + pills.id);
    const b: boolean = await TileNotifications.caregiverAlert('Kasia', 'Guardian: Mum may be on a scam call',
      'Asks for money, pressure to act right now. Demo call.', 'sr-guardian', 'guardian');
    const c: boolean = await TileNotifications.notifyTile(pills.id, 'Pills 8:00', 'Time for your morning pills.');
    TLog.info('selftest published caregiver=' + a + ' guardian=' + b + ' tile=' + c);
  }

  private static async remind(): Promise<void> {
    await TileNotifications.requestPermission(false);
    const pills: TileSpec = PlatformSelfTest.seniorPills();
    const soon: ReminderWhen = new ReminderWhen();
    soon.delaySec = 15;
    const id1: number = await Reminders.schedule(pills, soon, 'Time for your morning pills. Tap when taken.');
    const daily: ReminderWhen | null = Reminders.whenFor(pills, '');
    const id2: number = daily !== null ? await Reminders.schedule(pills, daily) : -1;
    const n: number = await Reminders.count();
    TLog.info('selftest reminders countdown=' + id1 + ' daily(' + (daily !== null ? daily.label() : '-') + ')=' + id2 +
      ' valid=' + n);
  }

  private static action(spec: string): void {
    const parts: string[] = spec.split(':');
    if (parts.length < 2) {
      return;
    }
    const t: TileSpec | null = TileStore.get().tile(parts[0]);
    if (t === null) {
      TLog.warn('selftest: no tile ' + parts[0]);
      return;
    }
    const a: TileAction = new TileAction();
    a.kind = parts[1];
    a.arg = parts.length > 2 ? parts.slice(2).join(':') : '';
    TileActions.handle(a, t);
  }
}
