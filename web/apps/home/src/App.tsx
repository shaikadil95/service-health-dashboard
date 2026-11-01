import {
  Activity,
  ArrowRight,
  KeyRound,
  LogIn,
  LogOut,
  Store,
  Wrench,
} from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"

import { ThemeToggle } from "@/components/theme-toggle"
import { CUSTOMER_LOGIN, ENGINEERING_TOOLS, LOGOUT } from "@/lib/links"

export function App() {
  return (
    <div className="mx-auto flex min-h-svh max-w-6xl flex-col gap-8 p-4 sm:p-6">
      <header className="flex flex-wrap items-center gap-3">
        <Activity aria-hidden="true" className="size-6" />
        <div className="mr-auto">
          <h1 className="text-xl font-semibold">Service Health Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Lightweight observability for User, Order and Payment, with Keycloak
            single sign-on
          </p>
        </div>
        <ThemeToggle />
      </header>

      <main className="flex flex-col gap-8">
        <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
          Three instrumented services run on a local Kubernetes cluster behind
          Envoy Gateway. OpenTelemetry feeds Prometheus, Loki and Tempo;
          Grafana, the status page and email alerts show their health. This page
          is public. Everything it links to needs a Keycloak login: the gateway
          redirects you to{" "}
          <span className="font-medium text-foreground">sso.localtest.me</span>{" "}
          and back.
        </p>

        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Store aria-hidden="true" className="size-5" />
                Customer shop
              </CardTitle>
              <CardDescription>
                Browse the products and place orders. Sign in or register on the
                shop&apos;s own login page (Keycloak realm{" "}
                <code>customers</code>).
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              The gateway keeps your session in encrypted cookies and calls the
              order API for you; the page never sees a token.
            </CardContent>
            <CardFooter className="mt-auto">
              <Button size="lg" asChild>
                <a href={CUSTOMER_LOGIN}>
                  <LogIn aria-hidden="true" />
                  Customer login
                </a>
              </Button>
            </CardFooter>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Wrench aria-hidden="true" className="size-5" />
                Engineering portal
              </CardTitle>
              <CardDescription>
                One login (Keycloak realm <code>ops</code>) for all tools;
                access depends on your group.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ul
                className="flex flex-col divide-y"
                aria-label="Engineering tools"
              >
                {ENGINEERING_TOOLS.map((tool) => (
                  <li key={tool.name}>
                    <a
                      href={tool.href}
                      className="group flex items-center gap-3 py-2.5 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                    >
                      <span className="mr-auto">
                        <span className="block text-sm font-medium group-hover:underline">
                          {tool.name}
                        </span>
                        <span className="block text-xs text-muted-foreground">
                          {tool.description}
                        </span>
                      </span>
                      <Badge variant="outline">{tool.access}</Badge>
                      <ArrowRight
                        aria-hidden="true"
                        className="size-4 shrink-0 text-muted-foreground"
                      />
                    </a>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Architecture</CardTitle>
            <CardDescription>
              Services, telemetry pipeline, storage, alerting and identity.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <img
              src="/architecture.svg"
              alt="Architecture: the gateway in front of the User, Order and Payment services; the OpenTelemetry Collector sends metrics to Prometheus, logs to Loki and traces to Tempo; Grafana, the status page and Alertmanager with Mailpit read them; Keycloak signs everyone in."
              className="w-full rounded-lg border bg-white p-2"
              loading="lazy"
            />
          </CardContent>
        </Card>

        <section
          aria-labelledby="sign-out"
          className="flex flex-col gap-3 rounded-xl border p-4"
        >
          <h2 id="sign-out" className="flex items-center gap-2 font-medium">
            <KeyRound aria-hidden="true" className="size-4" />
            Sign out
          </h2>
          <p className="text-sm text-muted-foreground">
            Ends the gateway session and the Keycloak session, then brings you
            back here. The next protected page asks for your password again.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button variant="outline" asChild>
              <a href={LOGOUT.engineering}>
                <LogOut aria-hidden="true" />
                Sign out of engineering tools
              </a>
            </Button>
            <Button variant="outline" asChild>
              <a href={LOGOUT.shop}>
                <LogOut aria-hidden="true" />
                Sign out of the shop
              </a>
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Grafana has its own session: use Sign out in Grafana (it also ends
            the Keycloak session and returns here).
          </p>
        </section>
      </main>
    </div>
  )
}
