import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import KcPage from "./KcPage"
import { getKcContextMock } from "./mocks"

describe("login page", () => {
  it("keeps Keycloak's form contract and shows the shop branding", async () => {
    const kcContext = getKcContextMock({ pageId: "login.ftl" })
    render(<KcPage kcContext={kcContext} />)

    const username = await screen.findByLabelText(/username or email/i)
    const form = username.closest("form")!
    expect(form).toHaveAttribute("id", "kc-form-login")
    expect(form).toHaveAttribute("action", kcContext.url.loginAction)
    expect(form).toHaveAttribute("method", "post")
    expect(username).toHaveAttribute("name", "username")
    expect(screen.getByLabelText(/^password$/i)).toHaveAttribute(
      "name",
      "password"
    )
    expect(form.querySelector('input[name="credentialId"]')).not.toBeNull()
    expect(screen.getByRole("button", { name: /sign in/i })).toHaveAttribute(
      "type",
      "submit"
    )

    expect(screen.getByText("Service Health Shop")).toBeInTheDocument()
    expect(
      screen.getByRole("heading", { name: /sign in to your account/i })
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /register/i })).toHaveAttribute(
      "href",
      kcContext.url.registrationUrl
    )
    expect(
      screen.getByRole("link", { name: /forgot password/i })
    ).toHaveAttribute("href", kcContext.url.loginResetCredentialsUrl)
  })

  it("marks the fields invalid and describes them with the error", async () => {
    const kcContext = getKcContextMock({
      pageId: "login.ftl",
      overrides: {
        login: { username: "ada" },
        messagesPerField: {
          existsError: (...fields: string[]) =>
            fields.includes("username") || fields.includes("password"),
          getFirstError: () => "Invalid username or password.",
        },
      },
    })
    render(<KcPage kcContext={kcContext} />)

    const username = await screen.findByLabelText(/username or email/i)
    expect(username).toHaveValue("ada")
    expect(username).toHaveAttribute("aria-invalid", "true")
    expect(username).toHaveAttribute("aria-describedby", "input-error")
    expect(screen.getByLabelText(/^password$/i)).toHaveAttribute(
      "aria-invalid",
      "true"
    )
    expect(document.getElementById("input-error")).toHaveTextContent(
      "Invalid username or password."
    )
  })

  it("shows Keycloak's global message as an alert", async () => {
    const kcContext = getKcContextMock({
      pageId: "login.ftl",
      overrides: {
        message: { type: "error", summary: "Account is disabled." },
      },
    })
    render(<KcPage kcContext={kcContext} />)

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Account is disabled."
    )
  })

  it("hides the registration link when registration is disabled", async () => {
    const kcContext = getKcContextMock({
      pageId: "login.ftl",
      overrides: {
        realm: { registrationAllowed: false, resetPasswordAllowed: false },
      },
    })
    render(<KcPage kcContext={kcContext} />)

    await screen.findByLabelText(/username or email/i)
    expect(screen.queryByRole("link", { name: /register/i })).toBeNull()
    expect(screen.queryByRole("link", { name: /forgot password/i })).toBeNull()
  })
})

describe("other pages", () => {
  it("register posts Keycloak's standard field names", async () => {
    const kcContext = getKcContextMock({ pageId: "register.ftl" })
    render(<KcPage kcContext={kcContext} />)

    const form = (await screen.findByLabelText(/first name/i)).closest("form")!
    expect(form).toHaveAttribute("action", kcContext.url.registrationAction)
    const names = Array.from(
      form.querySelectorAll<HTMLInputElement>("input[name]"),
      (input) => input.name
    )
    expect(names).toEqual(
      expect.arrayContaining([
        "firstName",
        "lastName",
        "email",
        "username",
        "password",
        "password-confirm",
      ])
    )
    expect(screen.getByLabelText(/^email/i)).toHaveAttribute("id", "email")
    expect(
      screen.getByRole("link", { name: /back to sign in/i })
    ).toHaveAttribute("href", kcContext.url.loginUrl)
  })

  it("reset password asks for the username", async () => {
    const kcContext = getKcContextMock({ pageId: "login-reset-password.ftl" })
    render(<KcPage kcContext={kcContext} />)

    const username = await screen.findByLabelText(/^username/i)
    expect(username.closest("form")).toHaveAttribute(
      "id",
      "kc-reset-password-form"
    )
    expect(
      screen.getByRole("link", { name: /back to sign in/i })
    ).toBeInTheDocument()
  })

  it("error page shows the error message", async () => {
    const kcContext = getKcContextMock({
      pageId: "error.ftl",
      overrides: {
        message: { type: "error", summary: "Invalid parameter: redirect_uri" },
      },
    })
    render(<KcPage kcContext={kcContext} />)

    expect(
      await screen.findByText("Invalid parameter: redirect_uri")
    ).toBeInTheDocument()
    expect(screen.getByText("Service Health Shop")).toBeInTheDocument()
  })
})
