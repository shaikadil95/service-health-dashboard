import { useState } from "react"
import { kcSanitize } from "keycloakify/lib/kcSanitize"
import type { PageProps } from "keycloakify/login/pages/PageProps"

import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"

import {
  Field,
  FieldError,
  PasswordInput,
  usernameLabel,
} from "../components/form-field"
import type { I18n } from "../i18n"
import type { KcContext } from "../KcContext"

const ERROR_ID = "input-error"

/**
 * Username + password (login.ftl). Keeps Keycloak's form id, field names and ids: scripts such as
 * deploy/scripts/oidc-login.py post `username`, `password` and `credentialId` to `kc-form-login`.
 * WebAuthn conditional UI and other variants are not enabled in the customers realm.
 */
export default function Login(
  props: PageProps<Extract<KcContext, { pageId: "login.ftl" }>, I18n>
) {
  const { kcContext, i18n, doUseDefaultCss, Template, classes } = props
  const {
    social,
    realm,
    url,
    usernameHidden,
    login,
    auth,
    registrationDisabled,
    messagesPerField,
  } = kcContext
  const { msg, msgStr } = i18n
  const [isSubmitting, setIsSubmitting] = useState(false)

  const hasError = messagesPerField.existsError("username", "password")
  const error = hasError
    ? messagesPerField.getFirstError("username", "password")
    : undefined
  const providers = social?.providers ?? []

  return (
    <Template
      kcContext={kcContext}
      i18n={i18n}
      doUseDefaultCss={doUseDefaultCss}
      classes={classes}
      displayMessage={!hasError}
      headerNode={msg("loginAccountTitle")}
      displayInfo={
        realm.password && realm.registrationAllowed && !registrationDisabled
      }
      infoNode={
        <p id="kc-registration">
          {msg("noAccount")}{" "}
          <a href={url.registrationUrl}>{msg("doRegister")}</a>
        </p>
      }
      socialProvidersNode={
        realm.password &&
        providers.length > 0 && (
          <div id="kc-social-providers" className="grid gap-2">
            <p className="text-center text-sm text-muted-foreground">
              {msg("identity-provider-login-label")}
            </p>
            {providers.map((p) => (
              <Button key={p.alias} variant="outline" asChild>
                <a
                  id={`social-${p.alias}`}
                  href={p.loginUrl}
                  dangerouslySetInnerHTML={{
                    __html: kcSanitize(p.displayName),
                  }}
                />
              </Button>
            ))}
          </div>
        )
      }
    >
      {realm.password && (
        <form
          id="kc-form-login"
          className="grid gap-4"
          action={url.loginAction}
          method="post"
          onSubmit={() => {
            setIsSubmitting(true)
            return true
          }}
        >
          {!usernameHidden && (
            <Field
              htmlFor="username"
              label={usernameLabel(realm, i18n)}
              error={error ? { id: ERROR_ID, message: error } : undefined}
            >
              <Input
                id="username"
                name="username"
                type="text"
                defaultValue={login.username ?? ""}
                autoFocus
                autoComplete="username"
                aria-invalid={hasError}
                aria-describedby={hasError ? ERROR_ID : undefined}
              />
            </Field>
          )}

          <div className="grid gap-2">
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="password">{msg("password")}</Label>
              {realm.resetPasswordAllowed && (
                <a
                  id="kc-forgot-password"
                  href={url.loginResetCredentialsUrl}
                  className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                >
                  {msg("doForgotPassword")}
                </a>
              )}
            </div>
            <PasswordInput
              id="password"
              name="password"
              i18n={i18n}
              autoComplete="current-password"
              aria-invalid={hasError}
              aria-describedby={hasError ? ERROR_ID : undefined}
            />
            {usernameHidden && error && (
              <FieldError id={ERROR_ID} message={error} />
            )}
          </div>

          {realm.rememberMe && !usernameHidden && (
            <label className="flex items-center gap-2 text-sm">
              <input
                id="rememberMe"
                name="rememberMe"
                type="checkbox"
                className="size-4 accent-primary"
                defaultChecked={!!login.rememberMe}
              />
              {msg("rememberMe")}
            </label>
          )}

          <input
            type="hidden"
            id="id-hidden-input"
            name="credentialId"
            value={auth.selectedCredential ?? ""}
          />
          <Button
            id="kc-login"
            name="login"
            type="submit"
            className="w-full"
            disabled={isSubmitting}
          >
            {msgStr("doLogIn")}
          </Button>
        </form>
      )}
    </Template>
  )
}
