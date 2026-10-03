export function JsonView({ value, collapsed = false }: { value: unknown; collapsed?: boolean | number }) {
  const text = JSON.stringify(value, null, 2) ?? 'undefined';
  if (collapsed === true) {
    return (
      <details className="rounded-md border border-border bg-surface-2 p-2">
        <summary className="cursor-pointer text-xs text-text-3">JSON</summary>
        <pre className="mt-2 overflow-auto font-mono text-xs text-text-2">{text}</pre>
      </details>
    );
  }
  return <pre className="overflow-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-xs text-text-2">{text}</pre>;
}
