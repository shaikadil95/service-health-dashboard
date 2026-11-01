import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "@/App"
import { ThemeProvider } from "@/components/theme-provider"
import type { Order, Profile } from "@/lib/api"

const profile: Profile = {
  id: "c-1",
  name: "Ada Customer",
  email: "customer@shd.localtest.me",
  status: "active",
}

const order: Order = {
  id: "a1b2c3d4e5f6",
  user_id: "c-1",
  items: [{ sku: "book", quantity: 2, unit_price: "12.50" }],
  total: "25.00",
  currency: "EUR",
  status: "confirmed",
  payment_id: "pay-1",
  created_at: "2026-11-01T10:00:00Z",
}

type Handler = (path: string, init?: RequestInit) => Response

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })

function mockApi(handler: Handler) {
  const fetchMock = vi.fn(async (path: string, init?: RequestInit) =>
    handler(path, init)
  )
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </QueryClientProvider>
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("shop", () => {
  it("shows the signed-in customer and their orders", async () => {
    mockApi((path) => (path === "/api/me" ? json(profile) : json([order])))
    renderApp()
    expect(
      await screen.findByText("Signed in as Ada Customer")
    ).toBeInTheDocument()
    expect(await screen.findByText("a1b2c3d4e5f6")).toBeInTheDocument()
    expect(screen.getByText("2× book")).toBeInTheDocument()
    expect(screen.getByText("Confirmed")).toBeInTheDocument()
  })

  it("places an order without a user id and without a token", async () => {
    const fetchMock = mockApi((path, init) => {
      if (path === "/api/me") return json(profile)
      if (init?.method === "POST") return json(order, 201)
      return json([])
    })
    const user = userEvent.setup()
    renderApp()
    await screen.findByText("Signed in as Ada Customer")
    await user.click(
      screen.getByRole("button", {
        name: "One more Site Reliability Engineering",
      })
    )
    await user.click(
      screen.getByRole("button", {
        name: "One more Site Reliability Engineering",
      })
    )
    await user.click(screen.getByRole("button", { name: /place order/i }))
    expect(
      await screen.findByText("Thank you for your order")
    ).toBeInTheDocument()

    const post = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST"
    )
    expect(post?.[0]).toBe("/api/orders")
    const headers = post?.[1]?.headers as Record<string, string>
    expect(headers["X-Requested-With"]).toBe("fetch")
    expect(headers.Authorization).toBeUndefined()
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({
      items: [{ sku: "book", quantity: 2, unit_price: "12.50" }],
      currency: "EUR",
    })
  })

  it("asks to sign in again when the gateway session expired", async () => {
    mockApi(() => new Response("", { status: 401 }))
    renderApp()
    expect(
      await screen.findByText("Your session has expired")
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Sign in again" })
    ).toBeInTheDocument()
  })

  it("reports a declined payment", async () => {
    mockApi((path, init) => {
      if (path === "/api/me") return json(profile)
      if (init?.method === "POST")
        return json({ ...order, status: "payment_declined" }, 402)
      return json([])
    })
    const user = userEvent.setup()
    renderApp()
    await screen.findByText("Signed in as Ada Customer")
    await user.click(
      screen.getByRole("button", { name: "One more Laptop sleeve" })
    )
    await user.click(screen.getByRole("button", { name: /place order/i }))
    await waitFor(() =>
      expect(screen.getByText("Payment was declined")).toBeInTheDocument()
    )
  })

  it("links to the gateway's logout path", async () => {
    mockApi((path) => (path === "/api/me" ? json(profile) : json([])))
    renderApp()
    expect(screen.getByRole("link", { name: "Sign out" })).toHaveAttribute(
      "href",
      "/oauth2/logout"
    )
  })
})
