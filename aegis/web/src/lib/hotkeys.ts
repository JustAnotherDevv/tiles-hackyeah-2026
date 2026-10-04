// Global keyboard navigation: ⌘K / Ctrl+K opens the palette, "g <key>" sequences jump to pages declared in
// meta.shortcut (e.g. "g o"). Ignored while typing in inputs/editors. Owner: dashboard-shell (B16).
import { useEffect, useRef } from 'react';

export interface HotkeyBindings {
  onPalette?: () => void;
  /** map "g o" -> handler */
  sequences?: Record<string, () => void>;
}

function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  const tag = t.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t.isContentEditable || Boolean(t.closest('.monaco-editor'));
}

export function useHotkeys(bindings: HotkeyBindings): void {
  const ref = useRef(bindings);
  ref.current = bindings;
  useEffect(() => {
    let prefix: string | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        ref.current.onPalette?.();
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e)) return;
      const key = e.key.toLowerCase();
      if (prefix) {
        const handler = ref.current.sequences?.[`${prefix} ${key}`];
        prefix = null;
        if (timer) clearTimeout(timer);
        if (handler) {
          e.preventDefault();
          handler();
        }
        return;
      }
      if (key === 'g') {
        prefix = 'g';
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => (prefix = null), 1200);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      if (timer) clearTimeout(timer);
    };
  }, []);
}
