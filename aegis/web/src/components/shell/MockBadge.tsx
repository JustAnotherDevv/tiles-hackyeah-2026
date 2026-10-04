import { FlaskConical } from '@/components/icons';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { isMockForced } from '@/lib/mockMode';

/** "demo data" pill: this panel shows mock data because the endpoint is missing (or mocks are forced). */
export function MockBadge({ label = 'demo data' }: { label?: string }) {
  const forced = isMockForced();
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex h-[18px] shrink-0 cursor-help items-center gap-1 rounded-full border border-dashed border-border-strong bg-surface-2 px-1.5 text-[10.5px] font-medium uppercase tracking-[0.06em] text-text-3">
          <FlaskConical className="size-2.5" />
          {label}
        </span>
      </TooltipTrigger>
      <TooltipContent>{forced ? 'Mocks forced (?mock=1) — synthetic data' : 'Endpoint not available yet — showing demo data'}</TooltipContent>
    </Tooltip>
  );
}
