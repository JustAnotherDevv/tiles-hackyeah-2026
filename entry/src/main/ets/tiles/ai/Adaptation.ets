import { Profile, Suggestion, TileSpec } from '../model/Tile';
import { cloneTile, parseTileJson, TapStat, TileStore } from '../data/TileStore';

/**
 * Adaptation engine (docs/TILES_SPEC.md): turns on-device usage signals into Suggestions that the person (or their
 * caregiver) approves before anything changes.
 *
 * Signals: TileStore.recordTap(tileId, missed) per tile (taps, missed taps, last tap time), which tiles are never
 * opened, the hour of day and the current profile settings. Rules are deterministic and run on the device; nothing
 * leaves the phone. "Simulate a day of use" (simulateDay) feeds clearly labelled DEMO taps into the same pipeline so
 * the behaviour can be shown in a 2-minute demo; the "14 unused apps" figure is demo data (an ordinary app cannot
 * read other apps' usage).
 *
 * Change strings follow TileStore.applyChange, plus 'top:<tileId>' (move a tile to the first spot), which
 * Adaptation.decide applies itself after TileStore.decideSuggestion.
 */

/** Result of applying a change to copies of the current state (before/after previews; never touches the store). */
export class PreviewState {
  profile: Profile = new Profile();
  tiles: TileSpec[] = [];
  appsHidden: boolean = false;
}

/** Input to the pure rule engine. */
export class UsageSnapshot {
  tiles: TileSpec[] = [];
  profile: Profile = new Profile();
  stats: TapStat[] = [];
  hour: number = 12;
  appsHidden: boolean = false;
  existing: Suggestion[] = [];
}

/** Demo figure for the "hide unused apps" rule (labelled as demo data in the suggestion's reason). */
export const DEMO_UNUSED_APPS: number = 14;

/** Tiles that are never suggested for removal. */
const SAFETY_TYPES: string[] = ['sos', 'guardian'];

export function copyProfile(p: Profile): Profile {
  const c: Profile = new Profile();
  c.id = p.id;
  c.name = p.name;
  c.textScale = p.textScale;
  c.highContrast = p.highContrast;
  c.readAloud = p.readAloud;
  c.columns = p.columns;
  c.caregiver = p.caregiver;
  c.caregiverRole = p.caregiverRole;
  return c;
}

function round1(v: number): number {
  return Math.round(v * 10) / 10;
}

function fmtScale(v: number): string {
  return round1(v).toString() + 'x';
}

function changeKey(change: string): string {
  const i: number = change.indexOf(':');
  return i >= 0 ? change.substring(0, i) : change;
}

/** Short human name of a tile for suggestion titles ('Pills 8:00' -> 'Pills'). */
export function shortName(t: TileSpec): string {
  switch (t.type) {
    case 'pills':
      return 'Pills';
    case 'homework':
      return 'Homework';
    case 'commute':
      return t.title.split(' in ')[0];
    default:
      return t.title;
  }
}

function suggestion(id: string, title: string, detail: string, change: string, reason: string): Suggestion {
  const s: Suggestion = new Suggestion();
  s.id = id;
  s.title = title;
  s.detail = detail;
  s.change = change;
  s.reason = reason;
  s.status = 'pending';
  return s;
}

function statOf(stats: TapStat[], id: string): TapStat | null {
  for (const x of stats) {
    if (x.tileId === id) {
      return x;
    }
  }
  return null;
}

export class Adaptation {
  /**
   * Pure rules: usage snapshot -> new suggestions. Skips anything already decided (same id) or already pending with
   * the same kind of change (e.g. a seeded 'textScale:' suggestion), so re-running never nags.
   */
  static suggest(u: UsageSnapshot): Suggestion[] {
    const out: Suggestion[] = [];
    const known: string[] = [];
    const pendingKeys: string[] = [];
    for (const s of u.existing) {
      known.push(s.id);
      if (s.status === 'pending') {
        pendingKeys.push(changeKey(s.change) === 'hide' ? s.change : changeKey(s.change));
      }
    }
    const allow = (id: string, change: string): boolean => {
      const k: string = changeKey(change) === 'hide' ? change : changeKey(change);
      return known.indexOf(id) < 0 && pendingKeys.indexOf(k) < 0;
    };
    const p: Profile = u.profile;
    const who: string = p.name.length > 0 ? p.name : 'You';

    let missed: number = 0;
    let repeats: number = 0;
    for (const st of u.stats) {
      missed += st.missed;
      if (st.taps >= 2) {
        repeats++;
      }
    }

    // 1. Missed taps -> bigger text (and with it, bigger buttons).
    if (missed >= 5 && p.textScale < 1.95) {
      const target: number = Math.min(2.0, round1(p.textScale * 1.4));
      const pct: number = Math.round((target / p.textScale - 1) * 100);
      const change: string = 'textScale:' + target.toString();
      if (pct > 0 && allow('ad-text', change)) {
        out.push(suggestion('ad-text', 'Make text ' + pct.toString() + '% bigger',
          'Text grows from ' + fmtScale(p.textScale) + ' to ' + fmtScale(target) + '; buttons grow with it.',
          change, missed.toString() + ' missed taps today, mostly on small buttons'));
      }
    }

    // 2. Biggest single trouble spot: a small tile that keeps being missed gets bigger.
    let worst: TileSpec | null = null;
    let worstMissed: number = 0;
    for (const t of u.tiles) {
      const st: TapStat | null = statOf(u.stats, t.id);
      if (st !== null && t.size === '1x1' && st.missed > worstMissed) {
        worst = t;
        worstMissed = st.missed;
      }
    }
    if (worst !== null && worstMissed >= 3) {
      const w: TileSpec = worst as TileSpec;
      const change: string = 'size:' + w.id + ':2x1';
      if (allow('ad-size-' + w.id, change)) {
        out.push(suggestion('ad-size-' + w.id, 'Make ' + shortName(w) + ' twice as wide',
          'The ' + shortName(w) + ' tile becomes a wide tile with a bigger button.', change,
          worstMissed.toString() + ' taps landed just outside it today'));
      }
    }

    // 3. Read aloud.
    if (!p.readAloud && (missed >= 8 || p.id === 'senior' || p.id === 'lowvision')) {
      if (allow('ad-read', 'readAloud:on')) {
        out.push(suggestion('ad-read', 'Read tiles aloud', 'Tiles speaks each tile when it is opened.',
          'readAloud:on', missed.toString() + ' missed taps and ' + repeats.toString() +
            ' tiles opened again and again: hearing the tile confirms the right one was tapped'));
      }
    }

    // 4. Unused apps (demo figure, labelled).
    if (!u.appsHidden && u.stats.length > 0 && allow('ad-apps', 'hide:apps')) {
      out.push(suggestion('ad-apps', 'Hide ' + DEMO_UNUSED_APPS.toString() + ' unused apps',
        'The home shows only ' + who + '\'s tiles; other apps stay in the app drawer.', 'hide:apps',
        'Demo usage data: ' + DEMO_UNUSED_APPS.toString() + ' apps not opened in 30 days'));
    }

    // 5. Time of day: the tile opened most this morning moves to the first spot.
    if (u.hour >= 5 && u.hour < 12 && u.tiles.length > 1) {
      let best: TileSpec | null = null;
      let bestTaps: number = 0;
      for (const t of u.tiles) {
        const st: TapStat | null = statOf(u.stats, t.id);
        if (st !== null && st.taps > bestTaps) {
          best = t;
          bestTaps = st.taps;
        }
      }
      if (best !== null && bestTaps >= 3 && u.tiles[0].id !== (best as TileSpec).id) {
        const b: TileSpec = best as TileSpec;
        const change: string = 'top:' + b.id;
        if (allow('ad-top-' + b.id, change)) {
          out.push(suggestion('ad-top-' + b.id, 'Move ' + shortName(b) + ' to the top in the morning',
            shortName(b) + ' becomes the first tile, where ' + who + ' looks first after waking up.', change,
            'Opened ' + bestTaps.toString() + ' times this morning, always first'));
        }
      }
    }

    // 6. A tile that is never opened (safety tiles are never suggested).
    if (u.stats.length >= 2) {
      for (let i = u.tiles.length - 1; i >= 0; i--) {
        const t: TileSpec = u.tiles[i];
        if (!t.pinned && SAFETY_TYPES.indexOf(t.type) < 0 && statOf(u.stats, t.id) === null &&
          u.tiles.length > 4) {
          const change: string = 'remove:' + t.id;
          if (allow('ad-unused-' + t.id, change)) {
            out.push(suggestion('ad-unused-' + t.id, 'Remove "' + t.title + '"',
              'It was not opened all day; the assistant can bring it back any time.', change,
              'Not opened today'));
          }
          break;
        }
      }
    }
    return out;
  }

  /** Snapshot of the live store for the rules. */
  static snapshot(hour: number): UsageSnapshot {
    const st: TileStore = TileStore.get();
    const u: UsageSnapshot = new UsageSnapshot();
    u.tiles = st.tiles();
    u.profile = st.profile();
    u.stats = st.tapStats();
    u.hour = hour;
    u.appsHidden = st.appsHidden();
    u.existing = st.suggestions();
    return u;
  }

  /** Runs the rules on the live store and adds new suggestions. Returns how many were added. */
  static refresh(hour?: number): number {
    const h: number = hour !== undefined ? hour : new Date().getHours();
    const list: Suggestion[] = Adaptation.suggest(Adaptation.snapshot(h));
    if (list.length > 0) {
      TileStore.get().addSuggestions(list);
    }
    return list.length;
  }

  /**
   * DEMO: feeds one simulated day of use into TileStore.recordTap (11 missed taps on the smallest targets, the
   * morning tile opened first 4 times, a call tile twice, the rest untouched), then runs the rules for a morning
   * hour. Returns a one-line summary for a toast.
   */
  static simulateDay(): string {
    const st: TileStore = TileStore.get();
    const tiles: TileSpec[] = st.tiles();
    if (tiles.length === 0) {
      return 'Simulated day: no tiles on the home yet';
    }
    // Morning tile: pills, else commute, else homework, else the second tile.
    let morning: TileSpec | null = null;
    const prefs: string[] = ['pills', 'commute', 'homework'];
    for (const type of prefs) {
      if (morning === null) {
        for (const t of tiles) {
          if (morning === null && t.type === type) {
            morning = t;
          }
        }
      }
    }
    if (morning === null) {
      morning = tiles.length > 1 ? tiles[1] : tiles[0];
    }
    const m: TileSpec = morning as TileSpec;
    for (let i = 0; i < 4; i++) {
      st.recordTap(m.id, false);
    }
    // Missed taps: small (1x1) tiles first, then tiles with buttons.
    const targets: TileSpec[] = [];
    for (const t of tiles) {
      if (t.size === '1x1' && t.type === 'sos') {
        targets.push(t);
      }
    }
    for (const t of tiles) {
      if (t.size === '1x1' && t.type !== 'sos') {
        targets.push(t);
      }
    }
    for (const t of tiles) {
      if (targets.length < 3 && t.size !== '1x1' && t.id !== m.id) {
        targets.push(t);
      }
    }
    if (targets.length === 0) {
      targets.push(m);
    }
    const MISSED: number = 11;
    // The first target takes the most misses (4), the rest are spread round-robin.
    for (let i = 0; i < MISSED; i++) {
      const t: TileSpec = i < 4 || targets.length === 1 ? targets[0] : targets[1 + ((i - 4) % (targets.length - 1))];
      st.recordTap(t.id, true);
    }
    // A call tile is used normally twice.
    for (const t of tiles) {
      if (t.type === 'call' && t.id !== m.id) {
        st.recordTap(t.id, false);
        st.recordTap(t.id, false);
        break;
      }
    }
    let unused: number = 0;
    for (const t of st.tiles()) {
      if (st.statFor(t.id) === null) {
        unused++;
      }
    }
    const added: number = Adaptation.refresh(8);
    return 'Simulated day: ' + MISSED.toString() + ' missed taps, ' + unused.toString() + ' tiles never opened → ' +
      (added === 0 ? 'no new suggestions' : added.toString() + (added === 1 ? ' new suggestion' : ' new suggestions'));
  }

  /** Approve/decline a suggestion. Approve applies it (incl. 'top:<tileId>', which TileStore does not handle). */
  static decide(id: string, approve: boolean): void {
    const st: TileStore = TileStore.get();
    let change: string = '';
    for (const s of st.suggestions()) {
      if (s.id === id && s.status === 'pending') {
        change = s.change;
      }
    }
    st.decideSuggestion(id, approve);
    if (approve && change.startsWith('top:')) {
      const tid: string = change.substring(4);
      const list: TileSpec[] = st.tiles();
      for (let i = 0; i < list.length; i++) {
        if (list[i].id === tid && i > 0) {
          st.moveTile(i, 0);
          break;
        }
      }
    }
  }

  /** What the home would look like after a change (pure; mirrors TileStore.applyChange on copies). */
  static preview(change: string, profile: Profile, tiles: TileSpec[], appsHidden: boolean): PreviewState {
    const r: PreviewState = new PreviewState();
    r.profile = copyProfile(profile);
    r.tiles = tiles.slice();
    r.appsHidden = appsHidden;
    const sep: number = change.indexOf(':');
    const key: string = sep >= 0 ? change.substring(0, sep) : change;
    const val: string = sep >= 0 ? change.substring(sep + 1) : '';
    switch (key) {
      case 'textScale': {
        const v: number = Number(val);
        if (isFinite(v) && v > 0) {
          r.profile.textScale = Math.max(0.85, Math.min(2.0, v));
        }
        break;
      }
      case 'readAloud':
        r.profile.readAloud = val === 'on' || val === 'true';
        break;
      case 'highContrast':
        r.profile.highContrast = val === 'on' || val === 'true';
        break;
      case 'columns': {
        const c: number = Math.round(Number(val));
        if (c >= 1 && c <= 6) {
          r.profile.columns = c;
        }
        break;
      }
      case 'hide':
        if (val === 'apps') {
          r.appsHidden = true;
        } else if (val === 'unused') {
          const stats: TapStat[] = TileStore.get().tapStats();
          r.tiles = r.tiles.filter((t: TileSpec) => t.pinned || statOf(stats, t.id) !== null);
        } else if (val.length > 0) {
          r.tiles = r.tiles.filter((t: TileSpec) => t.pinned || t.type !== val);
        }
        break;
      case 'addTile': {
        const t: TileSpec | null = parseTileJson(val);
        if (t !== null) {
          r.tiles = [t as TileSpec].concat(r.tiles);
        }
        break;
      }
      case 'remove':
        r.tiles = r.tiles.filter((t: TileSpec) => t.id !== val);
        break;
      case 'size': {
        const j: number = val.lastIndexOf(':');
        if (j > 0) {
          const tid: string = val.substring(0, j);
          const size: string = val.substring(j + 1);
          const out: TileSpec[] = [];
          for (const t of r.tiles) {
            if (t.id === tid) {
              const c: TileSpec = cloneTile(t);
              c.size = size;
              out.push(c);
            } else {
              out.push(t);
            }
          }
          r.tiles = out;
        }
        break;
      }
      case 'top': {
        let idx: number = -1;
        for (let i = 0; i < r.tiles.length; i++) {
          if (r.tiles[i].id === val) {
            idx = i;
          }
        }
        if (idx > 0) {
          const moved: TileSpec[] = r.tiles.splice(idx, 1);
          r.tiles = moved.concat(r.tiles);
        }
        break;
      }
      default:
        break;
    }
    return r;
  }

  /** Tile id a change focuses on ('' if none) so previews can highlight it. */
  static focusTile(change: string): string {
    const key: string = changeKey(change);
    const val: string = change.substring(key.length + 1);
    if (key === 'top' || key === 'remove') {
      return val;
    }
    if (key === 'size') {
      const j: number = val.lastIndexOf(':');
      return j > 0 ? val.substring(0, j) : '';
    }
    return '';
  }
}
