// Collapsible, syntax-coloured JSON viewer with copy (YAML palette from DESIGN_TOKENS §2.5).
import { Check, ChevronRight, Copy } from '@/components/icons';
import { useState, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

const C = { key: '#B5A8FF', string: '#8FD1A8', number: '#E8B865', bool: '#F2849A', null: '#7A808C', punct: '#7A808C' };

function Node({ value, depth, maxOpen, name, last }: { value: unknown; depth: number; maxOpen: number; name?: string; last: boolean }) {
  const [open, setOpen] = useState(depth < maxOpen);
  const keyEl = name !== undefined ? (
    <>
      <span style={{ color: C.key }}>"{name}"</span>
      <span style={{ color: C.punct }}>: </span>
    </>
  ) : null;
  const comma = last ? null : <span style={{ color: C.punct }}>,</span>;
  if (value === null || typeof value !== 'object') {
    let el: ReactNode;
    if (value === null || value === undefined) el = <span style={{ color: C.null }}>null</span>;
    else if (typeof value === 'string') el = <span style={{ color: C.string }}>"{value}"</span>;
    else if (typeof value === 'number') el = <span style={{ color: C.number }}>{String(value)}</span>;
    else if (typeof value === 'boolean') el = <span style={{ color: C.bool }}>{String(value)}</span>;
    else el = <span>{String(value)}</span>;
    return (
      <div style={{ paddingLeft: depth ? 14 : 0 }} className="whitespace-pre-wrap break-all">
        {keyEl}
        {el}
        {comma}
      </div>
    );
  }
  const isArr = Array.isArray(value);
  const entries = isArr ? (value as unknown[]).map((v, i) => [String(i), v] as const) : Object.entries(value as Record<string, unknown>);
  const [o, c] = isArr ? ['[', ']'] : ['{', '}'];
  if (entries.length === 0) {
    return (
      <div style={{ paddingLeft: depth ? 14 : 0 }}>
        {keyEl}
        <span style={{ color: C.punct }}>{o + c}</span>
        {comma}
      </div>
    );
  }
  return (
    <div style={{ paddingLeft: depth ? 14 : 0 }}>
      <button type="button" onClick={() => setOpen((x) => !x)} className="-ml-3.5 inline-flex items-center text-left hover:text-text-1">
        <ChevronRight className={cn('size-3 text-text-4 transition-transform', open && 'rotate-90')} />
        {keyEl}
        <span style={{ color: C.punct }}>{o}</span>
        {!open ? (
          <span className="text-text-4">
            {' '}
            {entries.length} {isArr ? 'items' : 'keys'} {c}
            {comma}
          </span>
        ) : null}
      </button>
      {open ? (
        <>
          {entries.map(([k, v], i) => (
            <Node key={k} name={isArr ? undefined : k} value={v} depth={depth + 1} maxOpen={maxOpen} last={i === entries.length - 1} />
          ))}
          <div>
            <span style={{ color: C.punct }}>{c}</span>
            {comma}
          </div>
        </>
      ) : null}
    </div>
  );
}

export function JsonView({ value, collapsed = false, className, maxHeight = 420 }: { value: unknown; collapsed?: boolean | number; className?: string; maxHeight?: number }) {
  const [copied, setCopied] = useState(false);
  const maxOpen = collapsed === true ? 0 : collapsed === false ? 99 : collapsed;
  const copy = () => {
    try {
      void navigator.clipboard.writeText(JSON.stringify(value, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <div className={cn('group relative rounded-md border border-border bg-[#0A0B0E] font-mono text-[11.5px] leading-[18px] text-text-2', className)}>
      <button
        type="button"
        onClick={copy}
        className="absolute right-2 top-2 z-10 grid size-6 place-items-center rounded-md border border-border bg-surface-2 text-text-3 opacity-0 transition-opacity hover:text-text-1 group-hover:opacity-100"
        aria-label="Copy JSON"
      >
        {copied ? <Check className="size-3 text-allow" /> : <Copy className="size-3" />}
      </button>
      <div className="overflow-auto p-3 pl-5" style={{ maxHeight }}>
        <Node value={value} depth={0} maxOpen={maxOpen} last />
      </div>
    </div>
  );
}
