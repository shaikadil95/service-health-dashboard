import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "@workspace/ui/globals.css"
import "./theme.css"

import { followSystemColorScheme } from "./color-scheme"
import { KcPage } from "./kc.gen"

async function main() {
  followSystemColorScheme()

  // `pnpm dev`: no Keycloak, so render a mock context; pick the page with ?page=register.ftl etc.
  if (import.meta.env.DEV && window.kcContext === undefined) {
    const { getKcContextMock } = await import("./login/mocks")
    const pageId = new URLSearchParams(window.location.search).get("page")
    window.kcContext = getKcContextMock({
      pageId: (pageId ?? "login.ftl") as "login.ftl",
    })
  }

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      {window.kcContext ? (
        <KcPage kcContext={window.kcContext} />
      ) : (
        <h1>No Keycloak context</h1>
      )}
    </StrictMode>
  )
}

void main()
