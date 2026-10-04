// Pinging live dot (the only looping animation besides the ticker). Styles in styles/effects.css.
export function LiveDot({ tone = 'good', paused = false, className }: { tone?: 'good' | 'bad' | 'warn' | 'info'; paused?: boolean; className?: string }) {
  return <span className={`live-dot ${className ?? ''}`} data-tone={tone === 'good' ? undefined : tone} data-paused={paused ? 'true' : undefined} aria-hidden />;
}
