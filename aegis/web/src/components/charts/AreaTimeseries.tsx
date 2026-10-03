import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

export interface AreaTimeseriesProps<T> {
  data: T[];
  xKey?: string;
  series: { key: string; label: string; color: string }[];
  kind?: 'area' | 'bar' | 'line';
  stacked?: boolean;
  height?: number;
  yFormat?: (v: number) => string;
  xFormat?: (v: string | number) => string;
  referenceLines?: { y: number; label?: string; color?: string; dashed?: boolean }[];
  annotations?: { x: string | number; label: string }[];
  legend?: boolean;
}

const TICK = { fill: '#7A808C', fontSize: 10.5 };

export function AreaTimeseries<T>({ data, xKey = 'ts', series, kind = 'area', stacked = false, height = 240, yFormat, xFormat, referenceLines = [], legend }: AreaTimeseriesProps<T>) {
  const Chart = kind === 'bar' ? BarChart : kind === 'line' ? LineChart : AreaChart;
  const common = (
    <>
      <CartesianGrid stroke="#1A1E24" vertical={false} />
      <XAxis dataKey={xKey} tick={TICK} tickFormatter={xFormat} axisLine={{ stroke: '#2A2F37' }} tickLine={false} />
      <YAxis tick={TICK} tickFormatter={yFormat} axisLine={false} tickLine={false} width={44} />
      <Tooltip contentStyle={{ background: '#191C21', border: '1px solid #2A2F37', borderRadius: 10, fontSize: 12 }} />
      {(legend ?? series.length > 1) ? <Legend wrapperStyle={{ fontSize: 11.5 }} /> : null}
      {referenceLines.map((r) => (
        <ReferenceLine key={`${r.y}-${r.label}`} y={r.y} stroke={r.color ?? '#C43350'} strokeDasharray={r.dashed ? '4 4' : undefined} label={r.label} />
      ))}
    </>
  );
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={data as object[]} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          {common}
          {series.map((s) =>
            kind === 'bar' ? (
              <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} stackId={stacked ? 'a' : undefined} maxBarSize={24} />
            ) : kind === 'line' ? (
              <Line key={s.key} dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} dot={false} type="monotone" />
            ) : (
              <Area key={s.key} dataKey={s.key} name={s.label} stroke={s.color} fill={s.color} fillOpacity={0.1} strokeWidth={2} stackId={stacked ? 'a' : undefined} type="monotone" />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}
