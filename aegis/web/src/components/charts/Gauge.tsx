export function Gauge({ value, max, label, sublabel, tone = 'auto', size = 96, format = (n: number) => String(Math.round(n)) }: { value: number; max: number; label: string; sublabel?: string; tone?: 'auto' | 'good' | 'warn' | 'bad' | 'neutral'; size?: number; format?: (n: number) => string }) {
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const t = tone === 'auto' ? (ratio >= 0.8 ? 'good' : ratio >= 0.5 ? 'warn' : 'bad') : tone;
  const color = { good: '#34D399', warn: '#FBBF24', bad: '#FB7185', neutral: '#94A3B8' }[t];
  const r = 40;
  const c = 2 * Math.PI * r;
  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={r} fill="none" stroke="#191C21" strokeWidth="8" />
        <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round" strokeDasharray={`${c * ratio} ${c}`} transform="rotate(-90 50 50)" />
        <text x="50" y="55" textAnchor="middle" fontSize="20" fontWeight="600" fill="#ECEEF1">
          {format(value)}
        </text>
      </svg>
      <div className="text-xs font-medium">{label}</div>
      {sublabel ? <div className="text-2xs text-text-3">{sublabel}</div> : null}
    </div>
  );
}
