import { curves } from '@kit.ArkUI';
import { Profile } from '../model/Tile';

/**
 * Tiles visual language (docs/TILES_SPEC.md): warm, colorful, friendly. Light warm background with a dark mode,
 * eight tile palette keys, each with an on-color that passes WCAG 2.1 AA (most pairs are >= 7:1).
 * Senior / low-vision profiles (Profile.highContrast) use deeper high-contrast variants (>= 6:1, white text).
 *
 * Usage:
 *   const c: TileColors = TilesTheme.tile(spec.color, profile.highContrast, dark);
 *   const p: ThemePalette = TilesTheme.palette(dark, profile.highContrast);
 *   const t: TypeScale = TilesTheme.type(profile.textScale);
 */

export const PALETTE_KEYS: string[] = ['sun', 'coral', 'sky', 'mint', 'grape', 'peach', 'leaf', 'ink'];

/** Colors for one tile. `soft` is a translucent on-color wash for chips / tracks inside the tile. */
export class TileColors {
  key: string = 'sky';
  bg: string = '#3DA5FF';
  on: string = '#06243F';
  onMuted: string = '#B306243F';
  soft: string = '#2606243F';
  border: string = '#00000000';
  pressed: string = '#33000000';
}

/** App-level surfaces and text colors. */
export class ThemePalette {
  dark: boolean = false;
  bg: string = '#F6F3EE';
  surface: string = '#FFFFFF';
  surfaceAlt: string = '#EFEAE2';
  text: string = '#1C2230';
  textMuted: string = '#5B6170';
  border: string = '#E2DCD2';
  accent: string = '#3DA5FF';
  onAccent: string = '#06243F';
  danger: string = '#C62828';
  onDanger: string = '#FFFFFF';
  success: string = '#1B7F4B';
  onSuccess: string = '#FFFFFF';
  scrim: string = '#661C2230';
  barBg: string = '#FFFFFF';
  shadow: string = '#1A1C2230';
}

/** Font sizes in fp, already multiplied by the profile's textScale. */
export class TypeScale {
  scale: number = 1.0;
  display: number = 40; // big numbers / hero values
  headline: number = 28; // screen titles, greeting
  title: number = 22; // tile titles
  body: number = 17; // tile content
  label: number = 15; // buttons, chips
  caption: number = 13; // meta lines
}

class Pair {
  bg: string;
  on: string;

  constructor(bg: string, on: string) {
    this.bg = bg;
    this.on = on;
  }
}

/** Standard light-mode tile colors. On-colors are deep tints of the hue (all >= 7:1 except grape ~6:1). */
function basePair(key: string): Pair {
  switch (key) {
    case 'sun':
      return new Pair('#FFC83D', '#3D2C00');
    case 'coral':
      return new Pair('#FF6B5A', '#3B0E08');
    case 'sky':
      return new Pair('#3DA5FF', '#06243F');
    case 'mint':
      return new Pair('#2ED3A0', '#04362A');
    case 'grape':
      return new Pair('#9B7BFF', '#170B38');
    case 'peach':
      return new Pair('#FF9F6B', '#3E1A05');
    case 'leaf':
      return new Pair('#7BD957', '#173A07');
    case 'ink':
      return new Pair('#1C2230', '#FFFFFF');
    default:
      return new Pair('#3DA5FF', '#06243F');
  }
}

/** Dark-mode tile colors: same hues, slightly deeper so they do not glare on the dark background. */
function darkPair(key: string): Pair {
  switch (key) {
    case 'sun':
      return new Pair('#F2B92E', '#2E2100');
    case 'coral':
      return new Pair('#F2604F', '#2E0904');
    case 'sky':
      return new Pair('#3696EB', '#03182C');
    case 'mint':
      return new Pair('#26BF90', '#022A20');
    case 'grape':
      return new Pair('#8E6CF5', '#100728');
    case 'peach':
      return new Pair('#F2915C', '#2E1203');
    case 'leaf':
      return new Pair('#6CC94A', '#102A04');
    case 'ink':
      return new Pair('#2A3245', '#FFFFFF');
    default:
      return new Pair('#3696EB', '#03182C');
  }
}

/** High-contrast variants (senior / low vision): saturated deep backgrounds + pure white/black text (>= 6:1). */
function hcPair(key: string, dark: boolean): Pair {
  switch (key) {
    case 'sun':
      return new Pair('#FFC83D', '#000000');
    case 'coral':
      return new Pair('#B3261E', '#FFFFFF');
    case 'sky':
      return new Pair('#0B57D0', '#FFFFFF');
    case 'mint':
      return new Pair('#00664F', '#FFFFFF');
    case 'grape':
      return new Pair('#5B3CC4', '#FFFFFF');
    case 'peach':
      return new Pair('#A63F00', '#FFFFFF');
    case 'leaf':
      return new Pair('#2E6B12', '#FFFFFF');
    case 'ink':
      return dark ? new Pair('#FFFFFF', '#000000') : new Pair('#000000', '#FFFFFF');
    default:
      return new Pair('#0B57D0', '#FFFFFF');
  }
}

/** '#RRGGBB' + alpha (0..1) -> '#AARRGGBB'. */
export function withAlpha(hex: string, alpha: number): string {
  const a: number = Math.max(0, Math.min(255, Math.round(alpha * 255)));
  let h: string = a.toString(16).toUpperCase();
  if (h.length < 2) {
    h = '0' + h;
  }
  const rgb: string = hex.length === 9 ? hex.substring(3) : hex.substring(1);
  return '#' + h + rgb;
}

export class TilesTheme {
  // Radii (vp)
  static readonly RADIUS_TILE: number = 24;
  static readonly RADIUS_TILE_LG: number = 28;
  static readonly RADIUS_SHEET: number = 28;
  static readonly RADIUS_CHIP: number = 999;
  static readonly RADIUS_BUTTON: number = 16;
  static readonly RADIUS_INNER: number = 14;

  // Spacing (vp)
  static readonly SPACE_XXS: number = 2;
  static readonly SPACE_XS: number = 4;
  static readonly SPACE_S: number = 8;
  static readonly SPACE_M: number = 12;
  static readonly SPACE_L: number = 16;
  static readonly SPACE_XL: number = 24;
  static readonly SPACE_XXL: number = 32;
  static readonly GUTTER: number = 16; // screen side padding
  static readonly GRID_GAP: number = 12; // gap between tiles
  static readonly TILE_PAD: number = 16; // padding inside a tile

  // Tap targets (vp): WCAG / platform minimum, larger for senior & low-vision profiles.
  static readonly TAP_MIN: number = 48;
  static readonly TAP_SENIOR: number = 64;

  // Motion durations (ms)
  static readonly DUR_INSTANT: number = 100;
  static readonly DUR_FAST: number = 150;
  static readonly DUR_MED: number = 250;
  static readonly DUR_SLOW: number = 400;
  static readonly DUR_GENERATE: number = 900; // "Tiles is making…" shimmer cycle
  static readonly STAGGER: number = 60; // delay between tiles springing in
  static readonly PRESS_SCALE: number = 0.96;

  /** Tile springs in when generated (slightly bouncy). */
  static springIn(): curves.ICurve {
    return curves.springMotion(0.45, 0.72);
  }

  /** Press / release feedback (fast, little overshoot). */
  static springPress(): curves.ICurve {
    return curves.responsiveSpringMotion(0.2, 0.86);
  }

  /** Grid reflow / reorder (calm, no overshoot). */
  static springReflow(): curves.ICurve {
    return curves.springMotion(0.5, 0.92);
  }

  /** Sheets and tile -> detail transitions. */
  static springSheet(): curves.ICurve {
    return curves.interpolatingSpring(0, 1, 228, 30);
  }

  /** Duration helper honoring reduced motion (0 = no animation). */
  static dur(ms: number, reducedMotion: boolean): number {
    return reducedMotion ? 0 : ms;
  }

  static isPaletteKey(key: string): boolean {
    return PALETTE_KEYS.indexOf(key) >= 0;
  }

  /** Colors for a tile palette key. Unknown keys fall back to 'sky'. */
  static tile(key: string, highContrast: boolean, dark: boolean): TileColors {
    const k: string = TilesTheme.isPaletteKey(key) ? key : 'sky';
    const p: Pair = highContrast ? hcPair(k, dark) : (dark ? darkPair(k) : basePair(k));
    const c: TileColors = new TileColors();
    c.key = k;
    c.bg = p.bg;
    c.on = p.on;
    c.onMuted = withAlpha(p.on, highContrast ? 0.92 : 0.74);
    c.soft = withAlpha(p.on, highContrast ? 0.22 : 0.14);
    c.pressed = withAlpha(p.on, 0.18);
    // High contrast adds a visible outline (sun/ink tiles can sit close to the page background).
    c.border = highContrast ? (dark ? '#FFFFFF' : '#000000') : '#00000000';
    return c;
  }

  /** Convenience: colors for a tile under a profile. */
  static tileFor(key: string, profile: Profile, dark: boolean): TileColors {
    return TilesTheme.tile(key, profile.highContrast, dark);
  }

  /** App surfaces. High contrast pushes text to pure black/white and strengthens borders. */
  static palette(dark: boolean, highContrast: boolean): ThemePalette {
    const p: ThemePalette = new ThemePalette();
    p.dark = dark;
    if (dark) {
      p.bg = '#14161C';
      p.surface = '#1E212A';
      p.surfaceAlt = '#272B36';
      p.text = '#F4F1EC';
      p.textMuted = '#A9AEBB';
      p.border = '#323746';
      p.accent = '#3DA5FF';
      p.onAccent = '#06243F';
      p.danger = '#FF6B5A';
      p.onDanger = '#3B0E08';
      p.success = '#2ED3A0';
      p.onSuccess = '#04362A';
      p.scrim = '#B3000000';
      p.barBg = '#232733';
      p.shadow = '#66000000';
    }
    if (highContrast) {
      p.text = dark ? '#FFFFFF' : '#000000';
      p.textMuted = dark ? '#E0E0E0' : '#262626';
      p.border = dark ? '#FFFFFF' : '#000000';
      p.accent = dark ? '#8AC6FF' : '#0B57D0';
      p.onAccent = dark ? '#000000' : '#FFFFFF';
      p.danger = dark ? '#FF8A80' : '#B3261E';
      p.onDanger = dark ? '#000000' : '#FFFFFF';
      p.success = dark ? '#5EE8B7' : '#00664F';
      p.onSuccess = dark ? '#000000' : '#FFFFFF';
      p.surface = dark ? '#000000' : '#FFFFFF';
      p.bg = dark ? '#0A0A0A' : '#FBF9F5';
    }
    return p;
  }

  static paletteFor(profile: Profile, dark: boolean): ThemePalette {
    return TilesTheme.palette(dark, profile.highContrast);
  }

  /** Type scale multiplied by textScale (clamped 0.85..2.0). */
  static type(textScale: number): TypeScale {
    const s: number = isFinite(textScale) ? Math.max(0.85, Math.min(2.0, textScale)) : 1.0;
    const t: TypeScale = new TypeScale();
    t.scale = s;
    t.display = Math.round(40 * s);
    t.headline = Math.round(28 * s);
    t.title = Math.round(22 * s);
    t.body = Math.round(17 * s);
    t.label = Math.round(15 * s);
    t.caption = Math.round(13 * s);
    return t;
  }

  static typeFor(profile: Profile): TypeScale {
    return TilesTheme.type(profile.textScale);
  }

  /** Minimum tap target for a profile (senior / low vision get 64 vp). */
  static tapTarget(profile: Profile): number {
    return profile.id === 'senior' || profile.id === 'lowvision' || profile.textScale >= 1.3 ?
      TilesTheme.TAP_SENIOR : TilesTheme.TAP_MIN;
  }

  /** Columns a tile spans: '1x1' -> 1, '2x1' / '2x2' -> 2 (clamped to the grid's column count). */
  static colSpan(size: string, columns: number): number {
    const want: number = size === '2x1' || size === '2x2' ? 2 : 1;
    return Math.max(1, Math.min(columns, want));
  }

  static rowSpan(size: string): number {
    return size === '2x2' ? 2 : 1;
  }

  /** Corner radius for a tile size (big tiles get the 28 vp radius). */
  static radiusFor(size: string): number {
    return size === '2x2' ? TilesTheme.RADIUS_TILE_LG : TilesTheme.RADIUS_TILE;
  }
}
