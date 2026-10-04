import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

const badgeVariants = cva(
  "group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-4xl border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground [a]:hover:bg-primary/80",
        secondary:
          "bg-secondary text-secondary-foreground [a]:hover:bg-secondary/80",
        destructive:
          "bg-destructive/10 text-destructive focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:focus-visible:ring-destructive/40 [a]:hover:bg-destructive/20",
        outline:
          "border-border text-foreground [a]:hover:bg-muted [a]:hover:text-muted-foreground",
        ghost:
          "hover:bg-muted hover:text-muted-foreground dark:hover:bg-muted/50",
        link: "text-primary underline-offset-4 hover:underline",
      },
      tone: {
        none: "",
        allow: "border-allow/25 bg-allow/10 text-allow",
        log: "border-log/25 bg-log/10 text-log",
        redact: "border-redact/30 bg-redact/10 text-redact",
        require_approval: "border-approval/30 bg-approval/10 text-approval",
        block: "border-block/30 bg-block/10 text-block",
        owner: "border-role-owner/30 bg-role-owner/10 text-role-owner",
        admin: "border-role-admin/30 bg-role-admin/10 text-role-admin",
        member: "border-border-strong bg-surface-2 text-text-2",
        agent: "border-role-agent/25 bg-role-agent/10 text-role-agent",
        accent: "border-[var(--accent-border)] bg-[var(--accent-subtle)] text-accent-fg",
        neutral: "border-border bg-surface-2 text-text-2",
      },
    },
    defaultVariants: {
      variant: "default",
      tone: "none",
    },
  }
)

function Badge({
  className,
  variant = "default",
  tone = "none",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant: tone && tone !== "none" ? "outline" : variant, tone }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
