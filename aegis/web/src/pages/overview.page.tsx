// Command Center — management overview (docs/plan/15 §2.7). Rows: A KPI tiles · B live ticker ·
// C decisions chart + live stream · D spend burn / team spend / posture · E insights.
// Widgets live in components/shell/overview/*. Owner: dashboard-shell (B16).
import { motion } from 'framer-motion';
import { Bot, Printer, UserCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { MockBadge, PageHeader } from '@/components/shell';
import { Segmented } from '@/components/shell/Segmented';
import { DecisionsChartCard } from '@/components/shell/overview/DecisionsChartCard';
import { DataProtectedCard, DestinationsCard, TopAgentsCard, TopControlsCard } from '@/components/shell/overview/InsightCards';
import { KpiRow } from '@/components/shell/overview/KpiRow';
import { LiveStreamCard } from '@/components/shell/overview/LiveStreamCard';
import { LiveTicker } from '@/components/shell/overview/LiveTicker';
import { PostureCard } from '@/components/shell/overview/PostureCard';
import { SpendBurnCard } from '@/components/shell/overview/SpendBurnCard';
import { TeamSpendCard } from '@/components/shell/overview/TeamSpendCard';
import { useOverviewData, useOverviewWindow, type OverviewWindow } from '@/components/shell/overview/useOverviewData';
import { fmtNum } from '@/lib/format';
import type { PageMeta } from '@/lib/page';
import { useMotionSafe } from '@/lib/motion';
import { cn } from '@/lib/utils';

export const meta: PageMeta = {
  path: '/',
  title: 'Command Center',
  icon: 'Gauge',
  section: 'Overview',
  order: 10,
  shortcut: 'g o',
  description: 'Live management overview — traffic, interventions, spend and posture',
};

function Chip({ to, tone, icon, children }: { to: string; tone: 'approval' | 'neutral'; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      className={cn(
        'inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-medium transition-colors',
        tone === 'approval' ? 'border-approval/30 bg-approval/[0.08] text-approval hover:bg-approval/[0.14]' : 'border-border bg-surface-1 text-text-2 hover:border-border-strong hover:text-text-1',
      )}
    >
      {icon}
      {children}
    </Link>
  );
}

function Row({ i, className, children }: { i: number; className?: string; children: React.ReactNode }) {
  const on = useMotionSafe();
  return (
    <motion.div
      initial={on ? { opacity: 0, y: 10 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.12 + i * 0.06, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

export default function OverviewPage() {
  const [win, setWin] = useOverviewWindow();
  const d = useOverviewData(win);
  const pending = d.approvals.total;
  const forMe = d.approvals.forMe;
  const agents = d.view?.kpis.active_agents ?? 0;
  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Command Center"
        icon="Gauge"
        badge={d.stats.isMock || d.budgets.isMock ? <MockBadge /> : null}
        subtitle="Acme Capital · every model, tool, MCP and egress call through one policy decision point"
        actions={
          <>
            {pending > 0 ? (
              <Chip to="/governance/approvals" tone="approval" icon={<UserCheck className="size-3.5" />}>
                <span className="tabular">{pending}</span> approval{pending > 1 ? 's' : ''} pending
                {forMe > 0 ? <span className="text-approval/70">· {forMe} awaiting you</span> : null}
              </Chip>
            ) : null}
            <Chip to="/governance/org" tone="neutral" icon={<Bot className="size-3.5 text-[#2DD4BF]" />}>
              <span className="tabular">{fmtNum(agents)}</span> active agents
            </Chip>
            <Segmented<OverviewWindow>
              ariaLabel="Time window"
              value={win}
              onChange={setWin}
              options={[
                { value: '1h', label: '1h' },
                { value: '24h', label: '24h' },
                { value: '7d', label: '7d' },
              ]}
            />
            <button
              type="button"
              onClick={() => window.print()}
              title="Export management report (print to PDF)"
              className="no-print grid size-7 place-items-center rounded-md border border-border bg-surface-1 text-text-3 hover:border-border-strong hover:text-text-1"
            >
              <Printer className="size-3.5" />
            </button>
          </>
        }
      />
      <KpiRow d={d} />
      <Row i={1}>
        <LiveTicker />
      </Row>
      <Row i={2} className="grid grid-cols-12 gap-3">
        <DecisionsChartCard d={d} className="col-span-8 max-[1180px]:col-span-12" />
        <LiveStreamCard className="col-span-4 max-[1180px]:col-span-12" />
      </Row>
      <Row i={3} className="grid grid-cols-12 gap-3">
        <SpendBurnCard d={d} className="col-span-5 max-[1360px]:col-span-12" />
        <TeamSpendCard d={d} className="col-span-4 max-[1360px]:col-span-7 max-[900px]:col-span-12" />
        <PostureCard d={d} className="col-span-3 max-[1360px]:col-span-5 max-[900px]:col-span-12" />
      </Row>
      <Row i={4} className="grid grid-cols-12 gap-3">
        <TopControlsCard d={d} className="col-span-3 max-[1360px]:col-span-6 max-[760px]:col-span-12" />
        <DataProtectedCard d={d} className="col-span-3 max-[1360px]:col-span-6 max-[760px]:col-span-12" />
        <DestinationsCard d={d} className="col-span-3 max-[1360px]:col-span-6 max-[760px]:col-span-12" />
        <TopAgentsCard d={d} className="col-span-3 max-[1360px]:col-span-6 max-[760px]:col-span-12" />
      </Row>
    </div>
  );
}
