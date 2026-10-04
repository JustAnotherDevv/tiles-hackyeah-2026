// Playground input form: text, surface, destination (+ provider), model, identity, tool name/args, Send.
import { Play } from '@/components/icons';
import { useId, useMemo, type ReactNode } from 'react';
import type { Agent, Surface } from '@/api/types';
import { Kbd, Segmented } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import type { PlaygroundPreset } from '../types';
import { PRESETS, TOOL_SURFACES } from './presets';

export const PLAYGROUND_SURFACES: Surface[] = [
  'prompt.user',
  'model.request',
  'model.response',
  'tool.input',
  'tool.output',
  'mcp.call',
  'mcp.result',
  'mcp.list',
  'egress.request',
];

export interface PlaygroundFormState {
  text: string;
  surface: Surface;
  destination: string; // local | remote | third_party | mock | ollama | anthropic
  model: string;
  agentId: string; // '' = me (viewer)
  toolName: string;
  toolArgs: string; // JSON text
  send: boolean;
}

export const INITIAL_FORM: PlaygroundFormState = {
  text: '',
  surface: 'prompt.user',
  destination: 'remote',
  model: '',
  agentId: '',
  toolName: '',
  toolArgs: '',
  send: false,
};

export function formFromPreset(p: PlaygroundPreset): PlaygroundFormState {
  return {
    text: p.text(),
    surface: p.surface,
    destination: String(p.destination),
    model: '',
    agentId: p.agent_id ?? '',
    toolName: p.tool_name ?? '',
    toolArgs: p.tool_args ? JSON.stringify(p.tool_args(), null, 2) : '',
    send: false,
  };
}

export function parseToolArgs(s: string): { value: Record<string, unknown> | null; error: string | null } {
  if (!s.trim()) return { value: null, error: null };
  try {
    const v: unknown = JSON.parse(s);
    if (!v || typeof v !== 'object' || Array.isArray(v)) return { value: null, error: 'tool_args must be a JSON object' };
    return { value: v as Record<string, unknown>, error: null };
  } catch (e) {
    return { value: null, error: e instanceof Error ? e.message : 'invalid JSON' };
  }
}

const DEST_CLASSES = ['local', 'remote', 'third_party'] as const;
const PROVIDERS = ['mock', 'ollama', 'anthropic'];

const INPUT = 'h-9 w-full min-w-0 rounded-md border border-border bg-background px-2.5 text-xs text-text-1 outline-none transition-colors placeholder:text-text-4 hover:border-border-strong focus:border-accent-fg/60';

function Field({ label, htmlFor, hint, className, children }: { label: string; htmlFor?: string; hint?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1', className)}>
      <label htmlFor={htmlFor} className="text-2xs font-medium text-text-3">
        {label}
        {hint ? <span className="font-normal"> {hint}</span> : null}
      </label>
      {children}
    </div>
  );
}

function NativeSelect({ id, value, onChange, children }: { id: string; value: string; onChange: (v: string) => void; children: ReactNode }) {
  return (
    <div className="relative">
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={cn(INPUT, 'cursor-pointer appearance-none pr-7 font-mono')}>
        {children}
      </select>
      <svg aria-hidden viewBox="0 0 12 12" className="pointer-events-none absolute right-2.5 top-1/2 size-3 -translate-y-1/2 text-text-3">
        <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    </div>
  );
}

export function PresetPicker({ activeId, onPick }: { activeId: string | null; onPick: (p: PlaygroundPreset) => void }) {
  const groups = useMemo(() => {
    const m = new Map<string, PlaygroundPreset[]>();
    for (const p of PRESETS) m.set(p.group, [...(m.get(p.group) ?? []), p]);
    return [...m.entries()];
  }, []);
  return (
    <div className="space-y-3">
      {groups.map(([g, items]) => (
        <div key={g} className="grid gap-1.5 sm:grid-cols-[88px_minmax(0,1fr)] sm:items-start">
          <div className="text-2xs font-medium text-text-3 sm:pt-2">{g}</div>
          <div className="flex flex-wrap gap-1.5">
            {items.map((p) => {
              const on = activeId === p.id;
              return (
                <button
                  key={p.id}
                  type="button"
                  title={p.hint}
                  aria-pressed={on}
                  onClick={() => onPick(p)}
                  className={cn(
                    'inline-flex min-h-8 max-w-full items-center truncate rounded-md border px-2.5 text-left text-xs transition-colors',
                    on ? 'border-accent-fg/60 bg-surface-3 text-text-1' : 'border-border bg-surface-1 text-text-2 hover:border-border-strong hover:text-text-1',
                  )}
                >
                  <span className="truncate">{p.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function PlaygroundForm({
  value,
  onChange,
  onRun,
  running,
  agents,
}: {
  value: PlaygroundFormState;
  onChange: (v: PlaygroundFormState) => void;
  onRun: () => void;
  running: boolean;
  agents: Agent[];
}) {
  const uid = useId();
  const set = (patch: Partial<PlaygroundFormState>) => onChange({ ...value, ...patch });
  const showTool = TOOL_SURFACES.has(value.surface);
  const args = parseToolArgs(value.toolArgs);
  const isClass = (DEST_CLASSES as readonly string[]).includes(value.destination);
  const destClass = isClass ? value.destination : value.destination === 'ollama' ? 'local' : 'remote';
  const provider = PROVIDERS.includes(value.destination) ? value.destination : '';
  const canRun = !running && value.text.trim().length > 0 && !args.error;
  return (
    <div className="space-y-3">
      <div className="relative">
        <label htmlFor={`${uid}-text`} className="sr-only">
          Input text
        </label>
        <textarea
          id={`${uid}-text`}
          value={value.text}
          onChange={(e) => set({ text: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && canRun) {
              e.preventDefault();
              onRun();
            }
          }}
          rows={5}
          spellCheck={false}
          placeholder="Enter a prompt, model response or tool call"
          className="block min-h-32 w-full resize-y rounded-md border border-border bg-background px-3 pb-6 pt-2.5 font-mono text-[13px] leading-5 text-text-1 outline-none transition-colors placeholder:text-text-4 hover:border-border-strong focus:border-accent-fg/60"
        />
        <span className="pointer-events-none absolute bottom-2 right-3 font-mono text-2xs tabular-nums text-text-4">{value.text.length.toLocaleString()} chars</span>
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-2.5 sm:grid-cols-4 xl:grid-cols-2 2xl:grid-cols-4">
        <Field label="Destination" className="col-span-2">
          <Segmented
            value={destClass as (typeof DEST_CLASSES)[number]}
            onChange={(d) => set({ destination: d })}
            ariaLabel="Destination"
            size="lg"
            className="w-full [&>button]:flex-1 [&>button]:justify-center"
            options={[
              { value: 'local', label: 'Local' },
              { value: 'remote', label: 'Remote' },
              { value: 'third_party', label: 'Third party' },
            ]}
          />
        </Field>
        <Field label="Provider" htmlFor={`${uid}-prov`}>
          <NativeSelect id={`${uid}-prov`} value={provider} onChange={(p) => set({ destination: p || destClass })}>
            <option value="">auto</option>
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Surface" htmlFor={`${uid}-surf`}>
          <NativeSelect id={`${uid}-surf`} value={value.surface} onChange={(s) => set({ surface: (s || 'prompt.user') as Surface })}>
            {PLAYGROUND_SURFACES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Run as" htmlFor={`${uid}-as`} className="sm:col-span-2 xl:col-span-1 2xl:col-span-2">
          <NativeSelect id={`${uid}-as`} value={value.agentId} onChange={(agentId) => set({ agentId })}>
            <option value="">me (viewer)</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.id}
              </option>
            ))}
            {value.agentId && !agents.some((a) => a.id === value.agentId) ? <option value={value.agentId}>{value.agentId}</option> : null}
          </NativeSelect>
        </Field>
        <Field label="Model" htmlFor={`${uid}-model`} className="sm:col-span-2 xl:col-span-1 2xl:col-span-2">
          <input id={`${uid}-model`} value={value.model} onChange={(e) => set({ model: e.target.value })} placeholder="default" spellCheck={false} className={cn(INPUT, 'font-mono')} />
        </Field>
      </div>

      {showTool ? (
        <div className="grid gap-x-3 gap-y-2.5 sm:grid-cols-[minmax(0,200px)_minmax(0,1fr)]">
          <Field label="Tool name" htmlFor={`${uid}-tool`}>
            <input id={`${uid}-tool`} value={value.toolName} onChange={(e) => set({ toolName: e.target.value })} placeholder="Bash" spellCheck={false} className={cn(INPUT, 'font-mono')} />
          </Field>
          <Field label="Tool args" htmlFor={`${uid}-args`} hint={args.error ? <span className="text-block">· {args.error}</span> : '(JSON object)'}>
            <textarea
              id={`${uid}-args`}
              value={value.toolArgs}
              onChange={(e) => set({ toolArgs: e.target.value })}
              rows={3}
              spellCheck={false}
              placeholder='{"command": "ls"}'
              aria-invalid={Boolean(args.error)}
              className={cn(
                'w-full min-w-0 resize-y rounded-md border bg-background px-2.5 py-1.5 font-mono text-xs text-text-1 outline-none transition-colors placeholder:text-text-4',
                args.error ? 'border-block/60' : 'border-border hover:border-border-strong focus:border-accent-fg/60',
              )}
            />
          </Field>
        </div>
      ) : null}

      <div className="flex flex-col-reverse gap-3 border-t border-border-subtle pt-3 sm:flex-row sm:items-center">
        <label className="inline-flex min-h-9 cursor-pointer items-center gap-2 text-xs text-text-2">
          <Switch checked={value.send} onCheckedChange={(send) => set({ send })} />
          Send to model if allowed
        </label>
        <Button className="w-full sm:ml-auto sm:w-auto sm:min-w-[120px]" onClick={onRun} disabled={!canRun}>
          <Play />
          {running ? 'Running…' : 'Run'}
          <Kbd className="ml-1 hidden sm:inline-grid">⌘↵</Kbd>
        </Button>
      </div>
    </div>
  );
}
