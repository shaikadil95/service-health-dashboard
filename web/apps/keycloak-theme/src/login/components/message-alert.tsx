import { kcSanitize } from "keycloakify/lib/kcSanitize"
import { CircleCheck, CircleX, Info, TriangleAlert } from "lucide-react"

import { Alert, AlertDescription } from "@workspace/ui/components/alert"
import { cn } from "@workspace/ui/lib/utils"

export type KcMessage = {
  type: "success" | "warning" | "error" | "info"
  summary: string
}

const ICONS = {
  success: CircleCheck,
  warning: TriangleAlert,
  error: CircleX,
  info: Info,
} as const

const ICON_COLORS = {
  success: "text-emerald-600 dark:text-emerald-400",
  warning: "text-amber-600 dark:text-amber-400",
  error: "",
  info: "text-muted-foreground",
} as const

/** Keycloak's global message (message.type / message.summary) as a shadcn Alert. */
export function MessageAlert(props: { message: KcMessage }) {
  const { type, summary } = props.message
  const Icon = ICONS[type]
  return (
    <Alert
      id="kc-message"
      variant={type === "error" ? "destructive" : "default"}
      role={type === "error" || type === "warning" ? "alert" : "status"}
      data-message-type={type}
    >
      <Icon aria-hidden="true" className={ICON_COLORS[type]} />
      <AlertDescription
        className={cn(type === "error" && "text-destructive")}
        dangerouslySetInnerHTML={{ __html: kcSanitize(summary) }}
      />
    </Alert>
  )
}
