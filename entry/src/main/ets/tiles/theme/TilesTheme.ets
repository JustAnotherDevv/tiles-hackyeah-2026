import { curves } from '@kit.ArkUI';
import { Profile } from '../model/Tile';

/*
 * Living Light (design direction C, design/tiles-motion/source/Tiles_Stage.dc.html THEMES.C):
 * soft 135deg pastel gradient tiles, frosted-glass surfaces, indigo ink, calm cubic-bezier(.22,1,.36,1) motion.
 * Existing names are kept (values adapted) so every caller keeps compiling; LL_* names are additive.
 */

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
/** Living Light palette names (coral -> rose, grape -> plum; sand is new). All are accepted by TilesTheme.tile(). */
export const LL_PALETTE_KEYS: string[] = ['sun', 'sky', 'leaf', 'rose', 'plum', 'sand', 'ink', 'mint', 'peach'];

/** App font family (Manrope, registered in EntryAbility; falls back to the system font if registration failed). */
export const LL_FONT_FAMILY: string = 'Manrope';

/** A linear gradient ready for `.linearGradient({ angle: g.angle, colors: g.colors })`. */
export class LLGradient {
  angle: number = 135;
  colors: Array<[ResourceColor, number]> = [];

  constructor(angle: number, colors: Array<[ResourceColor, number]>) {
    this.angle = angle;
    this.colors = colors;
  }
}

/** Per-profile home grid layout from the prototype PROFILES table. */
export class ProfileLayout {
  person: string = 'daniel'; // halina | zosia | michal | daniel
  cols: number = 4;
  rowH: number = 104; // vp, one grid row
  gap: number = 10; // vp between tiles
  pad: number = 16; // vp screen side padding
  fs: number = 0.78; // font scale multiplier for tile text
  askH: number = 52; // vp, ask dock height
  reducedMotion: boolean = false;
  greeting: string = 'Morning, Daniel';
}

/** Colors for one tile. `soft` is a translucent on-color wash for chips / tracks inside the tile. */
export class TileColors {
  key: string = 'sky';
  bg: string = '#3DA5FF';
  on: string = '#06243F';
  onMuted: string = '#B306243F';
  soft: string = '#2606243F';
  border: string = '#00000000';
  pressed: string = '#33000000';
  /** Living Light gradient stops (135deg): bg1 -> bg2. `bg` is kept as a flat mid-tone fallback. */
  bg1: string = '#D4E4FF';
  bg2: string = '#A9C4FF';
  angle: number = 135;
  /** Ready-made gradient for `.linearGradient({ angle: c.gradient.angle, colors: c.gradient.colors })`. */
  gradient: LLGradient = new LLGradient(135, [['#D4E4FF', 0.0], ['#A9C4FF', 1.0]]);
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
  // ---- Living Light additions ----
  /** Page background gradient (165deg, 3 stops). Use `.linearGradient({ angle: p.bgGradient.angle, colors: ... })`. */
  bgGradient: LLGradient = new LLGradient(165, [['#EDF1FC', 0.0], ['#F6F0FA', 0.5], ['#FFF3EA', 1.0]]);
  /** Launcher / lock-screen wallpaper gradient. */
  wallpaper: LLGradient = new LLGradient(165, [['#C9D4FF', 0.0], ['#F3D4EC', 0.6], ['#FFE1CC', 1.0]]);
  /** Incoming call / guardian call background gradient + foreground. */
  callBg: LLGradient = new LLGradient(165, [['#1D2140', 0.0], ['#2E3466', 1.0]]);
  callFg: string = '#F3F5FF';
  /** Assistant creature / avatar gradient. */
  creature: LLGradient = new LLGradient(135, [['#E3D5FF', 0.0], ['#C2ADFF', 1.0]]);
  surface2: string = '#121D2140';
  ink: string = '#1D2140';
  onInk: string = '#F3F5FF';
  muted: string = '#5B6283';
  line: string = '#1F1D2140';
  sheetBg: string = '#D6FFFFFF';
  inputBg: string = '#0F1D2140';
  toastBg: string = '#1D2140';
  toastFg: string = '#F3F5FF';
  statusInk: string = '#1D2140';
  dangerSoft: string = '#1FC62B4A';
  dangerInk: string = '#8E1B33';
  ok: string = '#1F7A4D';
  okSoft: string = '#1F1F7A4D';
  okInk: string = '#145C38';
  askMicBg: string = '#29FFFFFF';
  /** Skeleton shimmer stops (white .55 -> .98 -> .55); animate the gradient offset / a translate. */
  skeleton: LLGradient = new LLGradient(100, [['#8CFFFFFF', 0.35], ['#FAFFFFFF', 0.5], ['#8CFFFFFF', 0.65]]);
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
  bg1: string;
  bg2: string;
  on: string;

  constructor(bg1: string, bg2: string, on: string) {
    this.bg1 = bg1;
    this.bg2 = bg2;
    this.on = on;
  }
}

/** Legacy / alias keys -> Living Light names. */
function llKey(key: string): string {
  if (key === 'coral') {
    return 'rose';
  }
  if (key === 'grape') {
    return 'plum';
  }
  return LL_PALETTE_KEYS.indexOf(key) >= 0 ? key : 'sky';
}

/** Living Light tile gradients (135deg) + on-colors, verbatim from THEMES.C.pal. */
function basePair(key: string): Pair {
  switch (llKey(key)) {
    case 'sun':
      return new Pair('#FFE48F', '#FFB870', '#3B2500');
    case 'sky':
      return new Pair('#D4E4FF', '#A9C4FF', '#0F2A5F');
    case 'leaf':
      return new Pair('#D2F3D8', '#9FDFB3', '#0E3B1F');
    case 'rose':
      return new Pair('#FFD6DE', '#FFADBE', '#5A1424');
    case 'plum':
      return new Pair('#E6D9FF', '#C2ADFF', '#2B1A5E');
    case 'sand':
      return new Pair('#F7F0E6', '#E8DCCB', '#3A2E1E');
    case 'ink':
      return new Pair('#2A2E48', '#1B1E33', '#F0F2FF');
    case 'mint':
      return new Pair('#D3F5EF', '#9FE3DA', '#0B3B35');
    case 'peach':
      return new Pair('#FFDFC9', '#FFBE98', '#4A2208');
    default:
      return new Pair('#D4E4FF', '#A9C4FF', '#0F2A5F');
  }
}

/** Dark (deep indigo) variant: pastel tiles stay luminous; the ink tile lifts off the #14162A page. */
function darkPair(key: string): Pair {
  if (llKey(key) === 'ink') {
    return new Pair('#3A3F66', '#2A2E4D', '#F0F2FF');
  }
  return basePair(key);
}

/** Midpoint of two '#RRGGBB' colors (flat fallback for callers that still use a solid `bg`). */
function mix(a: string, b: string): string {
  const x: number = parseInt(a.substring(1), 16);
  const y: number = parseInt(b.substring(1), 16);
  const r: number = Math.round((((x >> 16) & 255) + ((y >> 16) & 255)) / 2);
  const g: number = Math.round((((x >> 8) & 255) + ((y >> 8) & 255)) / 2);
  const bl: number = Math.round(((x & 255) + (y & 255)) / 2);
  const v: string = ((1 << 24) + (r << 16) + (g << 8) + bl).toString(16).toUpperCase().substring(1);
  return '#' + v;
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
  // Radii (vp) — Living Light: rL 26 / rM 18 / rS 14 / pill
  static readonly RADIUS_TILE: number = 26;
  static readonly RADIUS_TILE_LG: number = 26;
  static readonly RADIUS_SHEET: number = 26;
  static readonly RADIUS_CHIP: number = 999;
  static readonly RADIUS_BUTTON: number = 18;
  static readonly RADIUS_INNER: number = 14;
  static readonly LL_RADIUS_L: number = 26;
  static readonly LL_RADIUS_M: number = 18;
  static readonly LL_RADIUS_S: number = 14;
  static readonly LL_RADIUS_PILL: number = 999;

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
  static readonly DUR_FAST: number = 160;
  static readonly DUR_MED: number = 280;
  static readonly DUR_SLOW: number = 560;
  static readonly DUR_GENERATE: number = 1400; // skeleton shimmer cycle (prototype: shimmer 1.4s linear)
  static readonly STAGGER: number = 70; // delay between tiles springing in
  static readonly PRESS_SCALE: number = 0.96;

  // ---- Living Light motion (THEMES.C: ease cubic-bezier(.22,1,.36,1), dur 720, sheetDur 560) ----
  static readonly LL_DUR: number = 720;
  static readonly LL_SHEET_DUR: number = 560;
  /** Tile birth: from scale(.92) translateY(22vp), opacity 0. */
  static readonly LL_ENTER_SCALE: number = 0.92;
  static readonly LL_ENTER_TY: number = 22;
  /** Live tiles breathe 1 -> 1.022 -> 1 (2.4 s period, half-period 1200 ms per animation leg). */
  static readonly LL_BREATHE_SCALE: number = 1.022;
  static readonly LL_BREATHE_MS: number = 2400;
  static readonly LL_SHIMMER_MS: number = 1400;
  static readonly LL_DOTS_MS: number = 1000; // typing dots: translateY 0 -> -6 -> 0
  static readonly LL_DOTS_TY: number = 6;
  static readonly LL_PULSE_MS: number = 1400; // mic/listening pulse: opacity 1->.45, scale 1->.8
  static readonly LL_RING_MS: number = 1600; // incoming call ring: 0 -> 28 vp halo
  static readonly LL_WAVE_MS: number = 900; // voice wave bars scaleY .3 -> 1
  static readonly LL_BLINK_MS: number = 4200; // creature eye blink

  // ---- Living Light type (weight 700, letter-spacing -0.012em) ----
  static readonly LL_FONT_FAMILY: string = LL_FONT_FAMILY;
  static readonly LL_WEIGHT: FontWeight = FontWeight.Bold;
  static readonly LL_LETTER_EM: number = -0.012;

  // ---- Living Light elevation ----
  /** Tile / card shadow (CSS 0 16px 34px -20px rgba(40,50,110,.45); spread approximated). */
  static readonly LL_SHADOW_TILE: ShadowOptions = { radius: 20, color: '#4028326E', offsetX: 0, offsetY: 12 };
  /** Bottom sheet / ask dock shadow (CSS 0 -20px 60px -24px rgba(40,50,110,.4)). */
  static readonly LL_SHADOW_SHEET: ShadowOptions = { radius: 36, color: '#4028326E', offsetX: 0, offsetY: -10 };
  /** Soft shadow for small floating pills / toasts. */
  static readonly LL_SHADOW_SOFT: ShadowOptions = { radius: 12, color: '#2628326E', offsetX: 0, offsetY: 6 };
  /** Frosted glass: blur 26 + saturate 1.5. Use `.backdropBlur(TilesTheme.LL_BLUR)` on translucent surfaces,
   * or `.backgroundBlurStyle(TilesTheme.LL_BLUR_STYLE)` for the system material. */
  static readonly LL_BLUR: number = 26;
  static readonly LL_SATURATE: number = 1.5;
  static readonly LL_BLUR_STYLE: BlurStyle = BlurStyle.Thin;
  static readonly LL_BLUR_STYLE_SHEET: BlurStyle = BlurStyle.Regular;

  /** Living Light easing: cubic-bezier(.22,1,.36,1). */
  static ease(): curves.ICurve {
    return curves.cubicBezierCurve(0.22, 1, 0.36, 1);
  }

  /** letterSpacing in fp for a font size (prototype: -0.012em). */
  static letterSpacing(fontSize: number): number {
    return Math.round(fontSize * TilesTheme.LL_LETTER_EM * 100) / 100;
  }

  /** Per-profile grid (prototype PROFILES): senior=halina, kid=zosia, lowvision=michal, everyday=daniel. */
  static layoutFor(profile: Profile): ProfileLayout {
    return TilesTheme.layoutForId(profile.id);
  }

  static layoutForId(id: string): ProfileLayout {
    const l: ProfileLayout = new ProfileLayout();
    if (id === 'senior') {
      l.person = 'halina';
      l.cols = 2;
      l.rowH = 136;
      l.gap = 12;
      l.fs = 1.1;
      l.askH = 64;
      l.greeting = 'Dzień dobry, Halino';
    } else if (id === 'kid') {
      l.person = 'zosia';
      l.cols = 2;
      l.rowH = 128;
      l.gap = 12;
      l.fs = 0.95;
      l.askH = 56;
      l.greeting = 'Hej, Zosia!';
    } else if (id === 'lowvision') {
      l.person = 'michal';
      l.cols = 2;
      l.rowH = 150;
      l.gap = 14;
      l.fs = 1.3;
      l.askH = 72;
      l.reducedMotion = true;
      l.greeting = 'Dzień dobry, Michale';
    }
    return l;
  }

  /** Tile springs in when generated (slightly bouncy). */
  static springIn(): curves.ICurve {
    return curves.springMotion(0.55, 0.86);
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
    return PALETTE_KEYS.indexOf(key) >= 0 || LL_PALETTE_KEYS.indexOf(key) >= 0;
  }

  /** Gradient for a palette key (shortcut for tile(key,...).gradient). */
  static tileGradient(key: string, dark: boolean): LLGradient {
    return TilesTheme.tile(key, false, dark).gradient;
  }

  /** Colors for a tile palette key (legacy or LL name). Unknown keys fall back to 'sky'. */
  static tile(key: string, highContrast: boolean, dark: boolean): TileColors {
    const k: string = llKey(key);
    const p: Pair = dark ? darkPair(k) : basePair(k);
    const c: TileColors = new TileColors();
    c.key = TilesTheme.isPaletteKey(key) ? key : k;
    c.bg1 = p.bg1;
    c.bg2 = p.bg2;
    c.angle = 135;
    c.gradient = new LLGradient(135, [[p.bg1, 0.0], [p.bg2, 1.0]]);
    c.bg = mix(p.bg1, p.bg2);
    c.on = p.on;
    c.onMuted = withAlpha(p.on, highContrast ? 0.92 : 0.74);
    c.soft = withAlpha(p.on, highContrast ? 0.2 : 0.12);
    c.pressed = withAlpha(p.on, 0.16);
    // High contrast keeps the LL look but adds a hairline in the on-color so tiles separate from the page.
    c.border = highContrast ? withAlpha(p.on, 0.35) : '#00000000';
    return c;
  }

  /** Convenience: colors for a tile under a profile. */
  static tileFor(key: string, profile: Profile, dark: boolean): TileColors {
    return TilesTheme.tile(key, profile.highContrast, dark);
  }

  /** App surfaces (Living Light). High contrast pushes muted text and lines darker. */
  static palette(dark: boolean, highContrast: boolean): ThemePalette {
    const p: ThemePalette = new ThemePalette();
    p.dark = dark;
    p.bg = '#F3F1FA';
    p.surface = '#CCFFFFFF';
    p.surfaceAlt = '#121D2140';
    p.text = '#1D2140';
    p.textMuted = '#5B6283';
    p.border = '#1F1D2140';
    p.accent = '#4F5BD5';
    p.onAccent = '#FFFFFF';
    p.danger = '#C62B4A';
    p.onDanger = '#FFFFFF';
    p.success = '#1F7A4D';
    p.onSuccess = '#FFFFFF';
    p.scrim = '#401D2140';
    p.barBg = '#D6FFFFFF';
    p.shadow = '#7328326E';
    if (dark) {
      p.bg = '#14162A';
      p.bgGradient = new LLGradient(165, [['#1A1D38', 0.0], ['#14162A', 0.55], ['#1E1A30', 1.0]]);
      p.wallpaper = new LLGradient(165, [['#2A3170', 0.0], ['#4A2E5E', 0.6], ['#5E3A33', 1.0]]);
      p.surface = '#CC22264A';
      p.surfaceAlt = '#1AF3F5FF';
      p.surface2 = '#1AF3F5FF';
      p.text = '#F3F5FF';
      p.ink = '#F3F5FF';
      p.onInk = '#1D2140';
      p.textMuted = '#A9AFD3';
      p.muted = '#A9AFD3';
      p.border = '#29F3F5FF';
      p.line = '#29F3F5FF';
      p.accent = '#8E97FF';
      p.onAccent = '#14162A';
      p.danger = '#FF7A93';
      p.onDanger = '#2A0610';
      p.dangerSoft = '#29FF7A93';
      p.dangerInk = '#FFB3C1';
      p.success = '#5ED39A';
      p.ok = '#5ED39A';
      p.onSuccess = '#062A17';
      p.okSoft = '#295ED39A';
      p.okInk = '#A6EEC8';
      p.scrim = '#99000000';
      p.barBg = '#E01C1F3A';
      p.sheetBg = '#E01C1F3A';
      p.inputBg = '#14F3F5FF';
      p.toastBg = '#F3F5FF';
      p.toastFg = '#1D2140';
      p.statusInk = '#F3F5FF';
      p.shadow = '#80000000';
      p.skeleton = new LLGradient(100, [['#14FFFFFF', 0.35], ['#33FFFFFF', 0.5], ['#14FFFFFF', 0.65]]);
    }
    if (highContrast) {
      p.textMuted = dark ? '#D8DBF0' : '#2E3355';
      p.muted = p.textMuted;
      p.border = dark ? '#80F3F5FF' : '#661D2140';
      p.line = p.border;
      p.surface = dark ? '#F022264A' : '#F2FFFFFF';
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

  /** Corner radius for a tile size (Living Light: 26 vp for every size). */
  static radiusFor(size: string): number {
    return size === '2x2' ? TilesTheme.RADIUS_TILE_LG : TilesTheme.RADIUS_TILE;
  }
}
