import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { TooltipProvider } from "@workspace/ui/components/tooltip"

import { App } from "@/App"
import { ThemeProvider } from "@/components/theme-provider"
import type { AlertsResponse, Me, ServicesResponse } from "@/lib/api"
import { noAlerts, service, servicesResponse } from "@/test/fixtures"

const sre: Me = {
  username: "sre",
  name: "Sam Reliability",
  email: "sre@shd.localtest.me",
  groups: ["sre"],
}

// Without a gateway session every /api call is 401 (mockApi(401)).
function mockApi(
  services: ServicesResponse | number,
  alerts: AlertsResponse = noAlerts,
  me: Me = sre
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      const body = path.endsWith("/alerts")
        ? alerts
        : path.endsWith("/me")
          ? services === 401
            ? 401
            : me
          : services
      if (typeof body === "number") {
        return new Response("unavailable", { status: body })
      }
      return new Response(JSON.stringify(body), {
        headers: { "Content-Type": "application/json" },
      })
    })
  )
}

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <TooltipProvider>
          <App />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("App", () => {
  it("shows every service with its status and metrics", async () => {
    mockApi(
      servicesResponse({
        status: "DEGRADED",
        services: [
          service(),
          service({
            name: "payment",
            status: "DEGRADED",
            reasons: ["5xx error ratio 32.0% > 5.0% (5m)"],
            metrics: { ...service().metrics, error_ratio_5m: 0.32 },
          }),
        ],
      })
    )
    renderApp()

    expect(
      await screen.findByText("Some services are degraded")
    ).toBeInTheDocument()
    const payment = screen.getByTestId("service-payment")
    expect(within(payment).getByText("DEGRADED")).toBeInTheDocument()
    expect(
      within(payment).getByText("5xx error ratio 32.0% > 5.0% (5m)")
    ).toBeInTheDocument()
    expect(within(payment).getByText("32%")).toBeInTheDocument()
    const user = screen.getByTestId("service-user")
    expect(within(user).getByText("UP")).toBeInTheDocument()
    expect(within(user).getByText("All checks passing")).toBeInTheDocument()
    expect(
      within(user).getByRole("link", { name: /grafana/i })
    ).toHaveAttribute("href", expect.stringContaining("var-service=user"))
    expect(await screen.findByText("No active alerts")).toBeInTheDocument()
  })

  it("lists active alerts", async () => {
    mockApi(servicesResponse(), {
      ...noAlerts,
      alerts: [
        {
          name: "HighErrorRate",
          service: "payment",
          severity: "critical",
          summary: "Payment 5xx above 5%",
          description: null,
          runbook_url: null,
          starts_at: new Date().toISOString(),
        },
      ],
    })
    renderApp()
    const row = (await screen.findByText("HighErrorRate")).closest("tr")!
    expect(within(row).getByText("critical")).toBeInTheDocument()
    expect(within(row).getByText("Payment 5xx above 5%")).toBeInTheDocument()
  })

  it("warns when a monitoring source is unavailable", async () => {
    mockApi(
      servicesResponse({
        status: "UNKNOWN",
        services: [
          service({
            status: "UNKNOWN",
            reasons: ["Prometheus is unreachable"],
          }),
        ],
        sources: {
          ...servicesResponse().sources,
          prometheus: {
            status: "unavailable",
            error: "prometheus: ConnectError",
            last_success_at: null,
          },
        },
      })
    )
    renderApp()
    expect(
      await screen.findByText("Monitoring data incomplete")
    ).toBeInTheDocument()
    expect(screen.getByText(/prometheus: ConnectError/)).toBeInTheDocument()
  })

  it("reports an unreachable Status API", async () => {
    mockApi(502)
    renderApp()
    expect(
      await screen.findByText("Status API unreachable")
    ).toBeInTheDocument()
  })

  it("shows a Login button instead of data without a session", async () => {
    mockApi(401)
    renderApp()
    expect(
      await screen.findByText("Sign in to see the service status")
    ).toBeInTheDocument()
    for (const link of screen.getAllByRole("link", { name: /login/i })) {
      expect(link).toHaveAttribute("href", "/login")
    }
    expect(screen.queryByText("Status API unreachable")).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Logout" })).toBeNull()
  })

  it("shows who is signed in and a Logout via the gateway", async () => {
    mockApi(servicesResponse(), noAlerts, { ...sre, groups: ["dev"] })
    renderApp()
    expect(await screen.findByText("Sam Reliability")).toBeInTheDocument()
    expect(screen.getByText("(dev)")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Logout" })).toHaveAttribute(
      "href",
      "/oauth2/logout"
    )
    expect(screen.queryByRole("link", { name: /login/i })).toBeNull()
  })
})
