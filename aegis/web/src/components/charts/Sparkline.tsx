// 28 px sparkline: 1.75 px line + 10 % area wash + end dot (prototype Ch.spark). Plain SVG (cheap to
// re-render on every live tick); draws in over 1.1 s on mount.
import { useId, useMemo } from 'react';

export interface SparklineProps {
  data: number[];
  color?: string;
  height?: number;
  area?: boolean;
  className?: string;
}

export function Sparkline({ data, color = '#7A808C', height = 28, area = true, className }: SparklineProps) {
  const id = useId().replace(/:/g, '');
  const W = 200;
  const H = height;
  const { line, fill, last } = useMemo(() => {
    const pts = data.filter((v) => Number.isFinite(v));
    if (pts.length < 2) return { line: '', fill: '', last: null as null | [number, number] };
    const min = Math.min(...pts);
    const max = Math.max(...pts);
    const span = max - min || 1;
    const xy = pts.map((v, i) => [(i / (pts.length - 1)) * W, H - 3 - ((v - min) / span) * (H - 6)] as [number, number]);
    const l = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('');
    return { line: l, fill: `${l}L${W},${H}L0,${H}Z`, last: xy[xy.length - 1] };
  }, [data, H]);
  if (!line) return <div style={{ height }} className={className} />;
  return (
    <div className={className} style={{ position: 'relative', height }}>
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height, overflow: 'visible', display: 'block' }} aria-hidden>
      <defs>
        <linearGradient id={`sg${id}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.22} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      {area ? <path d={fill} fill={`url(#sg${id})`} /> : null}
      <path d={line} fill="none" stroke={color} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
      {last ? (
        <span
          style={{ position: 'absolute', left: `calc(${(last[0] / W) * 100}% - 2.5px)`, top: last[1] - 2.5, width: 5, height: 5, borderRadius: 9, background: color, boxShadow: '0 0 0 2px #0E1013' }}
        />
      ) : null}
    </div>
  );
}
