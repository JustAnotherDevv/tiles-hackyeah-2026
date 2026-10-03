import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN: number = 0xA001;
const TAG: string = 'AegisPocket';

/** Thin hilog wrapper; follow logs with `hdc hilog | grep AegisPocket`. */
export class Log {
  static info(msg: string): void {
    hilog.info(DOMAIN, TAG, '%{public}s', msg);
  }

  static warn(msg: string): void {
    hilog.warn(DOMAIN, TAG, '%{public}s', msg);
  }

  static error(msg: string): void {
    hilog.error(DOMAIN, TAG, '%{public}s', msg);
  }
}

export class Fmt {
  static usd(v: number): string {
    if (v < 0) {
      return '-';
    }
    if (v >= 1000) {
      return '$' + (v / 1000).toFixed(1) + 'k';
    }
    if (Math.round(v) === v) {
      return '$' + v.toFixed(0);
    }
    return '$' + v.toFixed(2);
  }

  static num(v: number): string {
    if (v >= 1000000) {
      return (v / 1000000).toFixed(1) + 'M';
    }
    if (v >= 10000) {
      return (v / 1000).toFixed(1) + 'k';
    }
    return Math.round(v).toString();
  }

  static pad2(v: number): string {
    return v < 10 ? '0' + v.toString() : v.toString();
  }

  /** "14:05 left", "1h 02m left" or "expired". */
  static countdown(expiresAtMs: number, nowMs: number): string {
    if (expiresAtMs <= 0) {
      return 'no expiry';
    }
    const left: number = Math.floor((expiresAtMs - nowMs) / 1000);
    if (left <= 0) {
      return 'expired';
    }
    const h: number = Math.floor(left / 3600);
    const m: number = Math.floor((left % 3600) / 60);
    const s: number = left % 60;
    if (h > 0) {
      return h.toString() + 'h ' + Fmt.pad2(m) + 'm left';
    }
    return m.toString() + ':' + Fmt.pad2(s) + ' left';
  }

  static ago(tsMs: number, nowMs: number): string {
    const sec: number = Math.max(0, Math.floor((nowMs - tsMs) / 1000));
    if (sec < 60) {
      return sec.toString() + 's ago';
    }
    const min: number = Math.floor(sec / 60);
    if (min < 60) {
      return min.toString() + 'm ago';
    }
    const h: number = Math.floor(min / 60);
    if (h < 24) {
      return h.toString() + 'h ago';
    }
    return Math.floor(h / 24).toString() + 'd ago';
  }

  static parseIso(iso: string | null | undefined): number {
    if (iso === null || iso === undefined || iso.length === 0) {
      return 0;
    }
    const t: number = new Date(iso).getTime();
    return isNaN(t) ? 0 : t;
  }

  static isoFromMs(ms: number): string {
    return new Date(ms).toISOString();
  }
}
