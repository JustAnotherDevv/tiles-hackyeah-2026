import { curves, promptAction } from '@kit.ArkUI';
import { TileAction, TileSpec } from '../model/Tile';
import { TilesTheme } from '../theme/TilesTheme';
import { TileActions } from '../platform/TileActions';
import { TileStore } from '../data/TileStore';
import { Speech } from '../platform/Speech';

/** AppStorage keys owned by the Tiles shell (Index.ets / HomeView / TileDetailView). */
export const K_DARK: string = 'tiles.dark'; // boolean: system dark mode
export const K_REDUCE_MOTION: string = 'tiles.reduceMotion'; // boolean: disable non-essential motion
/** Set to '<seed>#<ts>' (or 'open#<ts>') to open the Assistant sheet on Home. */
export const K_ASSISTANT_SEED: string = 'tiles.assistantSeed';

/** Routes the Navigation shell knows (pushPathByName names). */
export const SHELL_ROUTES: string[] = ['detail', 'onboarding', 'caregiver', 'guardian', 'settings', 'gallery'];

/** Accent palette key per profile (avatar, highlights). */
export function profileAccent(id: string): string {
  switch (id) {
    case 'senior':
      return 'coral';
    case 'kid':
      return 'sun';
    case 'lowvision':
      return 'grape';
    default:
      return 'sky';
  }
}

/**
 * Shell-side handling of a tile action. 'open' goes straight to the detail screen (recording the tap and reading
 * the tile aloud for read-aloud profiles); everything else goes to the platform dispatcher (TileActions).
 */
export function openTileDetail(nav: NavPathStack, t: TileSpec): void {
  TileStore.get().recordTap(t.id, false);
  if (TileStore.get().profile().readAloud && t.speakText.length > 0) {
    Speech.speak(t.speakText, t.id);
  }
  // Guardian tiles open the dedicated scam-shield screen.
  nav.pushPathByName(t.type === 'guardian' ? 'guardian' : 'detail', t.id, true);
}

export function platformAction(a: TileAction, t: TileSpec): void {
  TileActions.handle(a, t);
}

// ---------------------------------------------------------------------------------------------------------------
// Living Light shell motion + chrome (design direction C: ease cubic-bezier(.22,1,.36,1), dur 720 ms, sheetDur 560,
// pages/tiles enter from scale(.92) translateY(22), scrim rgba(29,33,64,.25), toast #1D2140 / #F3F5FF).
// ---------------------------------------------------------------------------------------------------------------

/** Scrim behind sheets / dialogs: rgba(29,33,64,.25) light, deeper in dark. Use as bindSheet `maskColor`. */
export const LL_SCRIM: string = '#401D2140';
export const LL_SCRIM_DARK: string = '#80000000';

export function llScrim(dark: boolean): string {
  return dark ? LL_SCRIM_DARK : LL_SCRIM;
}

/** True when page motion should collapse to a short fade (profile reduced motion or the explicit flag). */
export function llReducedMotion(): boolean {
  if (AppStorage.get<boolean>(K_REDUCE_MOTION) === true) {
    return true;
  }
  try {
    return TilesTheme.layoutFor(TileStore.get().profile()).reducedMotion;
  } catch (e) {
    return false;
  }
}

/**
 * Living Light toast: ink pill (#1D2140 / #F3F5FF; inverted in dark), soft shadow, no system blur.
 * Usage: llToast(this.getUIContext(), 'Saved');
 */
export function llToast(ui: UIContext, message: string, duration: number = 2200): void {
  const dark: boolean = AppStorage.get<boolean>(K_DARK) === true;
  const opts: promptAction.ShowToastOptions = {
    message: message,
    duration: duration,
    backgroundColor: dark ? '#F3F5FF' : '#1D2140',
    textColor: dark ? '#1D2140' : '#F3F5FF',
    backgroundBlurStyle: BlurStyle.NONE,
    shadow: { radius: 24, color: '#5928326E', offsetX: 0, offsetY: 12 },
    bottom: 120
  };
  try {
    ui.getPromptAction().showToast(opts);
  } catch (e) {
    // Toasts are best-effort.
  }
}

/**
 * Per-page Living Light transition state for a NavDestination. Usage in a routed view:
 *
 *   @State llMotion: LLPageMotion = new LLPageMotion();
 *   NavDestination() { ... }
 *     .opacity(this.llMotion.opacity)
 *     .scale({ x: this.llMotion.scale, y: this.llMotion.scale })
 *     .translate({ y: this.llMotion.ty })
 *     .customTransition((op: NavigationOperation, isEnter: boolean) =>
 *       this.llMotion.transitions(this.getUIContext(), op, isEnter))
 *
 * Enter (push / replace): fade + scale .92 -> 1 + translateY 22 -> 0 over 720 ms on cubic-bezier(.22,1,.36,1).
 * Exit (pop): fade + scale .96 + translateY 12 over 560 ms. The covered page settles back from scale .98.
 * Reduced motion: opacity only, 200 ms.
 */
@Observed
export class LLPageMotion {
  opacity: number = 1;
  scale: number = 1;
  ty: number = 0;

  transitions(ui: UIContext, op: NavigationOperation, isEnter: boolean): Array<NavDestinationTransition> | undefined {
    const reduced: boolean = llReducedMotion();
    const enterDur: number = reduced ? 200 : TilesTheme.LL_DUR;
    const exitDur: number = reduced ? 200 : TilesTheme.LL_SHEET_DUR;
    const curve: curves.ICurve = TilesTheme.ease();
    const list: Array<NavDestinationTransition> = [];
    if (isEnter && op !== NavigationOperation.POP) {
      // New page: start state now (outside any animation), then settle with the LL curve.
      this.opacity = 0;
      this.scale = reduced ? 1 : TilesTheme.LL_ENTER_SCALE;
      this.ty = reduced ? 0 : TilesTheme.LL_ENTER_TY;
      list.push({
        duration: enterDur,
        curve: Curve.EaseOut,
        event: () => {
          ui.animateTo({ duration: enterDur, curve: curve }, () => {
            this.opacity = 1;
            this.scale = 1;
            this.ty = 0;
          });
        },
        onTransitionEnd: () => {
          this.opacity = 1;
          this.scale = 1;
          this.ty = 0;
        }
      });
      return list;
    }
    if (isEnter && op === NavigationOperation.POP) {
      // Revealed page: settles back from a slight recess.
      this.scale = reduced ? 1 : 0.98;
      list.push({
        duration: exitDur,
        curve: Curve.EaseOut,
        event: () => {
          ui.animateTo({ duration: exitDur, curve: curve }, () => {
            this.opacity = 1;
            this.scale = 1;
            this.ty = 0;
          });
        }
      });
      return list;
    }
    if (op === NavigationOperation.POP || op === NavigationOperation.REPLACE) {
      // Leaving page: fade down and away.
      list.push({
        duration: exitDur,
        curve: Curve.EaseOut,
        event: () => {
          ui.animateTo({ duration: exitDur, curve: curve }, () => {
            this.opacity = 0;
            this.scale = reduced ? 1 : 0.96;
            this.ty = reduced ? 0 : 12;
          });
        }
      });
      return list;
    }
    // Covered by a pushed page: recess slightly, restore once hidden.
    list.push({
      duration: enterDur,
      curve: Curve.EaseOut,
      event: () => {
        ui.animateTo({ duration: enterDur, curve: curve }, () => {
          this.scale = reduced ? 1 : 0.98;
        });
      },
      onTransitionEnd: () => {
        this.opacity = 1;
        this.scale = 1;
        this.ty = 0;
      }
    });
    return list;
  }
}
