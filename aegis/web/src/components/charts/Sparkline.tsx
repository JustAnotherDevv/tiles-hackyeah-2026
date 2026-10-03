import { Area, AreaChart, ResponsiveContainer } from 'recharts';

export function Sparkline({ data, color = '#818CF8', height = 28, area = true }: { data: number[]; color?: string; height?: number; area?: boolean }) {
  const points = data.map((v, i) => ({ i, v }));
  return (
    <div style={{ height }} className="mt-2">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.75} fill={color} fillOpacity={area ? 0.1 : 0} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
