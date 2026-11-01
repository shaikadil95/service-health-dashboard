import { kcSanitize } from "keycloakify/lib/kcSanitize"
import type { PageProps } from "keycloakify/login/pages/PageProps"
import { CircleX } from "lucide-react"

import { Alert, AlertDescription } from "@workspace/ui/components/alert"
import { Button } from "@workspace/ui/components/button"

import type { I18n } from "../i18n"
import type { KcContext } from "../KcContext"

export default function ErrorPage(
  props: PageProps<Extract<KcContext, { pageId: "error.ftl" }>, I18n>
) {
  const { kcContext, i18n, doUseDefaultCss, Template, classes } = props
  const { message, client, skipLink } = kcContext
  const { msg } = i18n

  return (
    <Template
      kcContext={kcContext}
      i18n={i18n}
      doUseDefaultCss={doUseDefaultCss}
      classes={classes}
      displayMessage={false}
      headerNode={msg("errorTitle")}
    >
      <div id="kc-error-message" className="grid gap-4">
        <Alert variant="destructive">
          <CircleX aria-hidden="true" />
          <AlertDescription
            className="text-destructive"
            dangerouslySetInnerHTML={{ __html: kcSanitize(message.summary) }}
          />
        </Alert>
        {!skipLink && !!client?.baseUrl && (
          <Button variant="outline" className="w-full" asChild>
            <a id="backToApplication" href={client.baseUrl}>
              {msg("backToApplication")}
            </a>
          </Button>
        )}
      </div>
    </Template>
  )
}
