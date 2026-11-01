import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { App } from "@/App"
import { ThemeProvider } from "@/components/theme-provider"

function renderApp() {
  return render(
    <ThemeProvider>
      <App />
    </ThemeProvider>
  )
}

describe("landing page", () => {
  it("has one explicit login: the customer's, a full-page link to the shop", () => {
    renderApp()
    expect(
      screen.getByRole("link", { name: "Customer login" })
    ).toHaveAttribute("href", "https://shop.localtest.me/")
    expect(
      screen.queryByRole("link", { name: /engineering login/i })
    ).toBeNull()
  })

  it("links every engineering tool through the gateway", () => {
    renderApp()
    const tools = within(
      screen.getByRole("list", { name: "Engineering tools" })
    )
    const hrefs = tools.getAllByRole("link").map((a) => a.getAttribute("href"))
    expect(hrefs).toEqual([
      "https://status.localtest.me/",
      "https://grafana.localtest.me/login/generic_oauth",
      "https://prometheus.localtest.me/",
      "https://alertmanager.localtest.me/",
      "https://mail.localtest.me/",
      "https://sso.localtest.me/admin/",
    ])
  })

  it("offers both logouts via the gateway's logout path", () => {
    renderApp()
    expect(
      screen.getByRole("link", { name: "Sign out of engineering tools" })
    ).toHaveAttribute("href", "https://status.localtest.me/oauth2/logout")
    expect(
      screen.getByRole("link", { name: "Sign out of the shop" })
    ).toHaveAttribute("href", "https://shop.localtest.me/oauth2/logout")
  })

  it("shows the architecture diagram with a text alternative", () => {
    renderApp()
    expect(screen.getByRole("img", { name: /architecture/i })).toHaveAttribute(
      "src",
      "/architecture.svg"
    )
  })
})
