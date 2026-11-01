import type { PageProps } from "keycloakify/login/pages/PageProps"

import { Button } from "@workspace/ui/components/button"

import { Field, PasswordInput } from "../components/form-field"
import type { I18n } from "../i18n"
import type { KcContext } from "../KcContext"

export default function LoginUpdatePassword(
  props: PageProps<
    Extract<KcContext, { pageId: "login-update-password.ftl" }>,
    I18n
  >
) {
  const { kcContext, i18n, doUseDefaultCss, Template, classes } = props
  const { url, messagesPerField, isAppInitiatedAction } = kcContext
  const { msg, msgStr } = i18n

  const hasError = messagesPerField.existsError("password", "password-confirm")
  const fieldError = (name: "password" | "password-confirm") =>
    messagesPerField.existsError(name)
      ? { id: `input-error-${name}`, message: messagesPerField.get(name) }
      : undefined
  const passwordError = fieldError("password")
  const confirmError = fieldError("password-confirm")

  return (
    <Template
      kcContext={kcContext}
      i18n={i18n}
      doUseDefaultCss={doUseDefaultCss}
      classes={classes}
      displayMessage={!hasError}
      headerNode={msg("updatePasswordTitle")}
    >
      <form
        id="kc-passwd-update-form"
        className="grid gap-4"
        action={url.loginAction}
        method="post"
      >
        <Field
          htmlFor="password-new"
          label={msg("passwordNew")}
          error={passwordError}
        >
          <PasswordInput
            id="password-new"
            name="password-new"
            i18n={i18n}
            autoFocus
            autoComplete="new-password"
            aria-invalid={hasError}
            aria-describedby={passwordError?.id}
          />
        </Field>
        <Field
          htmlFor="password-confirm"
          label={msg("passwordConfirm")}
          error={confirmError}
        >
          <PasswordInput
            id="password-confirm"
            name="password-confirm"
            i18n={i18n}
            autoComplete="new-password"
            aria-invalid={hasError}
            aria-describedby={confirmError?.id}
          />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            id="logout-sessions"
            name="logout-sessions"
            value="on"
            defaultChecked
            className="size-4 accent-primary"
          />
          {msg("logoutOtherSessions")}
        </label>
        <div className="flex flex-col gap-2">
          <Button type="submit" className="w-full">
            {msgStr("doSubmit")}
          </Button>
          {isAppInitiatedAction && (
            <Button
              type="submit"
              variant="outline"
              className="w-full"
              name="cancel-aia"
              value="true"
            >
              {msg("doCancel")}
            </Button>
          )}
        </div>
      </form>
    </Template>
  )
}
