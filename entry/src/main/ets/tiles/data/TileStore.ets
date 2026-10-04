import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { ComposeResult, Profile, Suggestion, TileAction, TileBlock, TileSpec } from '../model/Tile';
import { profileFor, seedSuggestionsFor, seedTilesFor, PROFILE_IDS } from './SeedTiles';
import { WidgetBridge } from '../../platform/WidgetBridge';

/**
 * Single source of truth for the Tiles home (docs/TILES_SPEC.md).
 *
 * Every mutation publishes a NEW array/object to AppStorage, so views can bind with
 *   @StorageLink('tiles.list') tiles: TileSpec[] = [];      @StorageLink('tiles.profile') profile: Profile = ...;
 *   @StorageLink('tiles.pending') pending: TileSpec[] = []; @StorageLink('tiles.suggestions') ...;
 *   @StorageProp('tiles.rev') rev: number = 0   (bumped on every change)
 * Views must not mutate those arrays in place; call the store.
 *
 * Persistence: ArkData Preferences file 'tiles_store' (on-device only), JSON per key; each profile keeps its own
 * tile list ('tiles.list.<profileId>') so switching profiles regenerates that person's home. Before init(ctx) the
 * store works in memory (seeded), so previews and early callers never crash.
 */

export const K_LIST: string = 'tiles.list';
export const K_PROFILE: string = 'tiles.profile';
export const K_SUGGESTIONS: string = 'tiles.suggestions';
export const K_PENDING: string = 'tiles.pending';
export const K_PENDING_REPLY: string = 'tiles.pendingReply';
export const K_ONBOARDED: string = 'tiles.onboarded';
export const K_HIDE_APPS: string = 'tiles.hideApps';
export const K_REV: string = 'tiles.rev';

const PREFS_FILE: string = 'tiles_store';
const DOMAIN: number = 0x7001;
const TAG: string = 'TileStore';

/** Per-tile usage signals for Adaptation.ets. */
export class TapStat {
  tileId: string = '';
  taps: number = 0;
  missed: number = 0;
  lastTapAt: number = 0;
}

class SavedState {
  profile: Profile = new Profile();
  suggestions: Suggestion[] = [];
  pending: TileSpec[] = [];
  onboarded: boolean = false;
}

// ---------- normalization (persisted / generated JSON -> class instances with every field set) ----------

function s(v: string | undefined | null, d: string): string {
  return typeof v === 'string' ? v : d;
}

function n(v: number | undefined | null, d: number): number {
  return typeof v === 'number' && isFinite(v) ? v : d;
}

function b(v: boolean | undefined | null, d: boolean): boolean {
  return typeof v === 'boolean' ? v : d;
}

function strs(v: string[] | undefined | null): string[] {
  const out: string[] = [];
  if (Array.isArray(v)) {
    for (const x of v) {
      if (typeof x === 'string') {
        out.push(x);
      }
    }
  }
  return out;
}

export function normAction(o: TileAction): TileAction {
  const a: TileAction = new TileAction();
  if (o === null || o === undefined || typeof o !== 'object') {
    return a;
  }
  a.label = s(o.label, '');
  a.kind = s(o.kind, 'done');
  a.arg = s(o.arg, '');
  return a;
}

export function normBlock(o: TileBlock): TileBlock {
  const x: TileBlock = new TileBlock();
  if (o === null || o === undefined || typeof o !== 'object') {
    return x;
  }
  x.kind = s(o.kind, 'text');
  x.text = s(o.text, '');
  x.value = s(o.value, '');
  x.items = strs(o.items);
  const checked: boolean[] = [];
  for (let i = 0; i < x.items.length; i++) {
    checked.push(Array.isArray(o.checked) && i < o.checked.length && o.checked[i] === true);
  }
  x.checked = checked;
  x.progress = Math.max(0, Math.min(1, n(o.progress, 0)));
  const acts: TileAction[] = [];
  if (Array.isArray(o.actions)) {
    for (const a of o.actions) {
      acts.push(normAction(a));
    }
  }
  x.actions = acts;
  return x;
}

export function normTile(o: TileSpec): TileSpec {
  const t: TileSpec = new TileSpec();
  if (o === null || o === undefined || typeof o !== 'object') {
    return t;
  }
  t.id = s(o.id, '');
  t.type = s(o.type, 'custom');
  t.title = s(o.title, '');
  t.subtitle = s(o.subtitle, '');
  t.icon = s(o.icon, '');
  t.color = s(o.color, 'sky');
  const size: string = s(o.size, '2x1');
  t.size = size === '1x1' || size === '2x1' || size === '2x2' ? size : '2x1';
  const blocks: TileBlock[] = [];
  if (Array.isArray(o.blocks)) {
    for (const bl of o.blocks) {
      blocks.push(normBlock(bl));
    }
  }
  t.blocks = blocks;
  t.source = s(o.source, 'seed');
  t.speakText = s(o.speakText, '');
  t.pinned = b(o.pinned, false);
  t.createdAt = n(o.createdAt, 0);
  return t;
}

export function normProfile(o: Profile): Profile {
  const base: Profile = profileFor(o !== null && o !== undefined && typeof o === 'object' ? s(o.id, 'everyday') :
    'everyday');
  if (o === null || o === undefined || typeof o !== 'object') {
    return base;
  }
  const p: Profile = new Profile();
  p.id = PROFILE_IDS.indexOf(s(o.id, '')) >= 0 ? o.id : 'everyday';
  p.name = s(o.name, base.name);
  p.textScale = Math.max(0.85, Math.min(2.0, n(o.textScale, base.textScale)));
  p.highContrast = b(o.highContrast, base.highContrast);
  p.readAloud = b(o.readAloud, base.readAloud);
  const cols: number = Math.round(n(o.columns, base.columns));
  p.columns = cols >= 1 && cols <= 6 ? cols : base.columns;
  p.caregiver = s(o.caregiver, base.caregiver);
  p.caregiverRole = s(o.caregiverRole, base.caregiverRole);
  return p;
}

export function normSuggestion(o: Suggestion): Suggestion {
  const x: Suggestion = new Suggestion();
  if (o === null || o === undefined || typeof o !== 'object') {
    return x;
  }
  x.id = s(o.id, '');
  x.title = s(o.title, '');
  x.detail = s(o.detail, '');
  x.change = s(o.change, '');
  x.status = s(o.status, 'pending');
  x.reason = s(o.reason, '');
  return x;
}

/** Parses a TileSpec JSON string (e.g. from an LLM or 'addTile:<json>'); null if unusable. */
export function parseTileJson(json: string): TileSpec | null {
  try {
    const o: TileSpec = JSON.parse(json) as TileSpec;
    const t: TileSpec = normTile(o);
    return t.title.length > 0 ? t : null;
  } catch (e) {
    return null;
  }
}

export function cloneTile(t: TileSpec): TileSpec {
  return normTile(JSON.parse(JSON.stringify(t)) as TileSpec);
}

function cloneProfile(p: Profile): Profile {
  return normProfile(JSON.parse(JSON.stringify(p)) as Profile);
}

let idCounter: number = 0;

export function newTileId(prefix: string): string {
  idCounter++;
  return prefix + '-' + Date.now().toString(36) + '-' + idCounter.toString();
}

export class TileStore {
  private static inst: TileStore | null = null;

  private ctx: common.Context | null = null;
  private prefs: preferences.Preferences | null = null;
  private list: TileSpec[] = [];
  private prof: Profile = profileFor('everyday');
  private suggs: Suggestion[] = [];
  private pend: TileSpec[] = [];
  private pendReply: string = '';
  private stats: TapStat[] = [];
  private onboarded: boolean = false;
  private hideApps: boolean = false;
  private rev: number = 0;

  static get(): TileStore {
    if (TileStore.inst === null) {
      TileStore.inst = new TileStore();
    }
    return TileStore.inst as TileStore;
  }

  private constructor() {
    this.list = seedTilesFor(this.prof.id);
    this.suggs = seedSuggestionsFor(this.prof.id);
    this.publishAll();
  }

  /** Call once from EntryAbility.onCreate. Loads persisted state (or keeps the seed). Safe to call again. */
  init(ctx: common.Context): void {
    this.ctx = ctx;
    try {
      const opts: preferences.Options = { name: PREFS_FILE };
      this.prefs = preferences.getPreferencesSync(ctx, opts);
    } catch (e) {
      this.prefs = null;
      hilog.warn(DOMAIN, TAG, 'preferences unavailable, in-memory only: %{public}s', JSON.stringify(e));
    }
    this.load();
    this.publishAll();
  }

  // ---------- reads ----------

  tiles(): TileSpec[] {
    return this.list;
  }

  profile(): Profile {
    return this.prof;
  }

  pending(): TileSpec[] {
    return this.pend;
  }

  /** Assistant reply that came with the pending proposal ('' if none). */
  pendingReply(): string {
    return this.pendReply;
  }

  suggestions(): Suggestion[] {
    return this.suggs;
  }

  pendingSuggestions(): Suggestion[] {
    return this.suggs.filter((x: Suggestion) => x.status === 'pending');
  }

  tile(id: string): TileSpec | null {
    for (const t of this.list) {
      if (t.id === id) {
        return t;
      }
    }
    return null;
  }

  tapStats(): TapStat[] {
    return this.stats;
  }

  isOnboarded(): boolean {
    return this.onboarded;
  }

  appsHidden(): boolean {
    return this.hideApps;
  }

  // ---------- profile ----------

  /**
   * Sets the active profile. A different profile id swaps in that person's home (their saved list, or the seed).
   * The same id only updates settings (textScale, contrast, read-aloud, columns...).
   */
  setProfile(p: Profile): void {
    const next: Profile = normProfile(p);
    const switching: boolean = next.id !== this.prof.id;
    if (switching) {
      this.saveListFor(this.prof.id);
      this.list = this.loadListFor(next.id);
      this.suggs = this.loadSuggestionsFor(next.id);
      this.pend = [];
      this.pendReply = '';
      this.stats = [];
    }
    this.prof = next;
    this.changed(true);
  }

  /** Switches to a profile id, keeping that profile's previously saved settings if any. */
  switchProfile(id: string): void {
    const saved: Profile | null = this.loadProfileFor(id);
    this.setProfile(saved !== null ? saved : profileFor(id));
  }

  setOnboarded(v: boolean): void {
    this.onboarded = v;
    this.changed(true);
  }

  // ---------- tiles ----------

  addTiles(t: TileSpec[]): void {
    const now: number = Date.now();
    const next: TileSpec[] = [];
    for (const x of t) {
      const c: TileSpec = cloneTile(x);
      if (c.id.length === 0 || this.indexOf(c.id) >= 0) {
        c.id = newTileId(c.type);
      }
      if (c.createdAt === 0) {
        c.createdAt = now;
      }
      next.push(c);
    }
    // A new tile with the same type + title replaces the old one (no duplicate "Dinner Fri" tiles).
    const sameKey = (a: TileSpec): string => a.type + '|' + a.title.trim().toLowerCase();
    const newKeys: string[] = next.map((x: TileSpec) => sameKey(x));
    const kept: TileSpec[] = this.list.filter((x: TileSpec) => newKeys.indexOf(sameKey(x)) < 0);
    // New tiles appear at the top, after pinned ones.
    let insertAt: number = 0;
    while (insertAt < kept.length && kept[insertAt].pinned) {
      insertAt++;
    }
    const out: TileSpec[] = kept.slice(0, insertAt).concat(next).concat(kept.slice(insertAt));
    this.list = out;
    this.changed(true);
  }

  removeTile(id: string): void {
    this.list = this.list.filter((x: TileSpec) => x.id !== id);
    this.changed(true);
  }

  /** Replaces a tile with the same id (e.g. after toggling a checklist or a vote). */
  updateTile(t: TileSpec): void {
    const i: number = this.indexOf(t.id);
    if (i < 0) {
      return;
    }
    const out: TileSpec[] = this.list.slice();
    out[i] = cloneTile(t);
    this.list = out;
    this.changed(true);
  }

  moveTile(from: number, to: number): void {
    if (from < 0 || from >= this.list.length || to < 0 || to >= this.list.length || from === to) {
      return;
    }
    const out: TileSpec[] = this.list.slice();
    const moved: TileSpec[] = out.splice(from, 1);
    out.splice(to, 0, moved[0]);
    this.list = out;
    this.changed(true);
  }

  togglePin(id: string): void {
    const t: TileSpec | null = this.tile(id);
    if (t !== null) {
      const c: TileSpec = cloneTile(t);
      c.pinned = !c.pinned;
      this.updateTile(c);
    }
  }

  /** Flips one checklist item; keeps a sibling 'progress' block in sync ('3 of 5'). */
  toggleCheck(tileId: string, blockIndex: number, itemIndex: number): void {
    const t: TileSpec | null = this.tile(tileId);
    if (t === null || blockIndex < 0 || blockIndex >= t.blocks.length) {
      return;
    }
    const c: TileSpec = cloneTile(t);
    const bl: TileBlock = c.blocks[blockIndex];
    if (itemIndex < 0 || itemIndex >= bl.checked.length) {
      return;
    }
    bl.checked[itemIndex] = !bl.checked[itemIndex];
    let done: number = 0;
    for (const v of bl.checked) {
      if (v) {
        done++;
      }
    }
    for (const other of c.blocks) {
      if (other.kind === 'progress' && bl.items.length > 0) {
        other.progress = done / bl.items.length;
        other.value = done.toString() + ' of ' + bl.items.length.toString();
      }
    }
    if (c.type === 'homework') {
      c.subtitle = done.toString() + ' of ' + bl.items.length.toString() + ' done';
    }
    this.updateTile(c);
  }

  /** Restores the current profile's seed home and suggestions. */
  resetToSeed(): void {
    this.list = seedTilesFor(this.prof.id);
    this.suggs = seedSuggestionsFor(this.prof.id);
    this.pend = [];
    this.pendReply = '';
    this.stats = [];
    this.hideApps = false;
    this.changed(true);
  }

  // ---------- assistant proposals (await approval) ----------

  /** Queues the assistant's tiles for approval (caregiver / parent, or the user's own "Add"). */
  propose(r: ComposeResult): void {
    const now: number = Date.now();
    const next: TileSpec[] = this.pend.slice();
    for (const x of r.tiles) {
      const c: TileSpec = cloneTile(x);
      if (c.id.length === 0 || this.indexOf(c.id) >= 0 || this.pendingIndexOf(c.id, next) >= 0) {
        c.id = newTileId(c.type);
      }
      if (c.source === 'seed') {
        c.source = 'assistant';
      }
      if (c.createdAt === 0) {
        c.createdAt = now;
      }
      next.push(c);
    }
    this.pend = next;
    this.pendReply = r.reply;
    this.changed(true);
  }

  approvePending(id: string): void {
    const i: number = this.pendingIndexOf(id, this.pend);
    if (i < 0) {
      return;
    }
    const t: TileSpec = this.pend[i];
    this.pend = this.pend.filter((x: TileSpec) => x.id !== id);
    if (this.pend.length === 0) {
      this.pendReply = '';
    }
    this.addTiles([t]); // publishes
  }

  declinePending(id: string): void {
    this.pend = this.pend.filter((x: TileSpec) => x.id !== id);
    if (this.pend.length === 0) {
      this.pendReply = '';
    }
    this.changed(true);
  }

  approveAllPending(): void {
    const all: TileSpec[] = this.pend;
    this.pend = [];
    this.pendReply = '';
    this.addTiles(all);
  }

  // ---------- adaptation suggestions ----------

  /** Adds suggestions (from Adaptation.ets); an id already present is replaced only if still pending. */
  addSuggestions(list: Suggestion[]): void {
    const out: Suggestion[] = this.suggs.slice();
    for (const x of list) {
      const c: Suggestion = normSuggestion(x);
      let found: number = -1;
      for (let i = 0; i < out.length; i++) {
        if (out[i].id === c.id) {
          found = i;
        }
      }
      if (found < 0) {
        out.push(c);
      } else if (out[found].status === 'pending') {
        out[found] = c;
      }
    }
    this.suggs = out;
    this.changed(true);
  }

  /** Approve applies the change (see applyChange); decline only records the decision. */
  decideSuggestion(id: string, approve: boolean): void {
    const out: Suggestion[] = [];
    let target: Suggestion | null = null;
    for (const x of this.suggs) {
      const c: Suggestion = normSuggestion(x);
      if (c.id === id && c.status === 'pending') {
        c.status = approve ? 'approved' : 'declined';
        target = c;
      }
      out.push(c);
    }
    this.suggs = out;
    if (target !== null && approve) {
      this.applyChange((target as Suggestion).change);
    }
    this.changed(true);
  }

  /**
   * Applies a suggestion change string:
   *   textScale:<n> | readAloud:on|off | highContrast:on|off | columns:<n> | hide:apps | hide:unused |
   *   hide:<type> | addTile:<TileSpec json> | remove:<tileId> | top:<tileId> | size:<tileId>:<1x1|2x1|2x2> |
   *   timer:<min>
   */
  applyChange(change: string): void {
    const sep: number = change.indexOf(':');
    const key: string = sep >= 0 ? change.substring(0, sep) : change;
    const val: string = sep >= 0 ? change.substring(sep + 1) : '';
    const p: Profile = cloneProfile(this.prof);
    switch (key) {
      case 'textScale': {
        const v: number = Number(val);
        if (isFinite(v) && v > 0) {
          p.textScale = v;
          this.prof = normProfile(p);
        }
        break;
      }
      case 'readAloud':
        p.readAloud = val === 'on' || val === 'true';
        this.prof = p;
        break;
      case 'highContrast':
        p.highContrast = val === 'on' || val === 'true';
        this.prof = p;
        break;
      case 'columns': {
        const c: number = Math.round(Number(val));
        if (c >= 1 && c <= 6) {
          p.columns = c;
          this.prof = p;
        }
        break;
      }
      case 'hide':
        if (val === 'apps') {
          this.hideApps = true;
        } else if (val === 'unused') {
          this.list = this.list.filter((t: TileSpec) => t.pinned || this.statFor(t.id) !== null);
        } else if (val.length > 0) {
          this.list = this.list.filter((t: TileSpec) => t.pinned || t.type !== val);
        }
        break;
      case 'addTile': {
        const t: TileSpec | null = parseTileJson(val);
        if (t !== null) {
          const tt: TileSpec = t as TileSpec;
          tt.source = 'adaptation';
          this.addTiles([tt]);
        }
        break;
      }
      case 'remove':
        this.list = this.list.filter((t: TileSpec) => t.id !== val);
        break;
      case 'top': {
        const i: number = this.indexOf(val);
        if (i > 0) {
          const out: TileSpec[] = this.list.slice();
          const moved: TileSpec[] = out.splice(i, 1);
          out.unshift(moved[0]);
          this.list = out;
        }
        break;
      }
      case 'size': {
        const j: number = val.lastIndexOf(':');
        if (j > 0) {
          const tid: string = val.substring(0, j);
          const size: string = val.substring(j + 1);
          const t: TileSpec | null = this.tile(tid);
          if (t !== null && (size === '1x1' || size === '2x1' || size === '2x2')) {
            const c: TileSpec = cloneTile(t);
            c.size = size;
            this.updateTile(c);
          }
        }
        break;
      }
      case 'timer': {
        const mins: number = Math.round(Number(val));
        if (mins > 0) {
          const out: TileSpec[] = [];
          for (const t of this.list) {
            if (t.type === 'timer') {
              const c: TileSpec = cloneTile(t);
              for (const bl of c.blocks) {
                if (bl.kind === 'timer' && !bl.value.startsWith('at:')) {
                  bl.value = mins.toString();
                }
                for (const a of bl.actions) {
                  if (a.arg.startsWith('timer:')) {
                    a.arg = 'timer:' + mins.toString();
                  }
                }
              }
              out.push(c);
            } else {
              out.push(t);
            }
          }
          this.list = out;
        }
        break;
      }
      default:
        hilog.info(DOMAIN, TAG, 'unknown change: %{public}s', key);
        break;
    }
    this.changed(true);
  }

  // ---------- usage signals ----------

  /** missed = a tap that landed near but outside a target, or was undone immediately. */
  recordTap(tileId: string, missed: boolean): void {
    const out: TapStat[] = [];
    let found: boolean = false;
    for (const x of this.stats) {
      if (x.tileId === tileId) {
        const c: TapStat = new TapStat();
        c.tileId = x.tileId;
        c.taps = x.taps + (missed ? 0 : 1);
        c.missed = x.missed + (missed ? 1 : 0);
        c.lastTapAt = Date.now();
        out.push(c);
        found = true;
      } else {
        out.push(x);
      }
    }
    if (!found) {
      const c: TapStat = new TapStat();
      c.tileId = tileId;
      c.taps = missed ? 0 : 1;
      c.missed = missed ? 1 : 0;
      c.lastTapAt = Date.now();
      out.push(c);
    }
    this.stats = out;
    this.changed(false);
  }

  missedTapsTotal(): number {
    let m: number = 0;
    for (const x of this.stats) {
      m += x.missed;
    }
    return m;
  }

  statFor(tileId: string): TapStat | null {
    for (const x of this.stats) {
      if (x.tileId === tileId) {
        return x;
      }
    }
    return null;
  }

  // ---------- internals ----------

  private indexOf(id: string): number {
    for (let i = 0; i < this.list.length; i++) {
      if (this.list[i].id === id) {
        return i;
      }
    }
    return -1;
  }

  private pendingIndexOf(id: string, arr: TileSpec[]): number {
    for (let i = 0; i < arr.length; i++) {
      if (arr[i].id === id) {
        return i;
      }
    }
    return -1;
  }

  private changed(persist: boolean): void {
    this.publishAll();
    if (persist) {
      this.save();
      if (this.ctx !== null) {
        WidgetBridge.publish(this.ctx as common.Context, this.list, this.prof);
      }
    }
  }

  private publishAll(): void {
    this.rev++;
    AppStorage.setOrCreate<TileSpec[]>(K_LIST, this.list);
    AppStorage.setOrCreate<Profile>(K_PROFILE, this.prof);
    AppStorage.setOrCreate<Suggestion[]>(K_SUGGESTIONS, this.suggs);
    AppStorage.setOrCreate<TileSpec[]>(K_PENDING, this.pend);
    AppStorage.setOrCreate<string>(K_PENDING_REPLY, this.pendReply);
    AppStorage.setOrCreate<boolean>(K_ONBOARDED, this.onboarded);
    AppStorage.setOrCreate<boolean>(K_HIDE_APPS, this.hideApps);
    AppStorage.setOrCreate<number>(K_REV, this.rev);
  }

  private getStr(key: string): string {
    if (this.prefs === null) {
      return '';
    }
    try {
      const v: preferences.ValueType = (this.prefs as preferences.Preferences).getSync(key, '');
      return typeof v === 'string' ? v : '';
    } catch (e) {
      return '';
    }
  }

  private putStr(key: string, v: string): void {
    if (this.prefs === null) {
      return;
    }
    try {
      (this.prefs as preferences.Preferences).putSync(key, v);
    } catch (e) {
      hilog.warn(DOMAIN, TAG, 'put %{public}s failed', key);
    }
  }

  private parseTiles(json: string): TileSpec[] | null {
    if (json.length === 0) {
      return null;
    }
    try {
      const arr: TileSpec[] = JSON.parse(json) as TileSpec[];
      if (!Array.isArray(arr)) {
        return null;
      }
      const out: TileSpec[] = [];
      for (const o of arr) {
        const t: TileSpec = normTile(o);
        if (t.id.length > 0) {
          out.push(t);
        }
      }
      return out;
    } catch (e) {
      return null;
    }
  }

  private loadListFor(profileId: string): TileSpec[] {
    const saved: TileSpec[] | null = this.parseTiles(this.getStr(K_LIST + '.' + profileId));
    return saved !== null ? saved : seedTilesFor(profileId);
  }

  private saveListFor(profileId: string): void {
    this.putStr(K_LIST + '.' + profileId, JSON.stringify(this.list));
  }

  private loadSuggestionsFor(profileId: string): Suggestion[] {
    const json: string = this.getStr(K_SUGGESTIONS + '.' + profileId);
    if (json.length > 0) {
      try {
        const arr: Suggestion[] = JSON.parse(json) as Suggestion[];
        if (Array.isArray(arr)) {
          const out: Suggestion[] = [];
          for (const o of arr) {
            out.push(normSuggestion(o));
          }
          return out;
        }
      } catch (e) {
        hilog.warn(DOMAIN, TAG, 'bad suggestions json');
      }
    }
    return seedSuggestionsFor(profileId);
  }

  private loadProfileFor(id: string): Profile | null {
    const json: string = this.getStr(K_PROFILE + '.' + id);
    if (json.length === 0) {
      return null;
    }
    try {
      const p: Profile = normProfile(JSON.parse(json) as Profile);
      return p.id === id ? p : null;
    } catch (e) {
      return null;
    }
  }

  private load(): void {
    const json: string = this.getStr('tiles.state');
    let st: SavedState | null = null;
    if (json.length > 0) {
      try {
        st = JSON.parse(json) as SavedState;
      } catch (e) {
        st = null;
      }
    }
    if (st === null || typeof st !== 'object') {
      return; // first run: keep the seed
    }
    const saved: SavedState = st as SavedState;
    this.prof = normProfile(saved.profile);
    this.onboarded = b(saved.onboarded, false);
    this.list = this.loadListFor(this.prof.id);
    this.suggs = this.loadSuggestionsFor(this.prof.id);
    const pend: TileSpec[] = [];
    if (Array.isArray(saved.pending)) {
      for (const o of saved.pending) {
        pend.push(normTile(o));
      }
    }
    this.pend = pend;
    this.hideApps = this.getStr(K_HIDE_APPS) === '1';
  }

  private save(): void {
    if (this.prefs === null) {
      return;
    }
    const st: SavedState = new SavedState();
    st.profile = this.prof;
    st.pending = this.pend;
    st.onboarded = this.onboarded;
    this.putStr('tiles.state', JSON.stringify(st));
    this.saveListFor(this.prof.id);
    this.putStr(K_SUGGESTIONS + '.' + this.prof.id, JSON.stringify(this.suggs));
    this.putStr(K_PROFILE + '.' + this.prof.id, JSON.stringify(this.prof));
    this.putStr(K_HIDE_APPS, this.hideApps ? '1' : '0');
    (this.prefs as preferences.Preferences).flush().catch((e: Error) => {
      hilog.warn(DOMAIN, TAG, 'flush failed: %{public}s', e.message);
    });
  }
}
