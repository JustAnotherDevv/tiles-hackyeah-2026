import { describe, it, expect } from '@ohos/hypium';
import { PostureStats } from '../main/ets/model/Models';
import {
  AppSettings,
  DEFAULT_BASE_URL,
  LIVE_STALE_MS,
  PREFS_NAME,
  PREFS_NAME_KV,
  PREFS_NAME_SHARED,
  SNAPSHOT_SAVE_MIN_MS,
  STORE_SETTINGS,
  STORE_SHARED,
  WIDGET_LIVE,
  WIDGET_MOCK,
  WIDGET_OFFLINE,
  WidgetSnapshot,
  buildSnapshot,
  isHttpUrl,
  markOffline,
  parseIdList,
  parseSnapshot,
  prefsFileName,
  shouldSaveSnapshot,
  snapshotKey
} from '../main/ets/platform/PocketPersist';

function stats(source: string, updatedAtMs: number): PostureStats {
  const s: PostureStats = new PostureStats();
  s.source = source;
  s.updatedAtMs = updatedAtMs;
  s.blocked = 5;
  s.redacted = 9;
  s.budgetUsedPct = 40;
  return s;
}

// Host-side tests for the persistence rules behind SettingsStore / WidgetBridge / BackgroundRefresh (WP-4).
export default function pocketPersistTest() {
  describe('PocketPersist', () => {
    it('sanitizeKeepsValidSettings', 0, () => {
      const s: AppSettings = AppSettings.sanitize('live', ' https://gw.example:8787 ', 'u_marek');
      expect(s.mode).assertEqual('live');
      expect(s.baseUrl).assertEqual('https://gw.example:8787');
      expect(s.persona).assertEqual('u_marek');
    });

    it('sanitizeReplacesGarbage', 0, () => {
      const s: AppSettings = AppSettings.sanitize('foo', 'garbage', 'u_nobody');
      expect(s.mode).assertEqual('mock');
      expect(s.baseUrl).assertEqual(DEFAULT_BASE_URL);
      expect(s.persona).assertEqual('u_emily');
      expect(AppSettings.sanitize('', '', '').baseUrl).assertEqual(DEFAULT_BASE_URL);
    });

    it('httpUrlRules', 0, () => {
      expect(isHttpUrl('http://10.0.2.2:8787')).assertTrue();
      expect(isHttpUrl('http://')).assertFalse();
      expect(isHttpUrl('https:///api')).assertFalse();
      expect(isHttpUrl('ftp://host')).assertFalse();
      expect(isHttpUrl('http://ho st')).assertFalse();
    });

    it('prefsFileSelection', 0, () => {
      expect(prefsFileName(STORE_SETTINGS, true)).assertEqual(PREFS_NAME_KV);
      expect(prefsFileName(STORE_SHARED, true)).assertEqual(PREFS_NAME_KV);
      expect(prefsFileName(STORE_SETTINGS, false)).assertEqual(PREFS_NAME);
      expect(prefsFileName(STORE_SHARED, false)).assertEqual(PREFS_NAME_SHARED);
    });

    it('idListSkipsEmpty', 0, () => {
      expect(parseIdList('').length).assertEqual(0);
      expect(parseIdList('a,,b').length).assertEqual(2);
    });

    it('emptyOrCorruptSnapshotHasNoNumbers', 0, () => {
      const empty: WidgetSnapshot = parseSnapshot('', 'mock');
      expect(empty.hasData).assertFalse();
      expect(empty.pending).assertEqual(0);
      expect(empty.mode).assertEqual(WIDGET_MOCK);
      const corrupt: WidgetSnapshot = parseSnapshot('{"pending":', 'live');
      expect(corrupt.hasData).assertFalse();
      expect(corrupt.pending).assertEqual(0);
      expect(corrupt.mode).assertEqual(WIDGET_LIVE);
      expect(parseSnapshot('null', 'mock').hasData).assertFalse();
      expect(parseSnapshot('[1,2]', 'mock').hasData).assertFalse();
    });

    it('legacySnapshotWithoutHasDataIsIgnored', 0, () => {
      const legacy: string = '{"pending":3,"blocked":37,"redacted":212,"budgetLeftPct":63,"spendToday":"$148",' +
        '"topRequest":"Buy MarketPulse Pro ($50)","mode":"MOCK","updated":"--:--"}';
      const s: WidgetSnapshot = parseSnapshot(legacy, 'mock');
      expect(s.hasData).assertFalse();
      expect(s.pending).assertEqual(0);
    });

    it('snapshotRoundTripAndModeMismatch', 0, () => {
      const built: WidgetSnapshot = buildSnapshot(stats('mock', 1000), 2, 'Buy X ($5)', '$10', false, 2000);
      const json: string = JSON.stringify(built);
      const back: WidgetSnapshot = parseSnapshot(json, 'mock');
      expect(back.hasData).assertTrue();
      expect(back.pending).assertEqual(2);
      expect(back.budgetLeftPct).assertEqual(60);
      // Mock data must not be shown under a LIVE label after switching to live.
      const switched: WidgetSnapshot = parseSnapshot(json, 'live');
      expect(switched.hasData).assertFalse();
      expect(switched.mode).assertEqual(WIDGET_LIVE);
    });

    it('badFieldTypesRejected', 0, () => {
      const bad: string = '{"hasData":true,"pending":"3","blocked":1,"redacted":1,"budgetLeftPct":1,' +
        '"spendToday":"$1","topRequest":"x","mode":"MOCK","updated":"10:00"}';
      expect(parseSnapshot(bad, 'mock').hasData).assertFalse();
    });

    it('buildWithoutRepoDataIsEmpty', 0, () => {
      const s: WidgetSnapshot = buildSnapshot(stats('live', 0), 0, '', '$0', false, 5000);
      expect(s.hasData).assertFalse();
      expect(s.mode).assertEqual(WIDGET_LIVE);
    });

    it('buildFailedOrStaleIsOffline', 0, () => {
      expect(buildSnapshot(stats('live', 1000), 1, 't', '$1', true, 2000).mode).assertEqual(WIDGET_OFFLINE);
      expect(buildSnapshot(stats('live', 1000), 1, 't', '$1', false, 1000 + LIVE_STALE_MS + 1).mode)
        .assertEqual(WIDGET_OFFLINE);
      expect(buildSnapshot(stats('live', 1000), 1, 't', '$1', false, 2000).mode).assertEqual(WIDGET_LIVE);
      // Mock mode is never OFFLINE.
      expect(buildSnapshot(stats('mock', 1000), 1, 't', '$1', true, 2000).mode).assertEqual(WIDGET_MOCK);
    });

    it('markOfflineKeepsLastGoodData', 0, () => {
      const live: WidgetSnapshot = buildSnapshot(stats('live', 1000), 4, 't', '$1', false, 2000);
      const off: WidgetSnapshot = markOffline(live);
      expect(off.mode).assertEqual(WIDGET_OFFLINE);
      expect(off.pending).assertEqual(4);
      expect(live.mode).assertEqual(WIDGET_LIVE);
      expect(parseSnapshot(JSON.stringify(off), 'live').mode).assertEqual(WIDGET_OFFLINE);
    });

    it('snapshotSaveThrottle', 0, () => {
      const a: WidgetSnapshot = buildSnapshot(stats('mock', 1000), 1, 't', '$1', false, 2000);
      const b: WidgetSnapshot = buildSnapshot(stats('mock', 1000), 2, 't', '$1', false, 2000);
      expect(shouldSaveSnapshot(snapshotKey(a), snapshotKey(a), 0, SNAPSHOT_SAVE_MIN_MS - 1)).assertFalse();
      expect(shouldSaveSnapshot(snapshotKey(a), snapshotKey(a), 0, SNAPSHOT_SAVE_MIN_MS)).assertTrue();
      expect(shouldSaveSnapshot(snapshotKey(a), snapshotKey(b), 0, 1)).assertTrue();
    });
  });
}
