import { sysSymbol } from './SymbolTable';

/**
 * Resolved visual style handed from TileView to every block renderer, so blocks never read the theme or the
 * profile directly: one place decides colors (palette + on-color + high contrast) and type scale.
 */
export class BlockStyle {
  /** Primary text / icon color on the tile surface (passes WCAG AA against `bg`). */
  fg: string = '#1C2230';
  /** Secondary text on the tile surface. */
  fgDim: string = '#3A4152';
  /** Tile background. */
  bg: string = '#3DA5FF';
  /** Translucent "well" drawn on top of the tile for inner chips / bars. */
  well: string = '#26FFFFFF';
  /** Solid contrasting surface (used for primary buttons, alert cards). */
  solid: string = '#FFFFFF';
  /** Text color on `solid`. */
  onSolid: string = '#1C2230';
  /** Font scale (profile.textScale). */
  scale: number = 1.0;
  /** High contrast profile flag (thicker borders, no translucency). */
  highContrast: boolean = false;
  /** Minimum tap target in vp (48, or 64 for senior / low-vision). */
  minTap: number = 48;
  /** Detail (full-screen) rendering: show everything bigger. */
  detail: boolean = false;
  /** Disable non-essential motion. */
  reduceMotion: boolean = false;
  /** Small (1x1) tile: blocks render a condensed variant. */
  compact: boolean = false;
  /** Layout tier from the tile's MEASURED size: 'compact' | 'medium' | 'full' (detail is always 'full'). */
  tier: string = 'full';
  /** Content column narrower than ~230 vp (scaled): stack instead of side-by-side, shorter labels. */
  narrow: boolean = false;
  /** Very narrow (< ~120 vp scaled, e.g. 1x1 in a 4-column grid): hero value only, no controls. */
  tiny: boolean = false;

  // ---------- Living Light (design C) shared block tokens — filled by TileView from the prototype formulas ----------
  // Prototype: titleSize 19*fs, bodySize 14*fs, numSize 38*fs, iconSize 24*fs (small tiles: .82/.9/.78/.85),
  // chipSize max(11, body*.85), btnH max(40, body*2.5), btnPad max(10, body*.9), rowMin max(28, body*2).
  /** Tile gradient stops (135deg) — e.g. a checked checkbox's tick uses `bgTo`-ish white on the on-color. */
  bgFrom: string = '#D4E4FF';
  bgTo: string = '#A9C4FF';
  /** Progress track / timer ring track: rgba(0,0,0,.14). */
  track: string = '#24000000';
  /** Secondary pill / chip / round control fill: rgba(0,0,0,.1) (`well` holds the same value). */
  pill: string = '#1A000000';
  /** Profile font multiplier from the prototype PROFILES table (Halina 1.1, Zosia .95, Michał 1.3, Daniel .78). */
  llFs: number = 1.0;
  /** Measured tile width < 120 vp (prototype `small`). */
  small: boolean = false;
  /** Measured tile width < 200 vp (prototype `square`): header stacks, no speaker/timer controls. */
  square: boolean = false;
  titleSize: number = 19;
  bodySize: number = 14;
  numSize: number = 38;
  iconSize: number = 24;
  chipSize: number = 12;
  btnH: number = 40;
  btnPad: number = 13;
  rowMin: number = 28;
  /** Body text max lines (prototype: 1 when the tile is shorter than 120 vp, else 3). */
  bodyLines: number = 3;
  /** Fit-to-tile squeeze (1 = natural size): TileView lowers it when the last block still overflows the tile, so
   * hero numbers shrink, captions under them hide and paragraphs lose lines instead of being cut off. */
  squeeze: number = 1;
  /** Gap between blocks (prototype gapY: 8, small 3). */
  gapY: number = 8;
  /** Checklist circle: 24 vp, 2.5 vp stroke; progress bar 12 vp / radius 6. */
  checkSize: number = 24;
  checkStroke: number = 2.5;
  barH: number = 12;
  /** Round icon controls (play/pause, read aloud): 44 vp, rgba(0,0,0,.12) / .1 fill. */
  roundSize: number = 44;
  roundFill: string = '#1F000000';
  /** Font family (Manrope) — pass to .fontFamily(). */
  font: string = 'Manrope';
  /** Hero numbers: weight 800, letterSpacing -0.03em, lineHeight .95. */
  numWeight: number = 800;
  /** Title weight 700, letterSpacing -0.012em. */
  titleWeight: number = 700;

  /** letterSpacing (fp) for hero numbers: -0.03em. */
  numLs(): number {
    return Math.round(this.numSize * -0.03 * 100) / 100;
  }

  /** letterSpacing (fp) for titles: -0.012em (0 on small tiles, like the prototype). */
  titleLs(size: number): number {
    return this.small ? 0 : Math.round(size * -0.012 * 100) / 100;
  }

  /** Text color for content drawn on `solid` (primary pill button / checked circle tick). */
  onSolidColor(): string {
    return this.onSolid;
  }

  /** Pick a per-tier limit (items, rows, buttons...). */
  limit(compactN: number, mediumN: number, fullN: number, detailN: number): number {
    if (this.detail) {
      return detailN;
    }
    if (this.compact || this.tier === 'compact') {
      return compactN;
    }
    return this.tier === 'medium' ? mediumN : fullN;
  }

  fs(base: number): number {
    return Math.round(base * this.scale * (this.detail ? 1.15 : 1.0));
  }
}

/** Parameter object for block @Builders (single object literal → reactive pass-by-reference). */
export class BlockArgs {
  style: BlockStyle = new BlockStyle();
}

/** Friendly icon keys / tile types -> SymbolGlyph names. */
function aliasOf(k: string): string {
  switch (k) {
    case 'pill':
    case 'pills':
    case 'medicine':
      return 'cross_case_fill';
    case 'phone':
    case 'call':
      return 'phone_fill';
    case 'weather':
      return 'cloud_sun_fill';
    case 'rain':
      return 'umbrella';
    case 'sun':
      return 'sun_max_fill';
    case 'snow':
      return 'snowflake';
    case 'guardian':
    case 'shield':
    case 'scam':
      return 'phone_shield_fill';
    case 'sos':
      return 'phone_sos';
    case 'alert':
    case 'warning':
      return 'exclamationmark_triangle_fill';
    case 'bell':
    case 'reminder':
      return 'bell_fill';
    case 'alarm':
      return 'alarm_fill';
    case 'focus':
      return 'stopwatch_fill';
    case 'screentime':
      return 'hourglass';
    case 'book':
    case 'homework':
    case 'school':
      return 'graduationcap_fill';
    case 'check':
    case 'done':
      return 'checkmark_circle_fill';
    case 'list':
      return 'list_bullet';
    case 'person':
      return 'person_fill';
    case 'people':
    case 'friends':
    case 'plan':
      return 'person_2_fill';
    case 'home':
    case 'house':
      return 'house_fill';
    case 'car':
      return 'car_fill';
    case 'bus':
    case 'commute':
      return 'bus_fill';
    case 'tram':
      return 'tram_fill';
    case 'walk':
      return 'figure_walk';
    case 'star':
      return 'star_fill';
    case 'heart':
      return 'heart_fill';
    case 'speaker':
    case 'speak':
      return 'speaker_wave_2_fill';
    case 'calendar':
      return 'calendar_fill';
    case 'food':
    case 'dinner':
      return 'fork_knife';
    case 'cup':
    case 'coffee':
      return 'cup_fill';
    case 'game':
      return 'gamecontroller_fill';
    case 'gift':
      return 'gift_fill';
    case 'map':
    case 'adventure':
      return 'flag_fill';
    case 'note':
      return 'doc_text_fill';
    case 'trophy':
      return 'star_trophy_fill';
    case 'music':
      return 'music_fill';
    case 'camera':
      return 'camera_fill';
    case 'message':
    case 'sms':
      return 'message_fill';
    case 'mic':
      return 'mic_fill';
    case 'moon':
      return 'moon_fill';
    case 'bulb':
    case 'idea':
      return 'lightbulb_fill';
    case 'mail':
      return 'envelope_fill';
    case 'vote':
    case 'thumbsup':
      return 'hand_thumbsup_fill';
    case 'sparkle':
    case 'custom':
    case 'auto_awesome':
      return 'wand_and_stars_fill';
    // Material Symbols names used by the Living Light prototype (design/tiles-motion) -> closest HarmonyOS symbol.
    case 'medication':
      return 'cross_case_fill';
    case 'restaurant':
      return 'fork_knife';
    case 'directions_run':
      return 'figure_run';
    case 'music_note':
      return 'music_fill';
    case 'footprint':
    case 'directions_walk':
      return 'figure_walk';
    case 'event':
      return 'calendar_fill';
    case 'group':
      return 'person_2_fill';
    case 'rainy':
      return 'umbrella';
    case 'emergency':
      return 'phone_sos';
    case 'timer':
      return 'stopwatch_fill';
    case 'menu_book':
      return 'book_open_fill';
    case 'photo_camera':
    case 'photo_library':
      return 'camera_fill';
    case 'bolt':
      return 'bolt_fill';
    case 'child_care':
    case 'elderly':
      return 'person_fill';
    case 'visibility_off':
      return 'eye_slash';
    case 'volume_up':
      return 'speaker_wave_2_fill';
    case 'explore':
      return 'map';
    case 'spellcheck':
      return 'doc_text_fill';
    case 'mail_outline':
      return 'envelope_fill';
    default:
      return k;
  }
}

/**
 * Resolve TileSpec.icon (sys.symbol name, friendly key, or empty) + tile type to a SymbolGlyph resource.
 * Never fails: unknown names fall back to the type's icon, then to a generic "magic" glyph.
 */
export function tileIcon(icon: string, type: string): Resource {
  const k: string = icon.toLowerCase().replace('sys.symbol.', '').trim();
  if (k.length > 0) {
    const r: Resource | undefined = sysSymbol(aliasOf(k));
    if (r !== undefined) {
      return r;
    }
  }
  const t: Resource | undefined = sysSymbol(aliasOf(type.toLowerCase()));
  return t !== undefined ? t : $r('sys.symbol.wand_and_stars_fill');
}

/** Icon for a TileAction kind (buttons). */
export function actionIcon(kind: string): Resource {
  switch (kind) {
    case 'call':
      return $r('sys.symbol.phone_fill');
    case 'remind':
      return $r('sys.symbol.bell_fill');
    case 'speak':
      return $r('sys.symbol.speaker_wave_2_fill');
    case 'done':
      return $r('sys.symbol.checkmark');
    case 'vote':
      return $r('sys.symbol.hand_thumbsup_fill');
    case 'navigate':
      return $r('sys.symbol.figure_walk');
    case 'sos':
      return $r('sys.symbol.phone_sos');
    case 'dismiss':
      return $r('sys.symbol.xmark');
    default:
      return $r('sys.symbol.arrow_right');
  }
}
