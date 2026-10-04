// Row D (3) — explainable posture score: Gauge + factor checklist with points (tooltip per factor).
import { CircleCheck, CircleDashed, CircleAlert } from '@/components/icons';
import { Gauge } from '@/components/charts/Gauge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { Panel } from '../Panel';
import type { OverviewData } from './useOverviewData';

export function PostureCard({ d, className }: { d: OverviewData; className?: string }) {
  const p = d.posture;
  return (
    <Panel className={className} title="Security posture" description="Computed from live controls, coverage, feed, audit & health" isMock={d.postureMock}>
      <div className="flex items-center gap-4 pb-2 pt-1">
        <Gauge value={p.score} max={100} label="Posture score" sublabel={`grade ${p.grade}`} size={84} tone={p.tone} />
        <div className="text-[12px] leading-[17px] text-text-3">
          {p.toReview > 0 ? (
            <>
              <span className="font-medium text-text-1">{p.toReview}</span> factor{p.toReview > 1 ? 's' : ''} below max — hover or tap a row for the rule.
            </>
          ) : (
            'Every factor at full points.'
          )}
        </div>
      </div>
      <div className="flex flex-col">
        {p.factors.map((f) => {
          const Icon = !f.known ? CircleDashed : f.ok ? CircleCheck : CircleAlert;
          return (
            <Tooltip key={f.key}>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-2 border-t border-border-subtle py-[6px] text-[12px]">
                  <Icon className={cn('size-3.5 shrink-0', !f.known ? 'text-text-4' : f.ok ? 'text-allow' : 'text-redact')} />
                  <span className="truncate text-text-2">{f.label}</span>
                  <span className="ml-auto shrink-0 tabular text-text-1">
                    {Math.round(f.points * 10) / 10}
                    <span className="text-text-4">/{f.max}</span>
                  </span>
                </div>
              </TooltipTrigger>
              <TooltipContent side="left">{f.detail}</TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </Panel>
  );
}
