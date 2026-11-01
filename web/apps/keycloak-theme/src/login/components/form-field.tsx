import { useState, type ComponentProps, type ReactNode } from "react"
import { kcSanitize } from "keycloakify/lib/kcSanitize"
import { Eye, EyeOff } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { cn } from "@workspace/ui/lib/utils"

import type { I18n } from "../i18n"

/** Keycloak's field error messages are HTML-escaped strings; sanitized like Keycloakify does. */
export function FieldError(props: { id: string; message: string }) {
  return (
    <p
      id={props.id}
      className="text-sm text-destructive"
      aria-live="polite"
      dangerouslySetInnerHTML={{ __html: kcSanitize(props.message) }}
    />
  )
}

export function Field(props: {
  htmlFor: string
  label: ReactNode
  required?: boolean
  /** Shown below the input; its id must be referenced by the input's aria-describedby. */
  error?: { id: string; message: string }
  className?: string
  children: ReactNode
}) {
  const { htmlFor, label, required, error, className, children } = props
  return (
    <div className={cn("grid gap-2", className)}>
      <Label htmlFor={htmlFor}>
        {label}
        {required && (
          <span aria-hidden="true" className="-ml-1 text-destructive">
            *
          </span>
        )}
      </Label>
      {children}
      {error && <FieldError id={error.id} message={error.message} />}
    </div>
  )
}

export function PasswordInput(
  props: Omit<ComponentProps<"input">, "type"> & { id: string; i18n: I18n }
) {
  const { i18n, className, ...inputProps } = props
  const [revealed, setRevealed] = useState(false)
  return (
    <div className="relative">
      <Input
        type={revealed ? "text" : "password"}
        className={cn("pr-9", className)}
        {...inputProps}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="absolute top-1/2 right-0.5 -translate-y-1/2 text-muted-foreground"
        aria-label={i18n.msgStr(revealed ? "hidePassword" : "showPassword")}
        aria-controls={inputProps.id}
        onClick={() => setRevealed((r) => !r)}
      >
        {revealed ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
      </Button>
    </div>
  )
}

/** The label of the username field depends on the realm's login settings. */
export function usernameLabel(
  realm: {
    loginWithEmailAllowed: boolean
    registrationEmailAsUsername: boolean
  },
  i18n: I18n
) {
  if (!realm.loginWithEmailAllowed) return i18n.msg("username")
  return realm.registrationEmailAsUsername
    ? i18n.msg("email")
    : i18n.msg("usernameOrEmail")
}
