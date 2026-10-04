import { i18n } from '@kit.LocalizationKit';

function pad2(v: number): string {
  return v < 10 ? '0' + v.toString() : v.toString();
}

/**
 * Device-local clock time for "now"-derived labels ("Taken at …", "Added … at …"), following the system
 * 12/24-hour setting so the app matches the status bar (e.g. "1:33 PM" when the status bar shows 01:33).
 */
export function clockLabel(d: Date): string {
  let is24: boolean = true;
  try {
    is24 = i18n.System.is24HourClock();
  } catch (e) {
    is24 = true;
  }
  const h: number = d.getHours();
  const m: string = pad2(d.getMinutes());
  if (is24) {
    return h.toString() + ':' + m;
  }
  const h12: number = h % 12 === 0 ? 12 : h % 12;
  return h12.toString() + ':' + m + (h < 12 ? ' AM' : ' PM');
}
