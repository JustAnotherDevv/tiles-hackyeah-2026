import { TileAction, TileBlock, TileSpec, Profile } from '../model/Tile';
import { LL_FONT_FAMILY, ProfileLayout, TileColors, TilesTheme, withAlpha } from '../theme/TilesTheme';
import { BlockStyle, tileIcon } from './blocks/BlockStyle';
import { BlockView } from './blocks/BlockView';
import { percentOf } from './blocks/ProgressBlock';

/** One block plus its index in tile.blocks (needed for 'toggle' args) and a stable render key. */
class BlockSlot {
  key: string = '';
  index: number = 0;
  block: TileBlock = new TileBlock();
  /** 0 = keep longest (hero value) ... 3 = drop first when the tile is too short. */
  priority: number = 2;
}

/** Block kinds that can be a tile's single "key value" in compact tiles. */
const KEY_KINDS: string[] = ['big', 'timer', 'progress', 'weather', 'alert'];

/** How long after creation an assistant tile still plays its "spring in" entrance. */
const APPEAR_WINDOW_MS: number = 20000;

/** Living Light (design C) tile shell constants — design/tiles-motion/source/Tiles_Stage.dc.html. */
const LL_BREATHE_HALF_MS: number = 1400; // @keyframes breathe 2.8s ease-in-out infinite (1 -> 1.022 -> 1)
const LL_SHIMMER_MS: number = 1400; // @keyframes shimmer 1.4s linear infinite
const LL_HIGHLIGHT: string = '#CCFFFFFF'; // inset 0 1px 0 rgba(255,255,255,.8)
const LL_HIGHLIGHT_DARK: string = '#2EFFFFFF';
/** Tile types that carry live, time-relevant data and "breathe" on the home grid (prototype spec.live). */
const LIVE_TYPES: string[] = ['pills', 'reminder'];

/** Relative luminance check for '#RRGGBB' / '#AARRGGBB' (true = light color). */
function isLightHex(hex: string): boolean {
  const rgb: string = hex.length === 9 ? hex.substring(3) : hex.substring(1);
  if (rgb.length !== 6) {
    return false;
  }
  const r: number = parseInt(rgb.substring(0, 2), 16);
  const g: number = parseInt(rgb.substring(2, 4), 16);
  const b: number = parseInt(rgb.substring(4, 6), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) > 160;
}

/** Seeded textScale per profile: Adaptation's "make text bigger" scales the prototype fs relative to it. */
function baseTextScale(id: string): number {
  switch (id) {
    case 'senior':
      return 1.4;
    case 'kid':
      return 1.15;
    case 'lowvision':
      return 1.6;
    default:
      return 1.0;
  }
}

/**
 * Generative-UI renderer: draws ANY TileSpec natively (size 1x1 / 2x1 / 2x2, palette color + on-color text,
 * SymbolGlyph icon, content blocks, actions), adapted to the Profile (textScale, highContrast, readAloud, tap size).
 *
 * The view never performs platform side effects: every interaction is reported through
 * `onAction(action, tile)` — tile tap = kind 'open', read-aloud = kind 'speak' (arg = text to speak),
 * buttons/chips = their TileAction, checklist = kind 'toggle' (arg '<block>:<item>'), timer = kind 'timer'.
 *
 * Responsive: the layout tier comes from the tile's MEASURED size (onAreaChange), scaled by the profile's text size:
 *  - compact (narrow and short, or 1x1): icon + title (<= 2 lines, shrinks before it ellipsizes, never mid-word),
 *    ONE key value (big / timer / progress / weather / alert), at most one primary button; no subtitle/chips/lists.
 *  - medium: title + 1-line subtitle + the primary block(s) + up to 2 chips + up to 2 buttons.
 *  - full: everything that fits (detail mode is always full).
 * In fixed-height grid cells, blocks that would overflow the tile are dropped lowest-priority first (measured,
 * not guessed); a soft fade is only drawn if even the last block cannot fit. accessibilityText always carries the
 * full content (title, subtitle, every block), so nothing hidden visually is lost to screen-reader users.
 *
 * Usage: TileView({ tile: t, profile: p, dark: isDark, onAction: (a, t) => {...} })
 *        TileView({ tile: t, profile: p, mode: 'detail' })  // full-screen detail rendering
 */
@Component
export struct TileView {
  @Prop @Watch('onInputs') tile: TileSpec = new TileSpec();
  @Prop @Watch('onInputs') profile: Profile = new Profile();
  /** 'tile' (grid) or 'detail' (full screen, all blocks, larger type). */
  @Prop mode: string = 'tile';
  @Prop dark: boolean = false;
  /** true: take the parent's height (e.g. fixed-height GridItem); false: min height from the size's aspect. */
  @Prop fillHeight: boolean = false;
  @Prop reduceMotion: boolean = false;
  @State private pressed: boolean = false;
  @State private appearScale: number = 1;
  @State private appearOpacity: number = 1;
  @State private appearTy: number = 0;
  /** Living Light "breathe" loop for live tiles (1 -> 1.022). */
  @State private breatheScale: number = 1;
  /** Skeleton shimmer sweep position (0 -> 1). */
  @State private shimmerT: number = 0;
  /** Generating placeholder: shimmer skeleton instead of content (prototype tile birth before the flood). */
  @Prop skeleton: boolean = false;
  /**
   * Progressive build (prototype tile birth): -1 = everything visible; otherwise the header shows once
   * built >= 1 and block #i once built >= i + 2, each fading/sliding in (opacity .35s, translateY 12 -> 0 .45s LL ease).
   */
  @Prop built: number = -1;
  @State private cardW: number = 0;
  @State private cardH: number = 0;
  /** tile.blocks indexes dropped because they did not fit the measured tile height. */
  @State private dropped: number[] = [];
  /** Even the last remaining block overflows: draw a soft fade at the bottom edge (last resort). */
  @State private overflowFade: boolean = false;
  /** Measured bottom edge (vp, inside the content column) per block index. */
  private bottoms: Map<number, number> = new Map<number, number>();
  private fitPending: boolean = false;
  private animateIn: boolean = false;
  private breathing: boolean = false;
  onAction: (action: TileAction, tile: TileSpec) => void = (action: TileAction, tile: TileSpec) => {
  };
  /** Optional long-press (reorder / remove menu in the home grid). */
  onLongPress: (tile: TileSpec) => void = (tile: TileSpec) => {
  };

  aboutToAppear(): void {
    this.animateIn = !this.reduceMotion && this.mode === 'tile' && this.tile.source === 'assistant' &&
      (this.tile.createdAt <= 0 || Date.now() - this.tile.createdAt < APPEAR_WINDOW_MS);
    if (this.animateIn) {
      this.appearScale = TilesTheme.LL_ENTER_SCALE;
      this.appearTy = TilesTheme.LL_ENTER_TY;
      this.appearOpacity = 0;
    }
  }

  onInputs(): void {
    this.resetFit();
    this.syncBreathe();
  }

  /** Prototype: live tiles breathe on the home grid (never in detail, skeleton, or with reduced motion). */
  private isLive(): boolean {
    return this.mode === 'tile' && !this.skeleton && !this.reduceMotion && !this.llLayout().reducedMotion &&
      LIVE_TYPES.indexOf(this.tile.type) >= 0;
  }

  private syncBreathe(): void {
    const want: boolean = this.isLive();
    if (want === this.breathing) {
      return;
    }
    this.breathing = want;
    if (want) {
      this.getUIContext().animateTo({
        duration: LL_BREATHE_HALF_MS, curve: Curve.EaseInOut, iterations: -1, playMode: PlayMode.Alternate
      }, () => {
        this.breatheScale = TilesTheme.LL_BREATHE_SCALE;
      });
    } else {
      this.getUIContext().animateTo({ duration: 0 }, () => {
        this.breatheScale = 1;
      });
    }
  }

  private startShimmer(): void {
    if (!this.skeleton || this.reduceMotion) {
      return;
    }
    this.shimmerT = 0;
    this.getUIContext().animateTo({ duration: LL_SHIMMER_MS, curve: Curve.Linear, iterations: -1 }, () => {
      this.shimmerT = 1;
    });
  }

  private llLayout(): ProfileLayout {
    return TilesTheme.layoutFor(this.profile);
  }

  /** Prototype font multiplier (PROFILES fs), grown by Adaptation's text-size changes; detail never below 1. */
  private llFs(): number {
    const base: number = baseTextScale(this.profile.id);
    const ts: number = isFinite(this.profile.textScale) && this.profile.textScale > 0 ? this.profile.textScale : base;
    const f: number = this.llLayout().fs * ts / base;
    return this.isDetail() ? Math.max(1.0, f) : f;
  }

  /** Measured width (vp) for the prototype's `small` (< 120) / `square` (< 200) header variants. */
  private measuredW(): number {
    return this.cardW > 0 ? this.cardW : (this.tile.size === '1x1' ? 110 : 300);
  }

  private small(): boolean {
    return !this.isDetail() && this.measuredW() < 120;
  }

  private square(): boolean {
    return !this.isDetail() && this.measuredW() < 200;
  }

  private headShown(): boolean {
    return this.built < 0 || this.built >= 1;
  }

  private blockShown(i: number): boolean {
    return this.built < 0 || this.built >= i + 2;
  }

  private resetFit(): void {
    this.bottoms.clear();
    if (this.dropped.length > 0) {
      this.dropped = [];
    }
    if (this.overflowFade) {
      this.overflowFade = false;
    }
  }

  private colors(): TileColors {
    return TilesTheme.tile(this.tile.color, this.profile.highContrast, this.dark);
  }

  private isDetail(): boolean {
    return this.mode === 'detail';
  }

  /** Type scale for the responsive tiers: the Living Light profile fs (the real tile text multiplier). */
  private typeScale(): number {
    const s: number = this.llFs();
    return s > 0 ? s : 1;
  }

  /** Measured width in "unscaled" vp (width / text scale): how much room the text really has. */
  private effW(): number {
    const w: number = this.cardW > 0 ? this.cardW : (this.tile.size === '1x1' ? 90 : 184);
    return w / this.typeScale();
  }

  /** Measured height in unscaled vp; unbounded when the tile sizes to its content. */
  private effH(): number {
    if (!this.fillHeight || this.isDetail()) {
      return 9999;
    }
    return (this.cardH > 0 ? this.cardH : 150) / this.typeScale();
  }

  /** Layout tier from the measured size: 'compact' | 'medium' | 'full'. */
  private tier(): string {
    if (this.isDetail()) {
      return 'full';
    }
    if (this.tile.size === '1x1') {
      return 'compact';
    }
    const ew: number = this.effW();
    const eh: number = this.effH();
    if (ew < 200 && eh < 200) {
      return 'compact';
    }
    if (ew < 320 || eh < 200) {
      return 'medium';
    }
    return 'full';
  }

  private isCompact(): boolean {
    return this.tier() === 'compact';
  }

  private narrow(): boolean {
    return !this.isDetail() && this.effW() < 230;
  }

  private tiny(): boolean {
    return !this.isDetail() && this.effW() < 120;
  }

  /** Prototype pad: small ? 10 : 16 (PROFILES pad); detail 22. */
  private pad(): number {
    if (this.isDetail()) {
      return 22;
    }
    return this.small() ? 10 : 16;
  }

  /** Prototype gapY: small ? 3 : 8. */
  private gapY(): number {
    if (this.isDetail()) {
      return 14;
    }
    return this.small() ? 3 : 8;
  }

  private style(): BlockStyle {
    const c: TileColors = this.colors();
    const s: BlockStyle = new BlockStyle();
    const f: number = this.llFs();
    const small: boolean = this.small();
    const body: number = Math.round(14 * f);
    const num: number = Math.round(38 * f);
    s.fg = c.on;
    s.fgDim = c.onMuted;
    s.bg = c.bg;
    s.bgFrom = c.bg1;
    s.bgTo = c.bg2;
    // Prototype: secondary pills / chips rgba(0,0,0,.1), track rgba(0,0,0,.14); high contrast uses the on-color wash.
    s.well = this.profile.highContrast ? c.soft : (this.dark ? '#1FFFFFFF' : '#1A000000');
    s.pill = s.well;
    s.track = this.profile.highContrast ? withAlpha(c.on, 0.24) : (this.dark ? '#29FFFFFF' : '#24000000');
    s.roundFill = this.profile.highContrast ? c.soft : (this.dark ? '#24FFFFFF' : '#1F000000');
    // Primary pill = on-color with white label (light on-colors, e.g. 'ink', take the deep gradient stop instead).
    s.solid = c.on;
    s.onSolid = isLightHex(c.on) ? c.bg2 : '#FFFFFF';
    s.scale = f;
    s.llFs = f;
    s.small = small;
    s.square = this.square();
    s.font = LL_FONT_FAMILY;
    s.titleSize = this.titleFs();
    s.bodySize = this.isDetail() ? Math.round(body * 1.15) : (small ? Math.round(body * 0.9) : body);
    s.numSize = small ? Math.round(num * 0.78) : (this.isDetail() ? Math.round(num * 1.15) : num);
    s.iconSize = this.iconSize();
    s.chipSize = Math.max(11, Math.round(s.bodySize * 0.85));
    s.btnH = Math.max(40, Math.round(s.bodySize * 2.5));
    s.btnPad = Math.max(10, Math.round(s.bodySize * 0.9));
    s.rowMin = Math.max(28, Math.round(s.bodySize * 2));
    s.bodyLines = !this.isDetail() && this.fillHeight && this.cardH > 0 && this.cardH < 120 ? 1 : 3;
    s.gapY = this.gapY();
    s.highContrast = this.profile.highContrast;
    s.minTap = TilesTheme.tapTarget(this.profile);
    s.detail = this.isDetail();
    s.reduceMotion = this.reduceMotion;
    s.tier = this.tier();
    s.compact = s.tier === 'compact';
    s.narrow = this.narrow();
    s.tiny = this.tiny();
    return s;
  }

  private fs(base: number): number {
    return Math.round(base * this.typeScale() * (this.isDetail() ? 1.15 : 1.0));
  }

  /** Prototype titleSize = 19 * fs (small .82, square .94); detail a step larger. */
  private titleFs(): number {
    const t: number = 19 * this.llFs();
    if (this.isDetail()) {
      return Math.round(t * 1.25);
    }
    if (this.small()) {
      return Math.round(t * 0.82);
    }
    return Math.round(this.square() ? t * 0.94 : t);
  }

  private firstKind(kind: string): number {
    for (let i = 0; i < this.tile.blocks.length; i++) {
      if (this.tile.blocks[i].kind === kind) {
        return i;
      }
    }
    return -1;
  }

  /** Which blocks this tier shows (before height capping), in original order. */
  private pickIndexes(): number[] {
    const all: TileBlock[] = this.tile.blocks;
    const picked: number[] = [];
    const tier: string = this.tier();
    if (this.isDetail()) {
      for (let i = 0; i < all.length; i++) {
        picked.push(i);
      }
      return picked;
    }
    if (tier === 'compact') {
      // ONE key value; tiny tiles only take a short hero value (no controls).
      for (let i = 0; i < all.length; i++) {
        const k: string = all[i].kind;
        if (this.tiny() ? (k === 'big' || k === 'weather') : KEY_KINDS.indexOf(k) >= 0) {
          picked.push(i);
          break;
        }
      }
      if (picked.length === 0 && !this.tiny()) {
        const cl: number = this.firstKind('checklist'); // shown as "2 of 6 done"
        if (cl >= 0) {
          picked.push(cl);
        }
      }
      if (!this.tiny()) {
        const btn: number = this.firstKind('buttons');
        if (btn >= 0) {
          picked.push(btn); // rendered as a single primary button; dropped first if it does not fit
        }
        if (picked.length === 0) {
          const tx: number = this.firstKind('text');
          if (tx >= 0) {
            picked.push(tx);
          }
        }
      }
    } else if (tier === 'medium') {
      const maxContent: number = this.effH() >= 240 ? 2 : 1;
      let n: number = 0;
      let chips: boolean = false;
      let btns: boolean = false;
      for (let i = 0; i < all.length; i++) {
        const k: string = all[i].kind;
        if (k === 'buttons') {
          if (!btns) {
            picked.push(i);
            btns = true;
          }
        } else if (k === 'chips') {
          if (!chips) {
            picked.push(i);
            chips = true;
          }
        } else if (n < maxContent) {
          picked.push(i);
          n++;
        }
      }
    } else {
      const max: number = this.tile.size === '2x2' ? 4 : 2;
      for (let i = 0; i < all.length && picked.length < max; i++) {
        picked.push(i);
      }
      // Never hide the tile's actions: swap the last picked block for the first 'buttons' block.
      const btn: number = this.firstKind('buttons');
      if (btn >= 0 && picked.indexOf(btn) < 0 && picked.length > 0) {
        picked[picked.length - 1] = btn;
      }
    }
    picked.sort((a: number, b: number) => a - b);
    return picked;
  }

  /** Visible blocks: the tier's picks minus the ones dropped for height. */
  private slots(): BlockSlot[] {
    const picked: number[] = this.pickIndexes();
    const out: BlockSlot[] = [];
    let first: boolean = true;
    for (let j = 0; j < picked.length; j++) {
      const i: number = picked[j];
      const b: TileBlock = this.tile.blocks[i];
      if (this.dropped.indexOf(i) >= 0) {
        continue;
      }
      const s: BlockSlot = new BlockSlot();
      s.index = i;
      s.block = b;
      if (b.kind === 'buttons' || b.kind === 'alert') {
        s.priority = 1;
      } else if (b.kind === 'chips') {
        s.priority = 3;
      } else if (first) {
        s.priority = 0;
        first = false;
      } else {
        s.priority = 2;
      }
      s.key = this.tile.id + '#' + i + ':' + b.kind + ':' + b.text + '|' + b.value + '|' + b.progress + '|' +
        b.items.join(',') + '|' + b.checked.join(',') + '|' + b.actions.length;
      out.push(s);
    }
    return out;
  }

  private scheduleFit(): void {
    if (!this.fillHeight || this.isDetail() || this.fitPending) {
      return;
    }
    this.fitPending = true;
    setTimeout(() => {
      this.fitPending = false;
      this.fit();
    }, 32);
  }

  /** Drop the lowest-priority block while any visible block's measured bottom exceeds the tile. */
  private fit(): void {
    if (this.cardH <= 0) {
      return;
    }
    const limit: number = this.cardH - this.pad() + 2;
    const visible: BlockSlot[] = this.slots();
    let over: boolean = false;
    for (let i = 0; i < visible.length; i++) {
      const b: number | undefined = this.bottoms.get(visible[i].index);
      if (b !== undefined && b > limit) {
        over = true;
      }
    }
    if (!over) {
      if (this.overflowFade) {
        this.overflowFade = false;
      }
      return;
    }
    if (visible.length <= 1) {
      this.overflowFade = true;
      return;
    }
    let victim: BlockSlot = visible[0];
    for (let i = 1; i < visible.length; i++) {
      const s: BlockSlot = visible[i];
      if (s.priority > victim.priority || (s.priority === victim.priority && s.index > victim.index)) {
        victim = s;
      }
    }
    const next: number[] = this.dropped.slice();
    next.push(victim.index);
    this.bottoms.delete(victim.index);
    this.dropped = next;
    this.scheduleFit();
  }

  private minHeight(): number {
    if (this.isDetail() || this.cardW <= 0 || this.fillHeight) {
      return 0;
    }
    if (this.tile.size === '2x1') {
      return Math.round(this.cardW * 0.5);
    }
    if (this.tile.size === '2x2') {
      return Math.round(this.cardW * 0.8);
    }
    return Math.round(this.cardW); // 1x1 is square
  }

  /** Compact: skip the title line when the hero block already shows the same value (e.g. '14°'). */
  private titleRepeated(): boolean {
    if (!this.isCompact()) {
      return false;
    }
    for (let i = 0; i < this.tile.blocks.length; i++) {
      if (this.tile.blocks[i].value.length > 0 && this.tile.blocks[i].value === this.tile.title) {
        return true;
      }
    }
    return false;
  }

  /** Spoken summary of one block (screen readers get everything, even what the tile hides). */
  private blockSummary(b: TileBlock): string {
    const parts: string[] = [];
    if (b.kind === 'buttons') {
      const labels: string[] = [];
      for (let i = 0; i < b.actions.length; i++) {
        labels.push(b.actions[i].label.length > 0 ? b.actions[i].label : b.actions[i].kind);
      }
      return labels.length > 0 ? 'Actions: ' + labels.join(', ') : '';
    }
    if (b.kind === 'checklist') {
      const rows: string[] = [];
      for (let i = 0; i < b.items.length; i++) {
        rows.push(b.items[i] + (i < b.checked.length && b.checked[i] ? ', done' : ''));
      }
      return (b.text.length > 0 ? b.text + ': ' : '') + rows.join('; ');
    }
    if (b.kind === 'progress') {
      if (b.value.length > 0) {
        parts.push(b.value);
      }
      parts.push(percentOf(b.progress) + ' percent');
      if (b.text.length > 0) {
        parts.push(b.text);
      }
      return parts.join(', ');
    }
    if (b.kind === 'timer') {
      const v: string = b.value.startsWith('at:') ? 'at ' + b.value.substring(3) :
        (b.value.length > 0 ? parseInt(b.value) + ' minute timer' : 'timer');
      return (b.text.length > 0 ? b.text + ', ' : '') + v;
    }
    if (b.kind === 'chips' && b.actions.length > 0) {
      const labels: string[] = [];
      for (let i = 0; i < b.actions.length; i++) {
        labels.push(b.actions[i].label);
      }
      return (b.text.length > 0 ? b.text + ': ' : '') + 'options ' + labels.join(', ');
    }
    if (b.value.length > 0) {
      parts.push(b.value);
    }
    if (b.text.length > 0) {
      parts.push(b.text);
    }
    if (b.items.length > 0) {
      parts.push(b.items.join(', '));
    }
    return parts.join(', ');
  }

  private a11yText(): string {
    const parts: string[] = [this.tile.title];
    if (this.tile.subtitle.length > 0) {
      parts.push(this.tile.subtitle);
    }
    const plain: string = this.tile.subtitle.length > 0 ? this.tile.title + '. ' + this.tile.subtitle : this.tile.title;
    if (this.tile.speakText.length > 0 && this.tile.speakText !== plain && this.tile.speakText !== this.tile.title) {
      parts.push(this.tile.speakText);
    }
    for (let i = 0; i < this.tile.blocks.length; i++) {
      const s: string = this.blockSummary(this.tile.blocks[i]);
      if (s.length > 0) {
        parts.push(s);
      }
    }
    if (this.badgeText().length > 0) {
      parts.push(this.badgeText() === 'NEW' ? 'New tile' : 'Adapted for you');
    }
    return parts.join('. ');
  }

  private isNew(): boolean {
    return this.tile.source === 'assistant' && this.tile.createdAt > 0 &&
      Date.now() - this.tile.createdAt < 10 * 60 * 1000;
  }

  private badgeText(): string {
    if (this.isNew()) {
      return 'NEW';
    }
    return this.tile.source === 'adaptation' ? 'ADAPTED' : '';
  }

  /** Prototype hides the read-aloud button on square (< 200 vp) tiles; detail always shows it. */
  private showSpeaker(): boolean {
    return (this.profile.readAloud && !this.square()) || this.isDetail();
  }

  /** Prototype iconSize = 24 * fs (small .85): a bare filled glyph, no plate. */
  private iconSize(): number {
    const i: number = 24 * this.llFs();
    if (this.isDetail()) {
      return Math.round(i * 1.25);
    }
    return Math.round(this.small() ? i * 0.85 : i);
  }

  private emit(kind: string, arg: string, label: string): void {
    const a: TileAction = new TileAction();
    a.kind = kind;
    a.arg = arg;
    a.label = label;
    this.onAction(a, this.tile);
  }

  private speak(): void {
    this.emit('speak', this.tile.speakText.length > 0 ? this.tile.speakText : this.a11yText(), 'Read aloud');
  }

  /** On-color for text/icons (skeleton tiles use the muted ink, like the prototype). */
  private fg(): string {
    return this.skeleton ? '#5B6283' : this.colors().on;
  }

  private fgMuted(): string {
    return this.skeleton ? '#995B6283' : this.colors().onMuted;
  }

  /** Background gradient stops: palette 135deg, or the flat skeleton glass while generating. */
  private bgStops(): Array<[ResourceColor, number]> {
    if (this.skeleton) {
      return [['#8CFFFFFF', 0.0], ['#8CFFFFFF', 1.0]];
    }
    return this.colors().gradient.colors;
  }

  /** High contrast: hairline in the on-color; otherwise the 1 vp inner top highlight (inset 0 1px 0 white .8). */
  private borderOpts(): BorderOptions {
    if (this.profile.highContrast) {
      const hc: BorderOptions = { width: 1.5, color: this.colors().border };
      return hc;
    }
    const hl: string = this.dark ? LL_HIGHLIGHT_DARK : LL_HIGHLIGHT;
    const o: BorderOptions = {
      width: { top: 1, left: 0, right: 0, bottom: 0 } as EdgeWidths,
      color: { top: hl, left: '#00000000', right: '#00000000', bottom: '#00000000' } as EdgeColors
    };
    return o;
  }

  /** Living Light tile shadow: 0 16px 34px -20px rgba(40,50,110,.45) (theme token); deeper black in dark mode. */
  private shadowOpts(): ShadowOptions {
    if (this.dark) {
      const d: ShadowOptions = { radius: 20, color: '#66000000', offsetX: 0, offsetY: 12 };
      return d;
    }
    return TilesTheme.LL_SHADOW_TILE;
  }

  private radius(): number {
    return TilesTheme.LL_RADIUS_L;
  }

  @Builder
  badgePill() {
    Text(this.badgeText())
      .fontFamily(LL_FONT_FAMILY)
      .fontSize(Math.max(10, Math.round(11 * this.llFs())))
      .fontWeight(FontWeight.Bold)
      .fontColor(this.style().onSolid)
      .letterSpacing(0.6)
      .maxLines(1)
      .padding({ left: 8, right: 8, top: 3, bottom: 3 })
      .borderRadius(TilesTheme.LL_RADIUS_PILL)
      .backgroundColor(this.fg())
      .flexShrink(0)
  }

  /** Prototype icon: Material Symbols Rounded, FILL 1, wght 500, no plate -> SymbolGlyph (filled), medium weight. */
  @Builder
  iconBox() {
    Stack({ alignContent: Alignment.TopEnd }) {
      SymbolGlyph(tileIcon(this.tile.icon, this.tile.type))
        .fontSize(this.iconSize())
        .fontWeight(FontWeight.Medium)
        .fontColor([this.fg()])
        .width(this.iconSize())
        .height(this.iconSize())

      if (this.square() && this.badgeText().length > 0) {
        Circle()
          .width(10)
          .height(10)
          .fill(this.fg())
          .stroke(this.colors().bg1)
          .strokeWidth(2)
          .margin({ top: -3, right: -5 })
      }
    }
    .flexShrink(0)
    .accessibilityLevel('no')
  }

  private speakerSize(): number {
    return this.style().minTap > 48 ? 48 : 44;
  }

  /** Prototype read-aloud: 44 vp circle, rgba(0,0,0,.1), volume_up glyph at iconSize. */
  @Builder
  speaker() {
    Stack() {
      SymbolGlyph($r('sys.symbol.speaker_wave_2_fill'))
        .fontSize(Math.min(this.iconSize(), 26))
        .fontColor([this.fg()])
    }
    // Prototype: 44 vp circle (48 for senior / low vision), hit area grown to the profile's minimum tap target.
    .width(this.speakerSize())
    .height(this.speakerSize())
    .responseRegion({
      x: -Math.max(0, (this.style().minTap - this.speakerSize()) / 2),
      y: -Math.max(0, (this.style().minTap - this.speakerSize()) / 2),
      width: Math.max(this.speakerSize(), this.style().minTap),
      height: Math.max(this.speakerSize(), this.style().minTap)
    })
    .borderRadius(TilesTheme.LL_RADIUS_PILL)
    .backgroundColor(this.style().roundFill)
    .border({ width: this.profile.highContrast ? 1.5 : 0, color: withAlpha(this.colors().on, 0.35) })
    .flexShrink(0)
    .accessibilityText('Read ' + this.tile.title + ' aloud')
    .accessibilityRole(AccessibilityRoleType.BUTTON)
    .onClick(() => {
      this.speak();
    })
  }

  /** Title: Manrope 700, -0.012em, lineHeight 1.08; up to 2 lines, word breaks only, shrinks before ellipsis. */
  @Builder
  titleText() {
    Text(this.tile.title)
      .fontFamily(LL_FONT_FAMILY)
      .fontSize(this.titleFs())
      .maxFontSize(this.titleFs())
      .minFontSize(Math.max(10, Math.round(this.titleFs() * 0.75)))
      .heightAdaptivePolicy(TextHeightAdaptivePolicy.MAX_LINES_FIRST)
      .fontWeight(FontWeight.Bold)
      .fontColor(this.fg())
      .letterSpacing(this.small() ? 0 : TilesTheme.letterSpacing(this.titleFs()))
      .lineHeight(Math.round(this.titleFs() * 1.08))
      .maxLines(this.isDetail() ? 3 : 2)
      .wordBreak(WordBreak.NORMAL)
      .textOverflow({ overflow: TextOverflow.Ellipsis })
      .layoutWeight(this.square() ? 0 : 1)
  }

  /** Subtitle reads like the prototype's first text block: bodySize, lineHeight 1.3, opacity .92. */
  @Builder
  subtitleText() {
    Text(this.tile.subtitle)
      .fontFamily(LL_FONT_FAMILY)
      .fontSize(this.style().bodySize)
      .fontWeight(FontWeight.Medium)
      .fontColor(this.fg())
      .opacity(0.92)
      .lineHeight(Math.round(this.style().bodySize * 1.3))
      .maxLines(this.isDetail() ? 3 : (this.isCompact() ? 1 : this.style().bodyLines))
      .wordBreak(WordBreak.NORMAL)
      .textOverflow({ overflow: TextOverflow.Ellipsis })
      .width('100%')
  }

  /** Prototype head: row (icon + title + speaker, gap 8, centered) or, when the tile is < 200 vp wide, a column
   * (icon above title, gap 6 / small 4). Fades + rises in during a progressive build (headOp / headTy). */
  @Builder
  header() {
    Column() {
      if (this.square()) {
        Column({ space: this.small() ? 4 : 6 }) {
          this.iconBox()
          if (!this.titleRepeated()) {
            this.titleText()
          }
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      } else {
        Row({ space: 8 }) {
          this.iconBox()
          if (!this.titleRepeated()) {
            this.titleText()
          } else {
            Blank()
          }
          if (this.badgeText().length > 0) {
            this.badgePill()
          }
          if (this.showSpeaker()) {
            this.speaker()
          }
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
      }
    }
    .width('100%')
    .opacity(this.headShown() ? 1 : 0)
    .translate({ y: this.headShown() ? 0 : 12 })
    .animation({ duration: this.reduceMotion ? 0 : 450, curve: TilesTheme.ease() })
  }

  /** Skeleton shimmer band (prototype: 100deg rgba(255,255,255,.55) -> .98 -> .55, 1.4 s linear, right to left). */
  @Builder
  shimmerBand() {
    Column()
      .width(Math.max(1, this.cardW))
      .height('100%')
      .linearGradient({
        angle: 100,
        colors: [['#00FFFFFF', 0.0], ['#00FFFFFF', 0.3], ['#73FFFFFF', 0.5], ['#00FFFFFF', 0.7], ['#00FFFFFF', 1.0]]
      })
      .position({ left: 0, top: 0 })
      .translate({ x: this.cardW * (1 - 2 * this.shimmerT) })
      .hitTestBehavior(HitTestMode.Transparent)
      .accessibilityLevel('no')
  }

  @Builder
  card() {
    Stack({ alignContent: Alignment.TopStart }) {
      if (this.skeleton) {
        this.shimmerBand()
      }

      Column({ space: this.gapY() }) {
        this.header()

        if (this.tile.subtitle.length > 0 && !this.tiny()) {
          Column() {
            this.subtitleText()
          }
          .width('100%')
          .opacity(this.blockShown(-1) ? 1 : 0)
          .translate({ y: this.blockShown(-1) ? 0 : 12 })
          .animation({ duration: this.reduceMotion ? 0 : 450, curve: TilesTheme.ease() })
        }

        ForEach(this.slots(), (s: BlockSlot) => {
          Column() {
            BlockView({
              block: s.block,
              bs: this.style(),
              blockIndex: s.index,
              onAction: (a: TileAction) => {
                this.onAction(a, this.tile);
              }
            })
          }
          .width('100%')
          .opacity(this.blockShown(s.index) ? 1 : 0)
          .translate({ y: this.blockShown(s.index) ? 0 : 12 })
          .animation({ duration: this.reduceMotion ? 0 : 450, curve: TilesTheme.ease() })
          .onAreaChange((oldArea: Area, newArea: Area) => {
            const bottom: number = Number(newArea.position.y) + Number(newArea.height);
            if (!isNaN(bottom)) {
              this.bottoms.set(s.index, bottom);
              this.scheduleFit();
            }
          })
        }, (s: BlockSlot) => s.key)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
      .justifyContent(FlexAlign.Start)
      .padding(this.pad())

      if (this.overflowFade) {
        Column()
          .width('100%')
          .height(28)
          .linearGradient({
            direction: GradientDirection.Bottom,
            colors: [[withAlpha(this.colors().bg2, 0), 0.0], [this.colors().bg2, 1.0]]
          })
          .position({ left: 0, bottom: 0 })
          .hitTestBehavior(HitTestMode.Transparent)
          .accessibilityLevel('no')
      }
    }
    .width('100%')
    .height(this.fillHeight ? '100%' : 'auto')
    .constraintSize({ minHeight: this.minHeight() })
    .borderRadius(this.radius())
    // Living Light: 135deg palette gradient + soft indigo drop shadow + 1 vp inner top highlight (white .8).
    .linearGradient({ angle: 135, colors: this.bgStops() })
    .border(this.borderOpts())
    .shadow(this.shadowOpts())
    .clip(true)
    .scale({
      x: this.pressed ? TilesTheme.PRESS_SCALE : 1,
      y: this.pressed ? TilesTheme.PRESS_SCALE : 1
    })
    .animation({ curve: TilesTheme.ease(), duration: this.reduceMotion ? 0 : TilesTheme.LL_DUR })
    .onAreaChange((oldArea: Area, newArea: Area) => {
      const w: number = Number(newArea.width);
      const h: number = Number(newArea.height);
      let changed: boolean = false;
      if (!isNaN(w) && Math.abs(w - this.cardW) > 1) {
        this.cardW = w;
        changed = true;
      }
      if (!isNaN(h) && Math.abs(h - this.cardH) > 1) {
        this.cardH = h;
        changed = changed || this.fillHeight;
      }
      if (changed) {
        this.resetFit();
      }
    })
    .onTouch((e: TouchEvent) => {
      if (this.isDetail()) {
        return;
      }
      if (e.type === TouchType.Down) {
        this.pressed = true;
      } else if (e.type === TouchType.Up || e.type === TouchType.Cancel) {
        this.pressed = false;
      }
    })
    .onClick(() => {
      if (!this.isDetail() && !this.skeleton) {
        this.emit('open', this.tile.id, this.tile.title);
      }
    })
    .gesture(
      LongPressGesture({ repeat: false, duration: 500 })
        .onAction(() => {
          this.pressed = false;
          this.onLongPress(this.tile);
        })
    )
    .accessibilityText(this.skeleton ? 'Tiles is making ' + this.tile.title : this.a11yText())
    .accessibilityDescription(this.isDetail() ? '' : 'Double tap to open')
  }

  build() {
    // Outer: Living Light entrance (scale .92 + translateY 22 -> rest, LL ease 720 ms). Middle: live "breathe" loop.
    Stack() {
      Stack() {
        this.card()
      }
      .width('100%')
      .height(this.fillHeight ? '100%' : 'auto')
      .scale({ x: this.breatheScale, y: this.breatheScale })
    }
    .width('100%')
    .height(this.fillHeight ? '100%' : 'auto')
    .opacity(this.appearOpacity)
    .scale({ x: this.appearScale, y: this.appearScale })
    .translate({ y: this.appearTy })
    .onAppear(() => {
      if (this.animateIn) {
        this.getUIContext().animateTo({ curve: TilesTheme.ease(), duration: TilesTheme.LL_DUR }, () => {
          this.appearScale = 1;
          this.appearTy = 0;
          this.appearOpacity = 1;
        });
      }
      this.syncBreathe();
      this.startShimmer();
    })
  }
}
