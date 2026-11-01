import { lazy, Suspense } from "react"
import DefaultPage from "keycloakify/login/DefaultPage"

import { classes } from "./classes"
import { useI18n } from "./i18n"
import type { KcContext } from "./KcContext"
import Template from "./Template"

const UserProfileFormFields = lazy(() => import("./UserProfileFormFields"))
const Login = lazy(() => import("./pages/Login"))
const Register = lazy(() => import("./pages/Register"))
const LoginResetPassword = lazy(() => import("./pages/LoginResetPassword"))
const LoginUpdatePassword = lazy(() => import("./pages/LoginUpdatePassword"))
const ErrorPage = lazy(() => import("./pages/Error"))
const Info = lazy(() => import("./pages/Info"))
const LogoutConfirm = lazy(() => import("./pages/LogoutConfirm"))

const doMakeUserConfirmPassword = true

/**
 * Routes Keycloak's page ids (*.ftl) to the custom pages; every other page is Keycloakify's
 * DefaultPage inside our Template, styled through `classes` (no PatternFly CSS).
 */
export default function KcPage(props: { kcContext: KcContext }) {
  const { kcContext } = props
  const { i18n } = useI18n({ kcContext })
  const common = {
    i18n,
    Template,
    classes,
    doUseDefaultCss: false,
  }

  return (
    <Suspense>
      {(() => {
        switch (kcContext.pageId) {
          case "login.ftl":
            return <Login kcContext={kcContext} {...common} />
          case "register.ftl":
            return (
              <Register
                kcContext={kcContext}
                {...common}
                UserProfileFormFields={UserProfileFormFields}
                doMakeUserConfirmPassword={doMakeUserConfirmPassword}
              />
            )
          case "login-reset-password.ftl":
            return <LoginResetPassword kcContext={kcContext} {...common} />
          case "login-update-password.ftl":
            return <LoginUpdatePassword kcContext={kcContext} {...common} />
          case "error.ftl":
            return <ErrorPage kcContext={kcContext} {...common} />
          case "info.ftl":
            return <Info kcContext={kcContext} {...common} />
          case "logout-confirm.ftl":
            return <LogoutConfirm kcContext={kcContext} {...common} />
          default:
            return (
              <DefaultPage
                kcContext={kcContext}
                {...common}
                UserProfileFormFields={UserProfileFormFields}
                doMakeUserConfirmPassword={doMakeUserConfirmPassword}
              />
            )
        }
      })()}
    </Suspense>
  )
}
