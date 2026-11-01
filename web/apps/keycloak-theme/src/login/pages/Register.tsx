import { useLayoutEffect, useState } from "react"
import type { LazyOrNot } from "keycloakify/tools/LazyOrNot"
import type { PageProps } from "keycloakify/login/pages/PageProps"
import type { UserProfileFormFieldsProps } from "keycloakify/login/UserProfileFormFieldsProps"
import type { JSX } from "keycloakify/tools/JSX"
import { ArrowLeft } from "lucide-react"

import { Button } from "@workspace/ui/components/button"

import { FieldError } from "../components/form-field"
import type { I18n } from "../i18n"
import type { KcContext } from "../KcContext"

type RegisterProps = PageProps<
  Extract<KcContext, { pageId: "register.ftl" }>,
  I18n
> & {
  UserProfileFormFields: LazyOrNot<
    (props: UserProfileFormFieldsProps) => JSX.Element
  >
  doMakeUserConfirmPassword: boolean
}

/**
 * Registration (register.ftl): the fields come from the realm's user profile (firstName,
 * lastName, email, username, password, password-confirm by default) and are posted with
 * Keycloak's standard names to url.registrationAction.
 */
export default function Register(props: RegisterProps) {
  const {
    kcContext,
    i18n,
    doUseDefaultCss,
    Template,
    classes,
    UserProfileFormFields,
    doMakeUserConfirmPassword,
  } = props
  const {
    messageHeader,
    url,
    messagesPerField,
    recaptchaRequired,
    recaptchaVisible,
    recaptchaSiteKey,
    recaptchaAction,
    termsAcceptanceRequired,
  } = kcContext
  const { msg, msgStr, advancedMsg } = i18n

  const [isFormSubmittable, setIsFormSubmittable] = useState(false)
  const [areTermsAccepted, setAreTermsAccepted] = useState(false)

  useLayoutEffect(() => {
    const w = window as unknown as Record<string, unknown>
    w["onSubmitRecaptcha"] = () => {
      ;(
        document.getElementById("kc-register-form") as HTMLFormElement | null
      )?.requestSubmit()
    }
    return () => {
      delete w["onSubmitRecaptcha"]
    }
  }, [])

  const invisibleRecaptcha =
    recaptchaRequired && !recaptchaVisible && recaptchaAction !== undefined
  const termsError = messagesPerField.existsError("termsAccepted")

  return (
    <Template
      kcContext={kcContext}
      i18n={i18n}
      doUseDefaultCss={doUseDefaultCss}
      classes={classes}
      headerNode={
        messageHeader !== undefined
          ? advancedMsg(messageHeader)
          : msg("registerTitle")
      }
      displayMessage={messagesPerField.exists("global")}
      displayRequiredFields
      displayInfo
      infoNode={
        <a id="kc-back-to-login" href={url.loginUrl}>
          <ArrowLeft aria-hidden="true" className="mr-1 inline size-4" />
          {msg("backToLogin")}
        </a>
      }
    >
      <form
        id="kc-register-form"
        className="grid gap-4"
        action={url.registrationAction}
        method="post"
      >
        <UserProfileFormFields
          kcContext={kcContext}
          i18n={i18n}
          kcClsx={() => ""}
          onIsFormSubmittableValueChange={setIsFormSubmittable}
          doMakeUserConfirmPassword={doMakeUserConfirmPassword}
        />
        {termsAcceptanceRequired && (
          <div className="grid gap-2">
            <div className="text-sm">
              <p className="font-medium">{msg("termsTitle")}</p>
              <div
                id="kc-registration-terms-text"
                className="text-muted-foreground"
              >
                {msg("termsText")}
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                id="termsAccepted"
                name="termsAccepted"
                className="size-4 accent-primary"
                checked={areTermsAccepted}
                onChange={(e) => setAreTermsAccepted(e.target.checked)}
                aria-invalid={termsError}
                aria-describedby={
                  termsError ? "input-error-terms-accepted" : undefined
                }
              />
              {msg("acceptTerms")}
            </label>
            {termsError && (
              <FieldError
                id="input-error-terms-accepted"
                message={messagesPerField.get("termsAccepted")}
              />
            )}
          </div>
        )}
        {recaptchaRequired && (recaptchaVisible || !recaptchaAction) && (
          <div
            className="g-recaptcha"
            data-size="compact"
            data-sitekey={recaptchaSiteKey}
            data-action={recaptchaAction}
          />
        )}
        <Button
          id="kc-register"
          type="submit"
          className={invisibleRecaptcha ? "g-recaptcha w-full" : "w-full"}
          disabled={
            !invisibleRecaptcha &&
            (!isFormSubmittable ||
              (termsAcceptanceRequired && !areTermsAccepted))
          }
          {...(invisibleRecaptcha && {
            "data-sitekey": recaptchaSiteKey,
            "data-callback": "onSubmitRecaptcha",
            "data-action": recaptchaAction,
          })}
        >
          {msgStr("doRegister")}
        </Button>
      </form>
    </Template>
  )
}
