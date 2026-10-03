// Dashboard page auto-discovery (CONTRACTS §2.2). Every web/src/pages/**/*.page.tsx must
// `export default` a component and `export const meta: PageMeta`. Invalid modules are skipped
// with a warning; duplicate paths: first wins. Owner: dashboard-shell (B16).
import type { ComponentType } from 'react';
import { matchPath } from 'react-router-dom';
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
    const okDefault = typeof mod.default === 'function' || (typeof mod.default === 'object' && mod.default !== null);
    if (!okDefault || !mod.meta?.path || !mod.meta.title) {
      console.warn(`[aegis] page ${file} skipped: needs default component + meta {path, title}`);
      continue;
    }
    if (seen.has(mod.meta.path)) {
      console.warn(`[aegis] page ${file} skipped: duplicate path ${mod.meta.path}`);
      continue;
    }
    seen.add(mod.meta.path);
    const section: NavSection = SECTION_ORDER.includes(mod.meta.section) ? mod.meta.section : 'System';
    if (section !== mod.meta.section) console.warn(`[aegis] page ${file}: unknown section "${mod.meta.section}", using System`);
    out.push({
      file,
      Component: mod.default as ComponentType,
      meta: { order: 100, minRole: 'member', nav: true, badge: null, ...mod.meta, section },
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

/** Page whose meta.path matches a router pathname (params supported), for crumbs and titles. */
export function findPage(pathname: string): PageEntry | undefined {
  return pages.find((p) => matchPath({ path: p.meta.path, end: true }, pathname));
}

/** Lowest role that unlocks the page (for "Requires admin" hints). */
export function requiredRole(meta: PageMeta): ViewRole {
  return meta.minRole ?? 'member';
}
