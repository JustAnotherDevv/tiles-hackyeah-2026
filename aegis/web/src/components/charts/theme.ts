// Chart chrome (DESIGN_TOKENS §2.5 / §7). Recharts props shared by all wrappers.
export const chartTheme = {
  grid: '#1A1E24',
  axis: '#2A2F37',
  label: '#808693',
  surface: '#111317',
  crosshair: '#4B5160',
  annotation: '#8AB0F5',
  annotationLine: 'rgba(138,176,245,.5)',
  forecast: '#7A808C',
  hardCap: '#C43350',
  tick: { fill: '#808693', fontSize: 10.5 },
  animationMs: 300,
} as const;

export function fmtClockTick(v: string | number): string {
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

export function fmtDayTick(v: string | number): string {
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleDateString('en-GB', { weekday: 'short', hour: '2-digit' });
}

/** Compact y-axis numbers: 1.2k, 3.4M. */
export function fmtAxisNum(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1).replace(/\.0$/, '')}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1).replace(/\.0$/, '')}k`;
  return String(Math.round(v * 100) / 100);
}
