// Dashboard page auto-discovery (CONTRACTS §2.2). Every web/src/pages/**/*.page.tsx must
// `export default` a component and `export const meta: PageMeta`. Invalid modules are skipped
// with a warning; duplicate paths: first wins. Owner: dashboard-shell (scaffold seed).
import type { ComponentType } from 'react';
import { VIEW_ROLE_RANK, type NavSection, type PageMeta, type ViewRole } from './page';

interface PageModule {
  default?: ComponentType;
  meta?: PageMeta;
}

export type ResolvedMeta = PageMeta & Required<Pick<PageMeta, 'order' | 'minRole' | 'nav'>>;

export interface PageEntry {
  file: string;
  meta: ResolvedMeta;
  Component: ComponentType;
}

export const SECTION_ORDER: NavSection[] = ['Overview', 'Security', 'Governance', 'System'];

const modules = import.meta.glob<PageModule>('../pages/**/*.page.tsx', { eager: true });

function load(): PageEntry[] {
  const seen = new Set<string>();
  const out: PageEntry[] = [];
  for (const [file, mod] of Object.entries(modules)) {
    if (typeof mod.default !== 'function' || !mod.meta?.path || !mod.meta.title) {
      console.warn(`[aegis] page ${file} skipped: needs default component + meta {path, title}`);
      continue;
    }
    if (seen.has(mod.meta.path)) {
      console.warn(`[aegis] page ${file} skipped: duplicate path ${mod.meta.path}`);
      continue;
    }
    seen.add(mod.meta.path);
    out.push({
      file,
      Component: mod.default,
      meta: { order: 100, minRole: 'member', nav: true, badge: null, ...mod.meta },
    });
  }
  return out.sort(
    (a, b) =>
      SECTION_ORDER.indexOf(a.meta.section) - SECTION_ORDER.indexOf(b.meta.section) ||
      a.meta.order - b.meta.order ||
      a.meta.title.localeCompare(b.meta.title),
  );
}

export const pages: PageEntry[] = load();
/** Alias used by the shell plan (docs/plan/15-dashboard-shell.md §4.2). */
export const PAGES = pages;

export function isLocked(meta: PageMeta, role: ViewRole): boolean {
  return VIEW_ROLE_RANK[role] < VIEW_ROLE_RANK[meta.minRole ?? 'member'];
}

/** Sidebar groups. Locked pages stay visible (shown with a lock) so `role` is informational. */
export function navSections(_role?: ViewRole): { section: NavSection; pages: PageEntry[] }[] {
  return SECTION_ORDER.map((section) => ({
    section,
    pages: pages.filter((p) => p.meta.section === section && p.meta.nav),
  })).filter((s) => s.pages.length > 0);
}
