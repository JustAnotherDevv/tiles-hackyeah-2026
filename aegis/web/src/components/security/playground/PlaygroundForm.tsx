// Playground input form: text, surface, destination (+ provider picks), model, identity, tool name/args, Send.
import { Play, Wand2 } from 'lucide-react';
import { useMemo } from 'react';
import type { Agent, Surface } from '@/api/types';
import { Kbd, Segmented } from '@/components/shell';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { MiniSelect } from '../live/FeedFilters';
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

export function PresetPicker({ activeId, onPick }: { activeId: string | null; onPick: (p: PlaygroundPreset) => void }) {
  const groups = useMemo(() => {
    const m = new Map<string, PlaygroundPreset[]>();
    for (const p of PRESETS) m.set(p.group, [...(m.get(p.group) ?? []), p]);
    return [...m.entries()];
  }, []);
  return (
    <div className="space-y-2.5">
      {groups.map(([g, items]) => (
        <div key={g}>
          <div className="mb-1 text-2xs uppercase tracking-[0.08em] text-text-4">{g}</div>
          <div className="flex flex-wrap gap-1.5">
            {items.map((p) => (
              <button
                key={p.id}
                type="button"
                title={p.hint}
                onClick={() => onPick(p)}
                className={cn(
                  'group inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs transition-all',
                  activeId === p.id ? 'border-accent-fg/50 bg-brand/15 text-text-1 shadow-raised' : 'border-border bg-surface-1 text-text-2 hover:-translate-y-px hover:border-border-strong hover:text-text-1',
                )}
              >
                <Wand2 className="size-3 text-text-4 group-hover:text-accent-fg" />
                {p.label}
              </button>
            ))}
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
  const set = (patch: Partial<PlaygroundFormState>) => onChange({ ...value, ...patch });
  const showTool = TOOL_SURFACES.has(value.surface);
  const args = parseToolArgs(value.toolArgs);
  const destClass = (DEST_CLASSES as readonly string[]).includes(value.destination) ? value.destination : value.destination === 'ollama' ? 'local' : 'remote';
  const canRun = !running && value.text.trim().length > 0 && !args.error;
  return (
    <div className="space-y-3">
      <div className="relative">
        <textarea
          value={value.text}
          onChange={(e) => set({ text: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && canRun) {
              e.preventDefault();
              onRun();
            }
          }}
          rows={6}
          spellCheck={false}
          placeholder="Type a prompt, a tool call or a model response… then press Run (⌘/Ctrl + Enter)"
          className="w-full resize-y rounded-lg border border-border bg-background px-3.5 py-3 font-mono text-[13px] leading-5 text-text-1 outline-none transition-colors placeholder:text-text-4 focus:border-accent-fg/50 focus:shadow-[0_0_0_3px_rgba(99,102,241,.15)]"
          aria-label="Playground input"
        />
        <span className="pointer-events-none absolute bottom-2.5 right-3 font-mono text-2xs text-text-4">{value.text.length} chars</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <MiniSelect label="Surface" value={value.surface} onChange={(s) => set({ surface: (s || 'prompt.user') as Surface })} options={PLAYGROUND_SURFACES.map((s) => ({ value: s, label: s }))} />
        <Segmented
          value={destClass as (typeof DEST_CLASSES)[number]}
          onChange={(d) => set({ destination: d })}
          ariaLabel="Destination"
          options={[
            { value: 'local', label: 'Local' },
            { value: 'remote', label: 'Remote' },
            { value: 'third_party', label: '3rd party' },
          ]}
        />
        <div className="flex items-center gap-1">
          {PROVIDERS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => set({ destination: value.destination === p ? destClass : p })}
              className={cn(
                'h-7 rounded-md border px-2 font-mono text-2xs transition-colors',
                value.destination === p ? 'border-accent-fg/50 bg-brand/15 text-text-1' : 'border-border text-text-3 hover:text-text-1',
              )}
            >
              {p}
            </button>
          ))}
        </div>
        <MiniSelect label="As" value={value.agentId} onChange={(agentId) => set({ agentId })} options={agents.map((a) => ({ value: a.id, label: a.id }))} />
        <label className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface-1 px-2.5 text-xs text-text-3">
          Model
          <input value={value.model} onChange={(e) => set({ model: e.target.value })} placeholder="default" className="w-[110px] bg-transparent font-mono text-text-1 outline-none placeholder:text-text-4" />
        </label>
      </div>
      {showTool ? (
        <div className="grid gap-2 sm:grid-cols-[200px_1fr]">
          <label className="flex flex-col gap-1 text-2xs uppercase tracking-[0.08em] text-text-3">
            Tool name
            <input
              value={value.toolName}
              onChange={(e) => set({ toolName: e.target.value })}
              placeholder="Bash · acme-db.query"
              className="h-8 rounded-md border border-border bg-background px-2.5 font-mono text-xs normal-case tracking-normal text-text-1 outline-none focus:border-accent-fg/50"
            />
          </label>
          <label className="flex flex-col gap-1 text-2xs uppercase tracking-[0.08em] text-text-3">
            <span>
              Tool args (JSON) {args.error ? <span className="normal-case tracking-normal text-block">· {args.error}</span> : null}
            </span>
            <textarea
              value={value.toolArgs}
              onChange={(e) => set({ toolArgs: e.target.value })}
              rows={3}
              spellCheck={false}
              placeholder='{"command": "ls"}'
              className={cn(
                'resize-y rounded-md border bg-background px-2.5 py-1.5 font-mono text-xs normal-case tracking-normal text-text-1 outline-none',
                args.error ? 'border-block/50' : 'border-border focus:border-accent-fg/50',
              )}
            />
          </label>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-text-2">
          <Switch checked={value.send} onCheckedChange={(send) => set({ send })} />
          Send to model <span className="text-text-4">(only when allowed)</span>
        </label>
        <Button className="ml-auto min-w-[120px]" onClick={onRun} disabled={!canRun}>
          <Play className={cn(running && 'animate-pulse')} />
          {running ? 'Running…' : 'Run'}
          <Kbd>⌘↵</Kbd>
        </Button>
      </div>
    </div>
  );
}
