// Dashboard page plug-in contract. FROZEN: materialized verbatim from docs/CONTRACTS.md section 2.2.
// Every file matching web/src/pages/**/*.page.tsx must `export default` a React component
// and `export const meta: PageMeta`. The shell discovers them with import.meta.glob.

export type ViewRole = 'owner' | 'admin' | 'member';
export type NavSection = 'Overview' | 'Security' | 'Governance' | 'System';

export interface PageMeta {
  /** Route path under the /ui basename, e.g. "/security/live" or "/security/decisions/:id". */
  path: string;
  title: string;
  /** lucide-react icon name in PascalCase, e.g. "ShieldAlert". */
  icon: string;
  section: NavSection;
  /** Sort order inside the section (ascending). Default 100. */
  order?: number;
  /** Minimum view-as role to see the page. Default "member". */
  minRole?: ViewRole;
  /** Show in the sidebar. Default true; set false for detail routes with params. */
  nav?: boolean;
  /** Live counter badge shown next to the nav item. */
  badge?: 'approvals' | 'live' | 'feed' | null;
  /** One-line description for the command palette. */
  description?: string;
  /** Keyboard shortcut hint for the command palette, e.g. "g a". */
  shortcut?: string;
}

export const VIEW_ROLE_RANK: Record<ViewRole, number> = { member: 1, admin: 2, owner: 3 };
