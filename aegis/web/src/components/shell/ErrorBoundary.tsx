// Per-route error boundary: one broken sibling page never takes down the shell.
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { TriangleAlert } from '@/components/icons';

interface Props {
  children: ReactNode;
  fallback?: ReactNode | ((error: Error, reset: () => void) => ReactNode);
  /** label for the console + fallback (e.g. the page file) */
  label?: string;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`[aegis] render error${this.props.label ? ` in ${this.props.label}` : ''}`, error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const { fallback } = this.props;
    if (typeof fallback === 'function') return fallback(error, this.reset);
    if (fallback !== undefined) return fallback;
    return (
      <div className="rounded-lg border border-block/30 bg-block/5 p-5">
        <div className="flex items-start gap-3">
          <div className="grid size-7 shrink-0 place-items-center rounded-md border border-block/30 bg-block/10 text-block">
            <TriangleAlert className="size-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-semibold">This panel crashed</div>
            <div className="mt-0.5 text-sm text-text-2">The rest of the dashboard keeps working. {this.props.label ? <span className="font-mono text-text-3">{this.props.label}</span> : null}</div>
            <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-surface-2 p-2 font-mono text-xs text-text-3">{error.message}</pre>
            <button type="button" onClick={this.reset} className="mt-3 h-7 rounded-md border border-border bg-surface-2 px-2.5 text-xs font-medium text-text-1 hover:bg-surface-3">
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }
}
