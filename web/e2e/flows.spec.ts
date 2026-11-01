import { mkdirSync } from "node:fs"
import { resolve } from "node:path"

import { expect, test, type Page } from "@playwright/test"

// Scripted browser flows of Phase 6b against the running cluster (`make verify-browser`, which
// passes the demo passwords from the cluster's Secrets):
//   engineer: landing page -> status page (Login button) -> Keycloak ops realm, default theme ->
//             back with data -> Prometheus without a new login (shared session) -> sign out ->
//             landing page -> the next protected page asks for the password again
//   SSO:      Grafana's own Keycloak login -> the status page's Login returns without a password
//   customer: landing page -> Customer login -> branded login page (customers realm) -> order ->
//             shop Sign out -> landing page -> the shop asks for the password again
// Screenshots for the docs go to SCREENSHOTS (default docs/screenshots).

const HOME = "https://home.localtest.me/"
const SCREENSHOTS = resolve(
  process.env.SCREENSHOTS ??
    resolve(import.meta.dirname, "../../docs/screenshots")
)
mkdirSync(SCREENSHOTS, { recursive: true })

function password(user: string): string {
  const value = process.env[`E2E_${user.toUpperCase()}_PASSWORD`]
  if (!value) throw new Error(`E2E_${user.toUpperCase()}_PASSWORD is not set`)
  return value
}

const shot = (page: Page, name: string) =>
  page.screenshot({ path: resolve(SCREENSHOTS, name), fullPage: true })

async function expectKeycloakLogin(page: Page, realm: "ops" | "customers") {
  await expect(page).toHaveURL(
    new RegExp(`^https://sso\\.localtest\\.me/realms/${realm}/`)
  )
  await expect(page.locator('input[name="password"]')).toBeVisible()
}

async function signIn(page: Page, user: string) {
  await page.locator('input[name="username"]').fill(user)
  await page.locator('input[name="password"]').fill(password(user))
  await page.locator('#kc-form-login [type="submit"]').click()
}

// The login page's theme: Keycloak serves each theme's files under /resources/<v>/login/<theme>/.
const themeOf = (page: Page) =>
  page.evaluate(() => {
    const urls = [
      ...Array.from(document.querySelectorAll("link[href]"), (l) =>
        l.getAttribute("href")
      ),
      ...Array.from(document.querySelectorAll("script[src]"), (s) =>
        s.getAttribute("src")
      ),
    ]
    for (const url of urls) {
      const match = /\/login\/([^/]+)\//.exec(url ?? "")
      if (match) return match[1]
    }
    return null
  })

test("engineer: landing page -> status page login -> shared session -> logout to the landing page", async ({
  page,
}) => {
  await page.goto(HOME)
  await expect(
    page.getByRole("heading", { name: "Service Health Dashboard" })
  ).toBeVisible()
  await expect(page.getByRole("img", { name: /architecture/i })).toBeVisible()
  await shot(page, "home.png")

  await page.getByRole("link", { name: /Status page/ }).click()
  await expect(page).toHaveURL("https://status.localtest.me/")
  await expect(
    page.getByText("Sign in to see the service status")
  ).toBeVisible()
  await shot(page, "status-signed-out.png")

  await page.getByRole("link", { name: "Login with Keycloak" }).click()
  await expectKeycloakLogin(page, "ops")
  expect(await themeOf(page)).toBe("keycloak.v2")
  await shot(page, "keycloak-login-ops.png")
  await signIn(page, "sre")

  await expect(page).toHaveURL("https://status.localtest.me/")
  await expect(page.getByText("Sam Reliability")).toBeVisible()
  await expect(page.getByText("(sre)")).toBeVisible()
  await expect(page.getByRole("link", { name: "Logout" })).toBeVisible()
  await expect(page.locator("#svc-payment")).toBeVisible()

  // Same gateway session (cookies on .localtest.me): Prometheus opens without Keycloak.
  await page.goto(HOME)
  await page.getByRole("link", { name: /Prometheus/ }).click()
  await expect(page).toHaveURL(/^https:\/\/prometheus\.localtest\.me\//)

  await page.goto(HOME)
  await page
    .getByRole("link", { name: "Sign out of engineering tools" })
    .click()
  await expect(page).toHaveURL(HOME)
  await expect(
    page.getByRole("heading", { name: "Service Health Dashboard" })
  ).toBeVisible()
  await shot(page, "post-logout-home.png")

  // Logged out of Keycloak too: the next protected page asks for the password.
  await page.goto("https://prometheus.localtest.me/")
  await expectKeycloakLogin(page, "ops")
  await page.goto("https://status.localtest.me/")
  await expect(
    page.getByRole("link", { name: "Login with Keycloak" })
  ).toBeVisible()
})

test("SSO: after Grafana's Keycloak login the status page's Login needs no password", async ({
  page,
}) => {
  await page.goto(HOME)
  await page.getByRole("link", { name: /Grafana/ }).click()
  await expectKeycloakLogin(page, "ops")
  await signIn(page, "sre")
  await expect(page).toHaveURL(/^https:\/\/grafana\.localtest\.me\//)

  await page.goto("https://status.localtest.me/")
  await page.getByRole("link", { name: "Login with Keycloak" }).click()
  await expect(page).toHaveURL("https://status.localtest.me/")
  await expect(page.getByText("Sam Reliability")).toBeVisible()

  await page.getByRole("link", { name: "Logout" }).click()
  await expect(page).toHaveURL(HOME)
})

test("customer: Customer login -> branded login page -> order -> sign out to the landing page", async ({
  page,
}) => {
  await page.goto(HOME)
  await page.getByRole("link", { name: "Customer login" }).click()
  await expectKeycloakLogin(page, "customers")
  expect(await themeOf(page)).toBe("shd-shop")
  await expect(page.getByText("Service Health Shop").first()).toBeVisible()
  await shot(page, "customer-login.png")

  await page.getByRole("link", { name: /register/i }).click()
  await expect(page.locator('input[name="password-confirm"]')).toBeVisible()
  await shot(page, "customer-register.png")
  await page.goBack()
  await expectKeycloakLogin(page, "customers")

  await signIn(page, "customer")
  await expect(page).toHaveURL("https://shop.localtest.me/")
  await expect(page.getByText("Signed in as Ada Customer")).toBeVisible()
  await page
    .getByRole("button", { name: "One more Site Reliability Engineering" })
    .click()
  await page.getByRole("button", { name: /place order/i }).click()
  await expect(page.getByText("Thank you for your order")).toBeVisible()

  await page.getByRole("link", { name: "Sign out" }).click()
  await expect(page).toHaveURL(HOME)

  await page.goto("https://shop.localtest.me/")
  await expectKeycloakLogin(page, "customers")
})
