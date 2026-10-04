// Recharts time-series wrapper (DESIGN_TOKENS §7): area | bar | line, stacked bars with 2 px surface gaps and
// 4 px rounded data-ends on the top segment only, bars ≤ 24 px, hairline grid, legend for ≥ 2 series,
// glass tooltip on every plot, reference lines (soft/hard caps), vertical version annotations.
import { useId, type ReactElement, type ReactNode } from 'react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { EmptyState } from '@/components/shell/EmptyState';
import { ChartLegend } from './ChartLegend';
import { ChartTooltip } from './ChartTooltip';
import { chartTheme, fmtAxisNum, fmtClockTick } from './theme';

export interface TimeseriesSeries {
  key: string;
  label: string;
  color: string;
  /** dashed line (forecast) */
  dashed?: boolean;
}

export interface AreaTimeseriesProps<T> {
  data: T[];
  xKey?: string;
  series: TimeseriesSeries[];
  kind?: 'area' | 'bar' | 'line';
  stacked?: boolean;
  height?: number;
  yFormat?: (v: number) => string;
  xFormat?: (v: string | number) => string;
  referenceLines?: { y: number; label?: string; color?: string; dashed?: boolean }[];
  annotations?: { x: string | number; label: string }[];
  legend?: boolean;
  /** tooltip title formatter (defaults to xFormat) */
  tooltipLabel?: (v: string | number) => ReactNode;
  /** show a total row in the tooltip (stacked bars) */
  tooltipTotal?: boolean;
  yDomain?: [number | 'auto' | 'dataMin' | 'dataMax', number | 'auto' | 'dataMin' | 'dataMax'];
  className?: string;
  animate?: boolean;
  emptyText?: string;
}

interface SegProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  fill?: string;
  payload?: Record<string, unknown>;
}

function makeSegment(seriesKeys: string[], idx: number, stacked: boolean) {
  return function Segment(p: SegProps) {
    const { x = 0, y = 0, width = 0, height = 0, fill, payload } = p;
    if (!(height > 0) || !(width > 0)) return <g />;
    const above = stacked ? seriesKeys.slice(idx + 1) : [];
    const isTop = !stacked || above.every((k) => !(Number(payload?.[k]) > 0));
    const gap = stacked && height > 3 ? 1 : 0;
    const yy = y + gap;
    const hh = Math.max(1, height - gap * 2);
    const r = isTop ? Math.min(4, width / 2, hh) : 0;
    if (r <= 0) return <rect x={x} y={yy} width={width} height={hh} fill={fill} />;
    const d = `M${x},${yy + hh}V${yy + r}Q${x},${yy} ${x + r},${yy}H${x + width - r}Q${x + width},${yy} ${x + width},${yy + r}V${yy + hh}Z`;
    return <path d={d} fill={fill} />;
  };
}

function AnnotationLabel({ viewBox, value, row }: { viewBox?: { x?: number; y?: number }; value: string; row: number }) {
  const x = viewBox?.x ?? 0;
  const y = (viewBox?.y ?? 0) - 4 + row * 12;
  return (
    <g>
      <circle cx={x} cy={y + 4} r={3} fill={chartTheme.annotation} />
      <text x={x - 6} y={y + 7} textAnchor="end" fill="#B5A8FF" fontSize={10} fontFamily="var(--font-mono)">
        {value}
      </text>
    </g>
  );
}

function RefLabel({ viewBox, value, color }: { viewBox?: { x?: number; y?: number; width?: number }; value: string; color: string }) {
  const x = (viewBox?.x ?? 0) + 4;
  const y = (viewBox?.y ?? 0) - 5;
  return (
    <text x={x} y={y} fill={color} fontSize={10.5} fontWeight={500}>
      {value}
    </text>
  );
}

export function AreaTimeseries<T>({
  data,
  xKey = 'ts',
  series,
  kind = 'area',
  stacked = false,
  height = 240,
  yFormat = fmtAxisNum,
  xFormat = fmtClockTick,
  referenceLines = [],
  annotations = [],
  legend,
  tooltipLabel,
  tooltipTotal,
  yDomain,
  className,
  animate = true,
  emptyText = 'No data in this window yet',
}: AreaTimeseriesProps<T>) {
  const gid = useId().replace(/:/g, '');
  const showLegend = legend ?? series.length > 1;
  if (!data || data.length === 0) {
    return (
      <div className={className}>
        <div style={{ height }} className="grid place-items-center">
          <EmptyState icon="ChartNoAxesColumn" title={emptyText} />
        </div>
      </div>
    );
  }
  const keys = series.map((s) => s.key);
  const anim = { isAnimationActive: animate, animationDuration: chartTheme.animationMs, animationEasing: 'ease-out' as const };
  const common = (
    <>
      <CartesianGrid stroke={chartTheme.grid} vertical={false} />
      <XAxis
        dataKey={xKey}
        tick={chartTheme.tick}
        tickFormatter={xFormat}
        axisLine={{ stroke: chartTheme.axis }}
        tickLine={false}
        minTickGap={28}
        tickMargin={6}
      />
      <YAxis tick={chartTheme.tick} tickFormatter={yFormat} axisLine={false} tickLine={false} width={44} domain={yDomain} allowDecimals />
      <Tooltip
        cursor={kind === 'bar' ? { fill: 'rgba(255,255,255,0.03)' } : { stroke: chartTheme.crosshair, strokeWidth: 1 }}
        content={<ChartTooltip labelFormat={tooltipLabel ?? xFormat} valueFormat={yFormat === fmtAxisNum ? undefined : yFormat} total={tooltipTotal ?? (stacked && kind === 'bar')} />}
        isAnimationActive={false}
        wrapperStyle={{ outline: 'none', zIndex: 20 }}
      />
      {referenceLines.map((r) => (
        <ReferenceLine
          key={`y-${r.y}-${r.label ?? ''}`}
          y={r.y}
          stroke={r.color ?? chartTheme.hardCap}
          strokeDasharray={r.dashed ? '4 4' : undefined}
          strokeOpacity={0.9}
          ifOverflow="extendDomain"
          label={r.label ? <RefLabel value={r.label} color={r.color ?? chartTheme.hardCap} /> : undefined}
        />
      ))}
      {annotations.map((a, i) => (
        <ReferenceLine key={`x-${a.x}-${a.label}`} x={a.x} stroke={chartTheme.annotationLine} label={<AnnotationLabel value={a.label} row={i % 2} />} />
      ))}
    </>
  );
  const margin = { top: annotations.length ? 22 : 10, right: 10, bottom: 0, left: 0 };

  let chart: ReactNode;
  if (kind === 'bar') {
    chart = (
      <BarChart data={data as object[]} margin={margin} barCategoryGap="22%">
        {common}
        {series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} stackId={stacked ? 'a' : undefined} maxBarSize={24} shape={makeSegment(keys, i, stacked)} {...anim} />
        ))}
      </BarChart>
    );
  } else if (kind === 'line') {
    chart = (
      <LineChart data={data as object[]} margin={margin}>
        {common}
        {series.map((s) => (
          <Line
            key={s.key}
            dataKey={s.key}
            name={s.label}
            stroke={s.dashed ? chartTheme.forecast : s.color}
            strokeWidth={2}
            strokeDasharray={s.dashed ? '4 4' : undefined}
            dot={false}
            activeDot={{ r: 4, stroke: chartTheme.surface, strokeWidth: 2 }}
            type="monotone"
            connectNulls={false}
            {...anim}
          />
        ))}
      </LineChart>
    );
  } else {
    chart = (
      <AreaChart data={data as object[]} margin={margin}>
        <defs>
          {series.map((s) => (
            <linearGradient key={s.key} id={`ag${gid}${s.key.replace(/[^a-z0-9]/gi, '')}`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity={0.18} />
              <stop offset="100%" stopColor={s.color} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        {common}
        {series.map((s) => (
          <Area
            key={s.key}
            dataKey={s.key}
            name={s.label}
            stroke={s.dashed ? chartTheme.forecast : s.color}
            strokeDasharray={s.dashed ? '4 4' : undefined}
            fill={s.dashed ? 'transparent' : `url(#ag${gid}${s.key.replace(/[^a-z0-9]/gi, '')})`}
            strokeWidth={2}
            stackId={stacked ? 'a' : undefined}
            type="monotone"
            dot={false}
            activeDot={{ r: 4, stroke: chartTheme.surface, strokeWidth: 2 }}
            connectNulls={false}
            {...anim}
          />
        ))}
      </AreaChart>
    );
  }

  return (
    <div className={className}>
      {showLegend ? <ChartLegend className="mb-2.5" items={series.map((s) => ({ label: s.label, color: s.dashed ? chartTheme.forecast : s.color, kind: kind === 'bar' ? 'swatch' : s.dashed ? 'dash' : 'line' }))} /> : null}
      <div className="aegis-chart" style={{ height, minWidth: 0 }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 480, height }}>
          {chart as ReactElement}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
