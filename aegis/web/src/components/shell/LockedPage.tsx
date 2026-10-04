// Rendered instead of a page whose meta.minRole is above the current "view as" role. Locked pages stay in
// the sidebar (with a lock) so judges see the RBAC model; one click switches to an eligible member.
import { Lock } from '@/components/icons';
import { motion } from 'framer-motion';
import { useViewAs } from '@/api/hooks';
import { Button } from '@/components/ui/button';
import { ROLE_COLORS } from '@/lib/colors';
import { VIEW_ROLE_RANK, type PageMeta } from '@/lib/page';
import { Avatar } from './IdentityChip';
import { RoleBadge } from './RoleBadge';

export function LockedPage({ meta }: { meta: PageMeta }) {
  const { members, role, setViewAs } = useViewAs();
  const need = meta.minRole ?? 'member';
  const eligible = members.filter((m) => m.active && VIEW_ROLE_RANK[m.role] >= VIEW_ROLE_RANK[need]).sort((a, b) => VIEW_ROLE_RANK[a.role] - VIEW_ROLE_RANK[b.role]);
  const pick = eligible[0];
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mx-auto mt-16 flex max-w-md flex-col items-center gap-3 rounded-lg border border-border bg-card px-8 py-10 text-center max-md:px-5">
      <Lock className="size-6 text-text-3" />
      <div className="text-lg font-semibold tracking-tight">{meta.title} is locked</div>
      <div className="text-sm text-text-2">
        Requires <RoleBadge role={need} icon={false} /> — you are viewing as <RoleBadge role={role} icon={false} />.
      </div>
      <div className="text-xs text-text-3">Aegis enforces the same role model in the API: requests carry the viewer in <span className="font-mono">X-Aegis-View-As</span>.</div>
      {pick ? (
        <Button className="mt-2" onClick={() => setViewAs(pick.id)}>
          <Avatar name={pick.name} size={18} />
          View as {pick.name} · {ROLE_COLORS[pick.role].label}
        </Button>
      ) : null}
    </motion.div>
  );
}
