// Glass tooltip for Recharts: title + swatch rows + right-aligned tabular values (DESIGN_TOKENS §6 Tooltip).
import type { ReactNode } from 'react';

export interface ChartTooltipRow {
  label: string;
  color: string;
  value: ReactNode;
}

export function ChartTooltipBox({ title, rows, footer }: { title?: ReactNode; rows: ChartTooltipRow[]; footer?: ReactNode }) {
  return (
    <div className="pointer-events-none min-w-[150px] max-w-[320px] rounded-[10px] bg-surface-3/95 px-2.5 py-2 text-xs leading-[17px] text-text-1 shadow-pop backdrop-blur-sm">
      {title ? <div className="mb-1 font-semibold">{title}</div> : null}
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 text-text-2">
          <span className="size-2 shrink-0 rounded-[2px]" style={{ background: r.color }} />
          <span className="truncate">{r.label}</span>
          <b className="ml-auto pl-3 font-medium text-text-1 tabular">{r.value}</b>
        </div>
      ))}
      {footer ? <div className="mt-1 border-t border-border pt-1 text-text-3">{footer}</div> : null}
    </div>
  );
}

interface RechartsPayloadItem {
  dataKey?: string | number;
  name?: string | number;
  value?: number | string | (number | string)[];
  color?: string;
  fill?: string;
  stroke?: string;
}

/** Adapter usable as `<Tooltip content={<ChartTooltip … />} />`. */
export function ChartTooltip({
  active,
  payload,
  label,
  labelFormat,
  valueFormat,
  total,
}: {
  active?: boolean;
  payload?: RechartsPayloadItem[];
  label?: string | number;
  labelFormat?: (l: string | number) => ReactNode;
  valueFormat?: (v: number) => string;
  total?: boolean;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const rows = [...payload]
    .reverse()
    .filter((p) => p.value !== undefined && p.value !== null)
    .map((p) => {
      const v = Array.isArray(p.value) ? Number(p.value[1]) : Number(p.value);
      return { label: String(p.name ?? p.dataKey ?? ''), color: p.color ?? p.fill ?? p.stroke ?? '#7A808C', value: valueFormat ? valueFormat(v) : v.toLocaleString('en-US'), raw: v };
    });
  const sum = rows.reduce((a, r) => a + (Number.isFinite(r.raw) ? r.raw : 0), 0);
  return (
    <ChartTooltipBox
      title={label !== undefined ? (labelFormat ? labelFormat(label) : String(label)) : undefined}
      rows={rows}
      footer={total && rows.length > 1 ? <span className="flex justify-between"><span>Total</span><b className="font-medium text-text-1 tabular">{valueFormat ? valueFormat(sum) : sum.toLocaleString('en-US')}</b></span> : undefined}
    />
  );
}
