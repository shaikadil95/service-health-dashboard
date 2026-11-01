import type { PageProps } from "keycloakify/login/pages/PageProps"

import { Button } from "@workspace/ui/components/button"

import type { I18n } from "../i18n"
import type { KcContext } from "../KcContext"

export default function LogoutConfirm(
  props: PageProps<Extract<KcContext, { pageId: "logout-confirm.ftl" }>, I18n>
) {
  const { kcContext, i18n, doUseDefaultCss, Template, classes } = props
  const { url, client, logoutConfirm } = kcContext
  const { msg, msgStr } = i18n

  return (
    <Template
      kcContext={kcContext}
      i18n={i18n}
      doUseDefaultCss={doUseDefaultCss}
      classes={classes}
      headerNode={msg("logoutConfirmTitle")}
    >
      <div id="kc-logout-confirm" className="grid gap-4">
        <p className="text-muted-foreground">{msg("logoutConfirmHeader")}</p>
        <form
          className="grid gap-2"
          action={url.logoutConfirmAction}
          method="POST"
        >
          <input type="hidden" name="session_code" value={logoutConfirm.code} />
          <Button
            id="kc-logout"
            name="confirmLogout"
            type="submit"
            value={msgStr("doLogout")}
            className="w-full"
          >
            {msgStr("doLogout")}
          </Button>
        </form>
        {!logoutConfirm.skipLink && client.baseUrl && (
          <Button variant="outline" className="w-full" asChild>
            <a href={client.baseUrl}>{msg("backToApplication")}</a>
          </Button>
        )}
      </div>
    </Template>
  )
}
