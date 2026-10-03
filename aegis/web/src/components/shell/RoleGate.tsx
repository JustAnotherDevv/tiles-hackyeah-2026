import type { ReactNode } from 'react';
import { useViewAs } from '@/api/hooks';
import { VIEW_ROLE_RANK, type ViewRole } from '@/lib/page';

export function RoleGate({ min, children, fallback = null }: { min: ViewRole; children: ReactNode; fallback?: ReactNode }) {
  const { role } = useViewAs();
  return <>{VIEW_ROLE_RANK[role] >= VIEW_ROLE_RANK[min] ? children : fallback}</>;
}
