import { TileAction, TileSpec } from '../model/Tile';
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
