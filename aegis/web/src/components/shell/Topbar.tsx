// Topbar: crumbs · ⌘K search · version pill (flashes on policy/feed change) · connection pill · kill switch
// (admin) · "View as" (Owner/Admin/Member quick picks + member dropdown). Sticky glass bar.
import { GitCommitHorizontal, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { eventHub, type SseStatus } from '@/api/sse';
import { useApi, useSseStatus, useVersions, useViewAs } from '@/api/hooks';
import type { AuditVerifyResult, Member } from '@/api/types';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ROLE_COLORS } from '@/lib/colors';
import { findPage } from '@/lib/registry';
import { cn } from '@/lib/utils';
import { mockAuditVerify } from '@/mocks/shell/posture';
import { VIEW_AS_QUICK } from '@/mocks/shell/org';
import { Avatar } from './IdentityChip';
import { Kbd } from './Kbd';
import { KillSwitchButton } from './KillSwitch';
import { LiveDot } from './LiveDot';
import { RoleBadge } from './RoleBadge';
import { Segmented } from './Segmented';
import { setShellState } from './shellStore';

export function VersionPill() {
  const { policyVersion, feedSerial, changedAt } = useVersions();
  const audit = useApi<AuditVerifyResult>('/api/audit/verify', { mock: mockAuditVerify, refreshMs: 60_000 });
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          key={changedAt}
          className={cn(
            'inline-flex h-[26px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-surface-1 px-2.5 font-mono text-[11.5px] text-text-2 transition-colors',
            changedAt > 0 && Date.now() - changedAt < 3000 && 'pill-flash',
          )}
        >
          <GitCommitHorizontal className="size-3.5 text-text-3" />
          policy v{policyVersion ?? '—'}
          <span className="text-text-4">·</span>
          feed #{feedSerial ?? '—'}
          <span className="text-text-4 max-[1400px]:hidden">·</span>
          <span className={cn('max-[1400px]:hidden', audit.data?.ok === false ? 'text-block' : 'text-allow')}>{audit.data?.ok === false ? 'chain ✗' : 'chain ✓'}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>Every decision is stamped with the active policy version + feed serial</TooltipContent>
    </Tooltip>
  );
}

const CONN: Record<SseStatus, { label: string; tone: 'good' | 'warn' | 'bad' | 'info'; paused?: boolean }> = {
  idle: { label: 'Idle', tone: 'warn', paused: true },
  connecting: { label: 'Connecting', tone: 'warn' },
  live: { label: 'Live', tone: 'good' },
  reconnecting: { label: 'Reconnecting', tone: 'warn' },
  offline: { label: 'Offline · retrying', tone: 'bad' },
  mock: { label: 'Demo data', tone: 'info' },
};

export function ConnectionPill() {
  const status = useSseStatus();
  const c = CONN[status];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={() => status === 'offline' && eventHub.retryNow()}
          className={cn(
            'inline-flex h-[26px] shrink-0 items-center gap-2 whitespace-nowrap rounded-full border px-2.5 text-[11.5px] font-medium',
            c.tone === 'good' && 'border-allow/25 bg-allow/[0.06] text-allow',
            c.tone === 'warn' && 'border-redact/25 bg-redact/[0.06] text-redact',
            c.tone === 'bad' && 'border-block/30 bg-block/[0.08] text-block',
            c.tone === 'info' && 'border-[var(--accent-border)] bg-[var(--accent-subtle)] text-accent-fg',
          )}
        >
          <LiveDot tone={c.tone} paused={c.paused} />
          {c.label}
        </button>
      </TooltipTrigger>
      <TooltipContent>
        {status === 'mock' ? 'Mocks forced (?mock=1): synthetic event stream' : status === 'offline' ? 'SSE /api/events unreachable — click to retry now' : 'Server-sent events from /api/events'}
      </TooltipContent>
    </Tooltip>
  );
}

function groupByRole(members: Member[]): [Member['role'], Member[]][] {
  const order: Member['role'][] = ['owner', 'admin', 'member'];
  return order.map((r) => [r, members.filter((m) => m.role === r && m.active)] as [Member['role'], Member[]]).filter(([, l]) => l.length > 0);
}

export function ViewAsSwitcher() {
  const { member, role, members, setViewAs } = useViewAs();
  const quick = VIEW_AS_QUICK.map((q) => ({ ...q, id: members.find((m) => m.id === q.id) ? q.id : (members.find((m) => m.role === q.role)?.id ?? q.id) }));
  return (
    <div className="flex shrink-0 items-center gap-2 whitespace-nowrap">
      <span className="text-[11.5px] text-text-3 max-[1280px]:hidden">View as</span>
      <Segmented
        ariaLabel="View as role"
        value={role}
        onChange={(r) => {
          const q = quick.find((x) => x.role === r);
          if (q) setViewAs(q.id);
        }}
        options={(['owner', 'admin', 'member'] as const).map((r) => ({ value: r, label: ROLE_COLORS[r].label }))}
      />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button type="button" className="flex items-center gap-2 rounded-md py-1 pl-1.5 pr-2 text-left hover:bg-surface-1" aria-label="Choose member to view as">
            <Avatar name={member?.name ?? '?'} size={26} />
            <span className="min-w-0 max-[1180px]:hidden">
              <span className="block max-w-[150px] truncate text-[12.5px] font-medium leading-[15px] text-text-1">{member?.name ?? 'Default viewer'}</span>
              <span className="block max-w-[150px] truncate text-[11px] leading-[13px] text-text-3">{member?.title ?? ROLE_COLORS[role].label}</span>
            </span>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          {groupByRole(members).map(([r, list], gi) => (
            <DropdownMenuGroup key={r}>
              {gi > 0 ? <DropdownMenuSeparator /> : null}
              <DropdownMenuLabel className="text-[10.5px] uppercase tracking-[0.08em] text-text-3">{ROLE_COLORS[r].label}s</DropdownMenuLabel>
              {list.map((m) => (
                <DropdownMenuItem key={m.id} onSelect={() => setViewAs(m.id)} className={cn('gap-2.5', m.id === member?.id && 'bg-surface-4')}>
                  <Avatar name={m.name} size={24} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12.5px] text-text-1">{m.name}</span>
                    <span className="block truncate text-[11px] text-text-3">
                      {m.title ?? ''} · {m.team_id}
                    </span>
                  </span>
                  <RoleBadge role={m.role} icon={false} />
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function Crumbs() {
  const { pathname } = useLocation();
  const page = findPage(pathname);
  return (
    <div className="flex min-w-0 shrink items-center gap-2 whitespace-nowrap text-[13px] text-text-3">
      <span className="max-[1280px]:hidden">Acme Capital</span>
      <span className="text-text-4 max-[1280px]:hidden">/</span>
      {page && page.meta.section !== 'Overview' ? (
        <>
          <span>{page.meta.section}</span>
          <span className="text-text-4">/</span>
        </>
      ) : null}
      <b className="truncate font-medium text-text-1">{page?.meta.title ?? 'Not found'}</b>
    </div>
  );
}

export function Topbar() {
  const [mac, setMac] = useState(true);
  useEffect(() => {
    setMac(/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent));
  }, []);
  return (
    <header className="no-print relative z-20 flex h-[var(--topbar-h)] shrink-0 items-center gap-3 border-b border-border-subtle bg-[rgba(7,8,10,0.86)] pl-6 pr-5 backdrop-blur-[10px] backdrop-saturate-[1.4]">
      <Crumbs />
      <div className="min-w-0 flex-1" />
      <button
        type="button"
        onClick={() => setShellState({ paletteOpen: true })}
        className="flex h-[30px] w-[260px] min-w-[150px] shrink items-center gap-2 rounded-md border border-border bg-surface-1 pl-2.5 pr-2 text-[12.5px] text-text-3 transition-colors hover:border-border-strong hover:bg-surface-2 hover:text-text-2 max-[1500px]:w-[200px]"
      >
        <Search className="size-3.5 shrink-0" />
        <span className="truncate">Search or jump to…</span>
        <Kbd className="ml-auto">{mac ? '⌘K' : 'Ctrl K'}</Kbd>
      </button>
      <VersionPill />
      <ConnectionPill />
      <KillSwitchButton />
      <div className="h-[18px] w-px shrink-0 bg-border" />
      <ViewAsSwitcher />
    </header>
  );
}

