// ⌘K command palette (UIS-15): Go to (registry pages, locked ones disabled), View as (all members),
// Actions (verify audit chain, toggle demo data, copy Claude Code env, open playground). `g <key>` page
// shortcuts from meta.shortcut are wired in AppShell via lib/hotkeys. Owner: dashboard-shell (B16).
import { ClipboardCopy, FlaskConical, Link2, Lock, ShieldCheck, ToggleLeft } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { api, isApiRequestError } from '@/api/client';
import { useViewAs } from '@/api/hooks';
import type { AuditVerifyResult } from '@/api/types';
import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator, CommandShortcut } from '@/components/ui/command';
import { ROLE_COLORS } from '@/lib/colors';
import { resolveIcon } from '@/lib/icons';
import { isMockForced, setMockForced } from '@/lib/mockMode';
import { getPages, isLocked } from '@/lib/registry';
import { mockAuditVerify } from '@/mocks/shell/posture';
import { Avatar } from './IdentityChip';
import { RoleBadge } from './RoleBadge';
import { setShellState, useShellState } from './shellStore';

const CLAUDE_ENV = 'export ANTHROPIC_BASE_URL=http://127.0.0.1:8787';

export async function verifyAuditChain(): Promise<void> {
  const id = toast.loading('Verifying audit hash chain…', { className: 'aegis-toast' });
  try {
    const r = await api.get<AuditVerifyResult>('/api/audit/verify', mockAuditVerify);
    const d = r.data;
    if (d.ok) toast.success(`Chain OK · ${d.records.toLocaleString('en-US')} records`, { id, className: 'aegis-toast', description: `head ${d.head_hash.slice(0, 12)}…${r.isMock ? ' · demo data' : ''}` });
    else toast.error(`Chain broken at seq ${d.broken_at_seq ?? '?'}`, { id, className: 'aegis-toast', description: d.message });
  } catch (e) {
    toast.error('Audit verification failed', { id, className: 'aegis-toast', description: isApiRequestError(e) ? e.message : 'Gateway unreachable' });
  }
}

export function toggleDemoData(): void {
  const on = !isMockForced();
  setMockForced(on);
  const url = new URL(window.location.href);
  url.searchParams.set('mock', on ? '1' : '0');
  window.location.assign(url.toString());
}

export function CommandPalette() {
  const open = useShellState((s) => s.paletteOpen);
  const setOpen = (o: boolean) => setShellState({ paletteOpen: o });
  const navigate = useNavigate();
  const { role, members, member, setViewAs } = useViewAs();
  const run = (fn: () => void) => {
    setOpen(false);
    fn();
  };
  const navPages = getPages().filter((p) => p.meta.nav);
  return (
    <CommandDialog open={open} onOpenChange={setOpen} title="Command palette" description="Jump to a page, switch viewer or run an action" className="sm:max-w-[620px]">
      <Command loop className="bg-popover">
        <CommandInput placeholder="Search pages, people, actions…" />
        <CommandList className="max-h-[420px]">
          <CommandEmpty>No results.</CommandEmpty>
          <CommandGroup heading="Go to">
            {navPages.map(({ meta }) => {
              const Icon = resolveIcon(meta.icon);
              const locked = isLocked(meta, role);
              return (
                <CommandItem
                  key={meta.path}
                  value={`${meta.title} ${meta.path}`}
                  keywords={[meta.section]}
                  disabled={locked}
                  onSelect={() => run(() => navigate(meta.path))}
                >
                  <Icon className="text-text-3" />
                  <span className="min-w-0 flex-1 truncate">
                    <span className="text-text-1">{meta.title}</span>
                    <span className="ml-2 text-[11.5px] text-text-3">{meta.description ?? meta.section}</span>
                  </span>
                  {locked ? (
                    <span className="flex items-center gap-1 text-[11px] text-text-4">
                      <Lock className="size-3" /> {ROLE_COLORS[meta.minRole].label.toLowerCase()}
                    </span>
                  ) : meta.shortcut ? (
                    <CommandShortcut>{meta.shortcut}</CommandShortcut>
                  ) : null}
                </CommandItem>
              );
            })}
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading="View as">
            {members
              .filter((m) => m.active)
              .map((m) => (
                <CommandItem key={m.id} value={`view as ${m.name} ${m.role} ${m.title ?? ''} ${m.id}`} onSelect={() => run(() => setViewAs(m.id))}>
                  <Avatar name={m.name} size={20} />
                  <span className="min-w-0 flex-1 truncate">
                    {m.name}
                    {m.id === member?.id ? <span className="ml-2 text-[11px] text-text-3">current</span> : null}
                  </span>
                  <RoleBadge role={m.role} icon={false} />
                </CommandItem>
              ))}
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading="Actions">
            <CommandItem value="verify audit chain hash" onSelect={() => run(() => void verifyAuditChain())}>
              <ShieldCheck className="text-allow" />
              Verify audit chain
            </CommandItem>
            <CommandItem value="toggle demo data mock" onSelect={() => run(toggleDemoData)}>
              <ToggleLeft className="text-text-3" />
              {isMockForced() ? 'Use live gateway data (disable demo data)' : 'Force demo data (?mock=1)'}
            </CommandItem>
            <CommandItem
              value="copy claude code env anthropic base url"
              onSelect={() =>
                run(() => {
                  void navigator.clipboard?.writeText(CLAUDE_ENV).then(
                    () => toast.success('Copied Claude Code env', { className: 'aegis-toast', description: CLAUDE_ENV }),
                    () => toast.info(CLAUDE_ENV, { className: 'aegis-toast' }),
                  );
                })
              }
            >
              <ClipboardCopy className="text-text-3" />
              Copy Claude Code env snippet
              <span className="ml-auto truncate font-mono text-[11px] text-text-4">ANTHROPIC_BASE_URL=…:8787</span>
            </CommandItem>
            <CommandItem value="open playground try" onSelect={() => run(() => navigate('/security/playground'))}>
              <FlaskConical className="text-text-3" />
              Open playground
            </CommandItem>
            <CommandItem
              value="copy link share page"
              onSelect={() =>
                run(() => {
                  void navigator.clipboard?.writeText(window.location.href);
                  toast.success('Link copied', { className: 'aegis-toast' });
                })
              }
            >
              <Link2 className="text-text-3" />
              Copy link to this page
            </CommandItem>
          </CommandGroup>
        </CommandList>
        <div className="flex items-center gap-3 border-t border-border-subtle px-3 py-2 text-[11px] text-text-4">
          <span>↑↓ navigate</span>
          <span>↵ select</span>
          <span>esc close</span>
          <span className="ml-auto">g + key jumps to a page</span>
        </div>
      </Command>
    </CommandDialog>
  );
}
