// Small shared atoms for the Security pages (plan 16 §2.1 common/).
import { ArrowDownLeft, ArrowUpRight, Check, Copy, Lock } from '@/components/icons';
import { useState, type MouseEvent, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import type { DataClass, Direction, Severity, Surface } from '@/api/types';
import { cn } from '@/lib/utils';
import { fallbackControl } from '../lib/catalog';
import { dataClassOf } from '../lib/placeholders';
import { dataClassColor, KIND_COLORS, SEVERITY_TONE } from './colors';

export function SurfaceTag({ surface, direction, className }: { surface: Surface | string; direction?: Direction; className?: string }) {
  const Arrow = direction === 'in' ? ArrowDownLeft : ArrowUpRight;
  return (
    <span
      className={cn(
        'inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-xs border border-border bg-surface-2 px-1.5 font-mono text-2xs text-text-2',
        className,
      )}
      title={direction ? `${surface} (${direction === 'in' ? 'inbound' : 'outbound'})` : String(surface)}
    >
      {direction ? <Arrow className={cn('size-3', direction === 'in' ? 'text-sky-300' : 'text-text-3')} /> : null}
      {surface}
    </span>
  );
}

export function ControlChip({
  id,
  name,
  kind,
  owner,
  href,
  onClick,
  active,
  className,
}: {
  id: string;
  name?: string;
  kind?: string;
  owner?: string;
  href?: string;
  onClick?: () => void;
  active?: boolean;
  className?: string;
}) {
  const fb = fallbackControl(id);
  const k = kind ?? fb?.kind;
  const title = [name ?? fb?.name ?? id, k, owner ?? fb?.owner].filter(Boolean).join(' · ');
  const body = (
    <>
      <span className="size-1.5 rounded-full" style={{ background: k ? (KIND_COLORS[k] ?? '#64748B') : '#64748B' }} />
      {id}
    </>
  );
  const cls = cn(
    'inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-xs border px-1.5 font-mono text-2xs transition-colors',
    active ? 'border-accent-fg/50 bg-brand/15 text-text-1' : 'border-border bg-surface-2 text-text-2 hover:border-border-strong hover:text-text-1',
    className,
  );
  if (href)
    return (
      <Link to={href} className={cls} title={title} onClick={(e) => e.stopPropagation()}>
        {body}
      </Link>
    );
  if (onClick)
    return (
      <button type="button" className={cls} title={title} onClick={onClick}>
        {body}
      </button>
    );
  return (
    <span className={cls} title={title}>
      {body}
    </span>
  );
}

export function EntityChip({ entity, count, dataClass, className }: { entity: string; count?: number; dataClass?: DataClass | null; className?: string }) {
  const color = dataClassColor(dataClass ?? dataClassOf(entity));
  return (
    <span
      className={cn('inline-flex h-[18px] items-center gap-1 rounded-xs px-1.5 font-mono text-2xs', className)}
      style={{ color, background: `color-mix(in srgb, ${color} 12%, transparent)`, boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${color} 35%, transparent)` }}
    >
      {entity}
      {count && count > 1 ? <span className="opacity-70">×{count}</span> : null}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY_TONE[severity] ?? SEVERITY_TONE.info;
  return <span className={cn('inline-flex h-5 items-center rounded-xs border px-1.5 text-2xs font-medium', s.className)}>{s.label}</span>;
}

export function CopyButton({ value, label, className }: { value: string; label?: string; className?: string }) {
  const [done, setDone] = useState(false);
  const copy = (e: MouseEvent) => {
    e.stopPropagation();
    const ok = () => {
      setDone(true);
      setTimeout(() => setDone(false), 1200);
    };
    try {
      void navigator.clipboard
        .writeText(value)
        .then(ok)
        .catch(() => toast.error('Clipboard unavailable'));
    } catch {
      toast.error('Clipboard unavailable');
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      className={cn("relative inline-flex items-center gap-1 rounded-xs px-1 text-text-3 transition-colors after:absolute after:-inset-2 after:content-[''] hover:bg-surface-3 hover:text-text-1", className)}
      title={label ? `Copy ${label}` : 'Copy'}
      aria-label={label ? `Copy ${label}` : 'Copy'}
    >
      {done ? <Check className="size-3 text-allow" /> : <Copy className="size-3" />}
    </button>
  );
}

export function shortHash(h: string | null | undefined, chars = 4): string {
  if (!h) return '—';
  const s = h.replace(/^sha256:/, '');
  return s.length <= chars * 2 + 1 ? s : `${s.slice(0, chars)}…${s.slice(-chars)}`;
}

export function HashText({ hash, chars = 4, copy = true, className }: { hash: string | null | undefined; chars?: number; copy?: boolean; className?: string }) {
  if (!hash) return <span className="text-text-4">—</span>;
  return (
    <span className={cn('inline-flex items-center gap-0.5 font-mono text-xs text-text-2', className)} title={hash}>
      {shortHash(hash, chars)}
      {copy ? <CopyButton value={hash} label="hash" /> : null}
    </span>
  );
}

/** `wrap` lets long ids break instead of clipping (narrow screens). */
export function KeyValue({ items, className, wrap }: { items: [ReactNode, ReactNode][]; className?: string; wrap?: boolean }) {
  return (
    <dl className={cn('grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-1.5 text-xs', className)}>
      {items.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-text-3">{k}</dt>
          <dd className={cn('min-w-0 font-mono text-text-1', wrap ? '[overflow-wrap:anywhere]' : 'truncate')}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SectionLabel({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2.5 mt-5 flex items-center gap-2">
      <h4 className="text-2xs font-medium uppercase tracking-[0.08em] text-text-3">{children}</h4>
      {right ? <div className="ml-auto text-xs text-text-3">{right}</div> : null}
    </div>
  );
}

/** RoleGate fallback: a visibly locked control that explains how to unlock it in the demo. */
export function LockedAction({ label, min = 'admin', className, compact }: { label: string; min?: 'admin' | 'owner'; className?: string; compact?: boolean }) {
  return (
    <span
      className={cn(
        'inline-flex h-7 cursor-not-allowed items-center gap-1.5 rounded-md border border-dashed border-border-strong px-2.5 text-xs text-text-3',
        className,
      )}
      title={`${label} needs ${min} — switch “View as” in the top bar`}
      aria-disabled="true"
    >
      <Lock className="size-3" />
      {label}
      {compact ? null : <span className="text-text-4">· needs {min}</span>}
    </span>
  );
}
