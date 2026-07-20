import { cn } from "@/lib/utils"
import type { RiskLevel } from "@/lib/api/types"

/*
 * Status = the design system's state treatment: a small dot + the word in the
 * semantic color. No tinted pill backgrounds (see DESIGN.md).
 */
export type StatusKind = "success" | "warning" | "info" | "danger" | "neutral"

const STATUS_COLORS: Record<StatusKind, string> = {
  success: "text-success",
  warning: "text-warning",
  info: "text-info",
  danger: "text-destructive",
  neutral: "text-tertiary",
}

export function Status({
  kind,
  children,
  className,
}: {
  kind: StatusKind
  children: React.ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 text-[13px] font-medium whitespace-nowrap",
        STATUS_COLORS[kind],
        className,
      )}
    >
      <span aria-hidden className="h-[7px] w-[7px] shrink-0 rounded-full bg-current" />
      {children}
    </span>
  )
}

/* Badge is for counts and quiet metadata — never money state. */
interface BadgeProps {
  children: React.ReactNode
  variant?: "default" | "success" | "warning" | "danger" | "info"
  className?: string
}

export function Badge({ children, variant = "default", className }: BadgeProps) {
  const variants: Record<string, string> = {
    default: "bg-muted text-muted-foreground",
    success: "bg-muted text-success",
    warning: "bg-muted text-warning",
    danger: "bg-muted text-destructive",
    info: "bg-muted text-info",
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold",
        variants[variant],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function RiskBadge({ level }: { level: RiskLevel }) {
  const map: Record<RiskLevel, { kind: StatusKind; label: string }> = {
    LOW: { kind: "success", label: "Low" },
    MEDIUM: { kind: "warning", label: "Medium" },
    HIGH: { kind: "danger", label: "High" },
  }
  const { kind, label } = map[level]
  return <Status kind={kind}>{label}</Status>
}
