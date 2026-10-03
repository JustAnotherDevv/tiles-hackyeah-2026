// Permission-aware button: when `locked`, the button is disabled, shows a Lock icon and explains why
// in a tooltip (span-wrapped so the tooltip fires on a disabled button). Never hidden — the role
// switch must be visible in the demo. Owner: B18-dashboard-gov-approvals.
import { Lock } from 'lucide-react';
import type { ComponentProps, ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

export interface LockedActionProps extends ComponentProps<typeof Button> {
  locked: boolean;
  reason?: ReactNode;
  /** Tooltip even when unlocked (e.g. keyboard hint). */
  hint?: ReactNode;
  /** Replace the leading icon with a lock when locked (default true). */
  lockIcon?: boolean;
  wrapperClassName?: string;
}

export function LockedAction({ locked, reason, hint, lockIcon = true, wrapperClassName, children, className, disabled, ...rest }: LockedActionProps) {
  const button = (
    <Button
      {...rest}
      disabled={locked || disabled}
      aria-disabled={locked || disabled}
      data-locked={locked ? 'true' : undefined}
      className={cn(locked && 'cursor-not-allowed', className)}
    >
      {locked && lockIcon ? <Lock className="size-3.5" /> : null}
      {children}
    </Button>
  );
  const tip = locked ? reason : hint;
  if (!tip) return button;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={locked ? 0 : -1} className={cn('inline-flex', locked && 'cursor-not-allowed', wrapperClassName)}>
          {button}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-[300px] text-left leading-snug">
        {locked ? (
          <span className="flex items-start gap-1.5">
            <Lock className="mt-0.5 size-3 shrink-0" />
            <span>{reason}</span>
          </span>
        ) : (
          hint
        )}
      </TooltipContent>
    </Tooltip>
  );
}
