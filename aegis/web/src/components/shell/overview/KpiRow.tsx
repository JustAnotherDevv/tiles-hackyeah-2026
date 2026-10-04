// Row A — 6 KPI tiles: requests · blocked · redacted · spend today vs budget · cost avoided · posture.
import { motion } from 'framer-motion';
import { Gauge } from '@/components/charts/Gauge';
import { ACTION_COLORS } from '@/lib/colors';
import { fmtNum, fmtPct, fmtUsd } from '@/lib/format';
import { useMotionSafe } from '@/lib/motion';
import { KpiTile } from '../KpiTile';
import { UsageBar } from '../UsageBar';
import { orgDayLimit, type OverviewData } from './useOverviewData';

function forecastAtMidnight(used: number): number {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const elapsed = (Date.now() - start.getTime()) / 86_400_000;
  return elapsed > 0.02 ? used / elapsed : used;
}

const tileAnim = (i: number, on: boolean) =>
  on ? { initial: { opacity: 0, y: 10 }, animate: { opacity: 1, y: 0 }, transition: { delay: i * 0.04, duration: 0.36, ease: [0.16, 1, 0.3, 1] as const } } : {};

export function KpiRow({ d }: { d: OverviewData }) {
  const motionOk = useMotionSafe();
  const v = d.view;
  const loading = !v;
  const ts = v?.timeseries ?? [];
  const totals = ts.map((b) => b.allow + b.log + b.redact + b.require_approval + b.block);
  const k = v?.kpis;
  const req = k?.requests ?? 0;
  const blockedPct = req > 0 ? ((k?.blocked ?? 0) / req) * 100 : 0;
  const lim = orgDayLimit(d.budgets.data);
  const spend = k ? Math.max(k.spend_today_usd, lim?.used ?? 0) : (lim?.used ?? 0);
  const limit = lim?.limit ?? 150;
  const pct = limit > 0 ? (spend / limit) * 100 : 0;
  const forecast = forecastAtMidnight(spend);
  const fpct = limit > 0 ? (forecast / limit) * 100 : 0;
  const spendTone = pct >= 100 ? 'bad' : pct >= 80 ? 'warn' : 'good';
  const rps = d.tick?.rps;

  const tiles = [
    <KpiTile
      key="req"
      label="Requests"
      icon="Activity"
      loading={loading}
      value={req}
      format={(n) => fmtNum(n, { compact: n >= 100_000 })}
      hint={rps !== undefined ? `${rps.toFixed(1)} rps now · window ${v?.window ?? ''}` : `through one decision point · ${v?.window ?? ''}`}
      sparkline={totals}
      sparkColor="#818CF8"
      href="/security/live"
    />,
    <KpiTile
      key="blk"
      label="Blocked"
      icon="Ban"
      tone="bad"
      loading={loading}
      value={k?.blocked ?? 0}
      hint={`${fmtPct(blockedPct, 1)} of traffic · injections, secrets, exfil`}
      sparkline={ts.map((b) => b.block)}
      sparkColor={ACTION_COLORS.block.chart}
      href="/security/live"
    />,
    <KpiTile
      key="red"
      label="Redacted"
      icon="EyeOff"
      tone="warn"
      loading={loading}
      value={k?.redacted ?? 0}
      hint={`${fmtNum(v?.entitiesTotal ?? 0, { compact: true })} values tokenized locally`}
      sparkline={ts.map((b) => b.redact)}
      sparkColor={ACTION_COLORS.redact.chart}
      href="/security/live"
    />,
    <KpiTile
      key="spend"
      label="Spend today vs budget"
      icon="Wallet"
      tone={spendTone}
      loading={loading && !lim}
      value={spend}
      format={(n) => fmtUsd(n, { dp: 2 })}
      suffix={`/ ${fmtUsd(limit, { dp: 0 })}`}
      hint={`forecast ${fmtUsd(forecast, { dp: 0 })} by midnight`}
      footer={
        <div className="mt-1.5">
          <UsageBar pct={pct} forecastPct={fpct} size="sm" />
        </div>
      }
      href="/governance/budgets"
    />,
    <KpiTile
      key="avoid"
      label="Cost avoided"
      icon="PiggyBank"
      tone="good"
      loading={loading}
      value={k?.cost_avoided_usd ?? 0}
      format={(n) => fmtUsd(n, { dp: 2 })}
      hint="blocks · downgrades · loop kills"
      footer={
        <div className="mt-1 flex items-center gap-2 text-[11px] text-text-3">
          <span className="rounded border border-allow/20 bg-allow/[0.06] px-1.5 py-px font-mono text-allow">{fmtNum(k?.local_compute_s ?? 0, { dp: 0 })}s</span>
          local compute instead of cloud
        </div>
      }
    />,
    <KpiTile
      key="posture"
      label="Posture score"
      icon="ShieldCheck"
      tone={d.posture.tone}
      value={
        <span className="flex items-center gap-3">
          <Gauge value={d.posture.score} max={100} label="Posture" size={46} stroke={5} tone={d.posture.tone} format={() => d.posture.grade} />
          <span className="flex flex-col leading-none">
            <span>{Math.round(d.posture.score)}</span>
            <span className="mt-1 text-[11px] font-medium tracking-normal text-text-3">grade {d.posture.grade}</span>
          </span>
        </span>
      }
      hint={d.posture.toReview > 0 ? `${d.posture.toReview} item${d.posture.toReview > 1 ? 's' : ''} to review` : 'all factors healthy'}
      href="/system/health"
    />,
  ];

  return (
    <div className="grid grid-cols-6 gap-3 max-[1500px]:grid-cols-3 max-[760px]:grid-cols-1">
      {tiles.map((t, i) => (
        <motion.div key={t.key} {...tileAnim(i, motionOk)} className="flex min-w-0 [&>*]:flex-1">
          {t}
        </motion.div>
      ))}
    </div>
  );
}
