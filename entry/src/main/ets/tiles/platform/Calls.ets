import { call } from '@kit.TelephonyKit';
import { common, Want } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { TilesPlatform, TLog } from './TilesPlatform';

/**
 * Demo contacts. Fictional numbers (555-01xx range) — no real personal data. A TileAction 'call' arg may be
 * a contact name ("Kasia") or a phone number.
 */
const DEMO_CONTACTS: Record<string, string> = {
  'kasia': '+48 555 010 101',
  'mum': '+48 555 010 102',
  'mama': '+48 555 010 102',
  'mom': '+48 555 010 102',
  'dad': '+48 555 010 103',
  'tata': '+48 555 010 103',
  'ola': '+48 555 010 104',
  'kuba': '+48 555 010 105',
  'tomek': '+48 555 010 106',
  'babcia': '+48 555 010 107',
  'grandma': '+48 555 010 107',
  'halina': '+48 555 010 107',
  'caregiver': '+48 555 010 101'
};

/**
 * Calls open the system dial screen with the number filled in (Telephony Kit `call.makeCall`, no CALL_PHONE
 * permission: the user presses the call button). Fallback: start the dialer with a Want
 * (action 'ohos.want.action.dial', uri 'tel:<n>'). If neither is available (some emulators), a labelled toast.
 */
export class Calls {
  static numberFor(arg: string, fallbackName: string = ''): string {
    const a: string = arg.trim();
    if (new RegExp('\\d{3,}').test(a.replace(new RegExp('[\\s\\-]', 'g'), ''))) {
      return a;
    }
    const keys: string[] = [a.toLowerCase(), fallbackName.toLowerCase()];
    for (const k of keys) {
      for (const name of Object.keys(DEMO_CONTACTS)) {
        if (k.length > 0 && (k === name || k.indexOf(name) >= 0)) {
          return DEMO_CONTACTS[name];
        }
      }
    }
    return DEMO_CONTACTS['caregiver'];
  }

  /** Opens the dial screen for `who` (name or number). Resolves true if the dialer opened. */
  static async dial(who: string, displayName: string = ''): Promise<boolean> {
    const num: string = Calls.numberFor(who, displayName);
    const digits: string = num.replace(new RegExp('[\\s\\-()]', 'g'), '');
    const name: string = displayName.length > 0 ? displayName : who;
    const ctx: common.UIAbilityContext | null = TilesPlatform.context();
    try {
      if (ctx !== null) {
        await call.makeCall(ctx, digits);
      } else {
        await call.makeCall(digits);
      }
      TLog.info('dial screen opened');
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      TLog.warn('makeCall failed: ' + err.code + ' ' + err.message);
    }
    if (ctx !== null) {
      try {
        const want: Want = { action: 'ohos.want.action.dial', uri: 'tel:' + digits };
        await ctx.startAbility(want);
        TLog.info('dialer opened via want');
        return true;
      } catch (e) {
        const err: BusinessError = e as BusinessError;
        TLog.warn('dial want failed: ' + err.code + ' ' + err.message);
      }
    }
    TilesPlatform.toast('Calling ' + name + ' (' + num + ') — no dialer on this device');
    return false;
  }
}
