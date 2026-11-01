import { kcSanitize } from "keycloakify/lib/kcSanitize"
import type { PageProps } from "keycloakify/login/pages/PageProps"

import { Button } from "@workspace/ui/components/button"

import type { I18n } from "../i18n"
import type { KcContext } from "../KcContext"

export default function Info(
  props: PageProps<Extract<KcContext, { pageId: "info.ftl" }>, I18n>
) {
  const { kcContext, i18n, doUseDefaultCss, Template, classes } = props
  const { advancedMsgStr, msg } = i18n
  const {
    messageHeader,
    message,
    requiredActions,
    skipLink,
    pageRedirectUri,
    actionUri,
    client,
  } = kcContext

  let html = message.summary?.trim() ?? ""
  if (requiredActions) {
    html += ` <b>${requiredActions
      .map((action) => advancedMsgStr(`requiredAction.${action}`))
      .join(", ")}</b>`
  }

  const link = skipLink
    ? undefined
    : pageRedirectUri
      ? { href: pageRedirectUri, label: msg("backToApplication") }
      : actionUri
        ? { href: actionUri, label: msg("proceedWithAction") }
        : client.baseUrl
          ? { href: client.baseUrl, label: msg("backToApplication") }
          : undefined

  return (
    <Template
      kcContext={kcContext}
      i18n={i18n}
      doUseDefaultCss={doUseDefaultCss}
      classes={classes}
      displayMessage={false}
      headerNode={
        <span
          dangerouslySetInnerHTML={{
            __html: kcSanitize(
              messageHeader ? advancedMsgStr(messageHeader) : message.summary
            ),
          }}
        />
      }
    >
      <div id="kc-info-message" className="grid gap-4">
        <p
          className="text-muted-foreground"
          dangerouslySetInnerHTML={{ __html: kcSanitize(html) }}
        />
        {link && (
          <Button className="w-full" asChild>
            <a href={link.href}>{link.label}</a>
          </Button>
        )}
      </div>
    </Template>
  )
}
