// Shell-wide UI state fed by SSE (feed badge, kill switch, feed-rejected banner, palette). Module store read
// with useSyncExternalStore. Owner: dashboard-shell (B16).
import { useSyncExternalStore } from 'react';
import type { KillSwitch } from '@/api/types';

export interface ShellState {
  /** sidebar feed badge: "+N" for 10 s after feed.updated, "!" until a later feed.updated after feed.rejected */
  feedBadge: { kind: 'new'; count: number; until: number } | { kind: 'error' } | null;
  feedRejected: { reason: string; keptSerial: number | null; attempted: number | null; at: number } | null;
  kill: KillSwitch | null;
  killActor: string | null;
  paletteOpen: boolean;
  sidebarCollapsed: boolean;
}

let state: ShellState = {
  feedBadge: null,
  feedRejected: null,
  kill: null,
  killActor: null,
  paletteOpen: false,
  sidebarCollapsed: false,
};
const listeners = new Set<() => void>();

export function getShellState(): ShellState {
  return state;
}

export function setShellState(patch: Partial<ShellState> | ((s: ShellState) => Partial<ShellState>)): void {
  const p = typeof patch === 'function' ? patch(state) : patch;
  state = { ...state, ...p };
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

export function useShellState<T>(select: (s: ShellState) => T): T {
  return useSyncExternalStore(subscribe, () => select(state), () => select(state));
}

export function killActive(k: KillSwitch | null): boolean {
  return Boolean(k && (k.global || k.teams.length || k.members.length || k.agents.length || k.sessions.length));
}

export function killScopes(k: KillSwitch | null): string[] {
  if (!k) return [];
  return [
    ...(k.global ? ['global'] : []),
    ...k.teams.map((t) => `team:${t}`),
    ...k.members.map((m) => `member:${m}`),
    ...k.agents.map((a) => `agent:${a}`),
    ...k.sessions.map((s) => `session:${s}`),
  ];
}

/** Apply a `killswitch` SSE event to the KillSwitch shape. */
export function applyKillEvent(k: KillSwitch | null, scope: string, active: boolean): KillSwitch {
  const next: KillSwitch = k ? { ...k, teams: [...k.teams], members: [...k.members], agents: [...k.agents], sessions: [...k.sessions] } : { global: false, teams: [], members: [], agents: [], sessions: [] };
  if (scope === 'global') {
    next.global = active;
    return next;
  }
  const [kind, ...rest] = scope.split(':');
  const id = rest.join(':');
  const list = kind === 'team' ? next.teams : kind === 'member' ? next.members : kind === 'agent' ? next.agents : kind === 'session' ? next.sessions : null;
  if (!list) return next;
  const i = list.indexOf(id);
  if (active && i < 0) list.push(id);
  if (!active && i >= 0) list.splice(i, 1);
  return next;
}
