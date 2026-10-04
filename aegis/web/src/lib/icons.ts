// Resolve a lucide icon by PascalCase name (PageMeta.icon); unknown names fall back to Circle.
// Owner: dashboard-shell (scaffold seed).
import { Circle, icons, type LucideIcon } from '@/components/icons';

export function resolveIcon(name: string | undefined): LucideIcon {
  if (!name) return Circle;
  return (icons as Record<string, LucideIcon>)[name] ?? Circle;
}
