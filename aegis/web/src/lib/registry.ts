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

function load(): { entries: PageEntry[]; complete: boolean } {
  const seen = new Set<string>();
  const out: PageEntry[] = [];
  let complete = true;
  for (const [file, mod] of Object.entries(modules)) {
    // Reading `meta`/`default` can throw a TDZ ReferenceError while a page module is still
    // evaluating (registry -> page -> @/components/shell -> AppShell -> registry cycle, seen after
    // Vite HMR edits). Skip that module for now and retry on the next access instead of crashing.
    let meta: PageMeta | undefined;
    let Component: unknown;
    try {
      meta = mod.meta;
      Component = mod.default;
    } catch {
      complete = false;
      continue;
    }
    const okDefault = typeof Component === 'function' || (typeof Component === 'object' && Component !== null);
    if (!okDefault || !meta?.path || !meta.title) {
      console.warn(`[aegis] page ${file} skipped: needs default component + meta {path, title}`);
      continue;
    }
    if (seen.has(meta.path)) {
      console.warn(`[aegis] page ${file} skipped: duplicate path ${meta.path}`);
      continue;
    }
    seen.add(meta.path);
    const section: NavSection = SECTION_ORDER.includes(meta.section) ? meta.section : 'System';
    if (section !== meta.section) console.warn(`[aegis] page ${file}: unknown section "${meta.section}", using System`);
    out.push({
      file,
      Component: Component as ComponentType,
      meta: { order: 100, minRole: 'member', nav: true, badge: null, ...meta, section },
    });
  }
  out.sort(
    (a, b) =>
      SECTION_ORDER.indexOf(a.meta.section) - SECTION_ORDER.indexOf(b.meta.section) ||
      a.meta.order - b.meta.order ||
      a.meta.title.localeCompare(b.meta.title),
  );
  return { entries: out, complete };
}

let cache: PageEntry[] | null = null;

/**
 * Discovered pages, computed lazily on first use (never at module-evaluation time) so that an
 * import cycle through a page module cannot throw "Cannot access 'meta' before initialization".
 */
export function getPages(): PageEntry[] {
  if (cache) return cache;
  const { entries, complete } = load();
  if (complete) cache = entries;
  return entries;
}

/** Back-compat array view (`pages.map`, `for…of`, `length`) that resolves lazily. */
export const pages: PageEntry[] = new Proxy([] as PageEntry[], {
  get: (_t, key) => {
    const list = getPages();
    const v = Reflect.get(list, key, list) as unknown;
    return typeof v === 'function' ? (v as (...a: unknown[]) => unknown).bind(list) : v;
  },
  has: (_t, key) => Reflect.has(getPages(), key),
  ownKeys: () => Reflect.ownKeys(getPages()),
  getOwnPropertyDescriptor: (_t, key) => {
    const d = Reflect.getOwnPropertyDescriptor(getPages(), key);
    if (d) d.configurable = true;
    return d;
  },
});
/** Alias used by the shell plan (docs/plan/15-dashboard-shell.md §4.2). */
export const PAGES = pages;

export function isLocked(meta: PageMeta, role: ViewRole): boolean {
  return VIEW_ROLE_RANK[role] < VIEW_ROLE_RANK[meta.minRole ?? 'member'];
}

/** Sidebar groups. Locked pages stay visible (shown with a lock) so `role` is informational. */
export function navSections(_role?: ViewRole): { section: NavSection; pages: PageEntry[] }[] {
  return SECTION_ORDER.map((section) => ({
    section,
    pages: getPages().filter((p) => p.meta.section === section && p.meta.nav),
  })).filter((s) => s.pages.length > 0);
}

/** Page whose meta.path matches a router pathname (params supported), for crumbs and titles. */
export function findPage(pathname: string): PageEntry | undefined {
  return getPages().find((p) => matchPath({ path: p.meta.path, end: true }, pathname));
}

/** Lowest role that unlocks the page (for "Requires admin" hints). */
export function requiredRole(meta: PageMeta): ViewRole {
  return meta.minRole ?? 'member';
}
