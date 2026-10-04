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
      return 'wand_and_stars_fill';
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
