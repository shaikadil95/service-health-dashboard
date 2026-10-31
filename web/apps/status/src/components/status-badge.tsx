import {
  CircleCheck,
  CircleQuestionMark,
  CircleX,
  TriangleAlert,
} from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"
import { cn } from "@workspace/ui/lib/utils"

import type { Status } from "@/lib/api"

// Colour is never the only signal: every badge shows an icon and the status word.
const STYLE: Record<Status, { className: string; Icon: typeof CircleCheck }> = {
  UP: {
    className:
      "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-emerald-950",
    Icon: CircleCheck,
  },
  DEGRADED: {
    className: "bg-amber-400 text-amber-950 dark:bg-amber-400",
    Icon: TriangleAlert,
  },
  DOWN: {
    className: "bg-red-600 text-white dark:bg-red-500 dark:text-red-950",
    Icon: CircleX,
  },
  UNKNOWN: {
    className: "bg-muted text-muted-foreground",
    Icon: CircleQuestionMark,
  },
}

export function StatusBadge({
  status,
  className,
}: {
  status: Status
  className?: string
}) {
  const { className: style, Icon } = STYLE[status]
  return (
    <Badge className={cn(style, className)} data-status={status}>
      <Icon aria-hidden="true" data-icon="inline-start" />
      {status}
    </Badge>
  )
}
