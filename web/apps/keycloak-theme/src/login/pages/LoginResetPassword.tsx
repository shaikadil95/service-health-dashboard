import type { PageProps } from "keycloakify/login/pages/PageProps"
import { ArrowLeft } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"

import { Field, usernameLabel } from "../components/form-field"
import type { I18n } from "../i18n"
import type { KcContext } from "../KcContext"

const ERROR_ID = "input-error-username"

export default function LoginResetPassword(
  props: PageProps<
    Extract<KcContext, { pageId: "login-reset-password.ftl" }>,
    I18n
  >
) {
  const { kcContext, i18n, doUseDefaultCss, Template, classes } = props
  const { url, realm, auth, messagesPerField } = kcContext
  const { msg, msgStr } = i18n

  const hasError = messagesPerField.existsError("username")

  return (
    <Template
      kcContext={kcContext}
      i18n={i18n}
      doUseDefaultCss={doUseDefaultCss}
      classes={classes}
      displayMessage={!hasError}
      headerNode={msg("emailForgotTitle")}
      displayInfo
      infoNode={
        <a id="kc-back-to-login" href={url.loginUrl}>
          <ArrowLeft aria-hidden="true" className="mr-1 inline size-4" />
          {msg("backToLogin")}
        </a>
      }
    >
      <form
        id="kc-reset-password-form"
        className="grid gap-4"
        action={url.loginAction}
        method="post"
      >
        <p id="kc-reset-password-instruction" className="text-muted-foreground">
          {realm.duplicateEmailsAllowed
            ? msg("emailInstructionUsername")
            : msg("emailInstruction")}
        </p>
        <Field
          htmlFor="username"
          label={usernameLabel(realm, i18n)}
          error={
            hasError
              ? { id: ERROR_ID, message: messagesPerField.get("username") }
              : undefined
          }
        >
          <Input
            id="username"
            name="username"
            type="text"
            autoFocus
            autoComplete="username"
            defaultValue={auth.attemptedUsername ?? ""}
            aria-invalid={hasError}
            aria-describedby={
              hasError
                ? `${ERROR_ID} kc-reset-password-instruction`
                : "kc-reset-password-instruction"
            }
          />
        </Field>
        <Button type="submit" className="w-full">
          {msgStr("doSubmit")}
        </Button>
      </form>
    </Template>
  )
}
