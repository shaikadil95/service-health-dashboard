import { useEffect } from "react"
import type { TemplateProps } from "keycloakify/login/TemplateProps"
import { useInitialize } from "keycloakify/login/Template.useInitialize"
import { Languages, RotateCcw, Store } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"

import { MessageAlert } from "./components/message-alert"
import type { I18n } from "./i18n"
import type { KcContext } from "./KcContext"

/**
 * Page frame of every login page (also the ones rendered by Keycloakify's DefaultPage): the shop
 * brand above a centered card, like the shop's header in apps/shop/src/App.tsx.
 */
export default function Template(props: TemplateProps<KcContext, I18n>) {
  const {
    displayInfo = false,
    displayMessage = true,
    displayRequiredFields = false,
    headerNode,
    socialProvidersNode = null,
    infoNode = null,
    documentTitle,
    kcContext,
    i18n,
    children,
  } = props

  const { msg, msgStr, currentLanguage, enabledLanguages } = i18n
  const { realm, auth, url, message, isAppInitiatedAction } = kcContext
  const brand = realm.displayName || realm.name

  useEffect(() => {
    document.title = documentTitle ?? msgStr("loginTitle", brand)
  }, [documentTitle, msgStr, brand])

  useEffect(() => {
    document.body.classList.add("bg-muted/40", "text-foreground", "antialiased")
  }, [])

  // Keycloak's own scripts (session polling across tabs, authenticator scripts); no PatternFly CSS.
  const { isReadyToRender } = useInitialize({
    kcContext,
    doUseDefaultCss: false,
  })
  if (!isReadyToRender) return null

  const showAttemptedUsername =
    auth !== undefined && auth.showUsername && !auth.showResetCredentials

  return (
    <div
      id="kc-container"
      className="flex min-h-svh flex-col items-center justify-center gap-6 p-4 sm:p-6"
    >
      <header id="kc-header" className="flex items-center gap-3">
        <Store aria-hidden="true" className="size-6" />
        <div>
          <p id="kc-header-wrapper" className="text-xl font-semibold">
            {brand}
          </p>
          <p className="text-sm text-muted-foreground">{msg("shopTagline")}</p>
        </div>
      </header>

      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>
            <h1 id="kc-page-title" className="text-lg font-semibold">
              {headerNode}
            </h1>
          </CardTitle>
          {showAttemptedUsername && (
            <CardDescription
              id="kc-username"
              className="flex items-center gap-2"
            >
              <span id="kc-attempted-username" className="truncate">
                {auth.attemptedUsername}
              </span>
              <Button variant="ghost" size="icon-xs" asChild>
                <a
                  id="reset-login"
                  href={url.loginRestartFlowUrl}
                  aria-label={msgStr("restartLoginTooltip")}
                  title={msgStr("restartLoginTooltip")}
                >
                  <RotateCcw aria-hidden="true" />
                </a>
              </Button>
            </CardDescription>
          )}
          {displayRequiredFields && (
            <CardDescription>
              <span aria-hidden="true" className="text-destructive">
                *
              </span>{" "}
              {msg("requiredFields")}
            </CardDescription>
          )}
          {enabledLanguages.length > 1 && (
            <CardAction>
              <details id="kc-locale" className="relative">
                <summary
                  className="flex cursor-pointer list-none items-center gap-1 rounded-md px-1.5 py-1 text-xs text-muted-foreground hover:bg-muted"
                  aria-label={msgStr("languages")}
                >
                  <Languages aria-hidden="true" className="size-3.5" />
                  {currentLanguage.label}
                </summary>
                <ul className="absolute right-0 z-10 mt-1 max-h-64 min-w-36 overflow-auto rounded-lg bg-popover p-1 text-sm text-popover-foreground shadow-md ring-1 ring-foreground/10">
                  {enabledLanguages.map(({ languageTag, label, href }) => (
                    <li key={languageTag}>
                      <a
                        href={href}
                        lang={languageTag}
                        className="block rounded-md px-2 py-1 hover:bg-muted"
                        aria-current={
                          languageTag === currentLanguage.languageTag
                            ? "true"
                            : undefined
                        }
                      >
                        {label}
                      </a>
                    </li>
                  ))}
                </ul>
              </details>
            </CardAction>
          )}
        </CardHeader>

        <CardContent id="kc-content" className="grid gap-4">
          {/* App-initiated actions don't show the "you need to ..." warnings (like Keycloak's template). */}
          {displayMessage &&
            message !== undefined &&
            (message.type !== "warning" || !isAppInitiatedAction) && (
              <MessageAlert message={message} />
            )}
          {children}
          {auth !== undefined && auth.showTryAnotherWayLink && (
            <form
              id="kc-select-try-another-way-form"
              action={url.loginAction}
              method="post"
            >
              <input type="hidden" name="tryAnotherWay" value="on" />
              <Button
                id="try-another-way"
                type="submit"
                variant="link"
                className="h-auto p-0"
              >
                {msg("doTryAnotherWay")}
              </Button>
            </form>
          )}
          {socialProvidersNode}
        </CardContent>

        {displayInfo && (
          <CardFooter
            id="kc-info"
            className="justify-center text-center text-sm text-muted-foreground [&_a]:font-medium [&_a]:text-foreground [&_a]:underline-offset-4 [&_a]:hover:underline"
          >
            {infoNode}
          </CardFooter>
        )}
      </Card>
    </div>
  )
}
