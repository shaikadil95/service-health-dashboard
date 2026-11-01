import { useQuery } from "@tanstack/react-query"
import { Activity, ExternalLink, LogIn, LogOut } from "lucide-react"

import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { Skeleton } from "@workspace/ui/components/skeleton"

import { AlertsTable } from "@/components/alerts-table"
import { ServiceCard } from "@/components/service-card"
import { StatusBadge } from "@/components/status-badge"
import { ThemeToggle } from "@/components/theme-toggle"
import {
  fetchAlerts,
  fetchMe,
  fetchServices,
  LOGIN_PATH,
  LOGOUT_PATH,
  SessionExpiredError,
  type Me,
} from "@/lib/api"
import { formatTime } from "@/lib/format"

// Matches the Status API's server-side cache; polling faster would only return cached data.
export const REFRESH_MS = 10_000

const SUMMARY = {
  UP: "All systems operational",
  DEGRADED: "Some services are degraded",
  DOWN: "Service outage",
  UNKNOWN: "Status unknown",
} as const

// Stop polling while there is no session: only a full-page login can start one.
const poll = (error: Error | null) =>
  error instanceof SessionExpiredError ? false : REFRESH_MS

export function App() {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => fetchMe(signal),
    staleTime: Infinity,
  })
  const services = useQuery({
    queryKey: ["services"],
    queryFn: ({ signal }) => fetchServices(signal),
    refetchInterval: (query) => poll(query.state.error),
  })
  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: ({ signal }) => fetchAlerts(signal),
    refetchInterval: (query) => poll(query.state.error),
  })
  const signedOut = [me.error, services.error].some(
    (e) => e instanceof SessionExpiredError
  )
  const data = signedOut ? undefined : services.data
  const unavailable = data
    ? (["prometheus", "alertmanager"] as const).filter(
        (name) => data.sources[name].status !== "ok"
      )
    : []

  return (
    <div className="mx-auto flex min-h-svh max-w-6xl flex-col gap-6 p-4 sm:p-6">
      <header className="flex flex-wrap items-center gap-3">
        <Activity aria-hidden="true" className="size-6" />
        <div className="mr-auto">
          <h1 className="text-xl font-semibold">Service status</h1>
          <p className="text-sm text-muted-foreground">
            User, Order and Payment · refreshed every {REFRESH_MS / 1000}s
          </p>
        </div>
        {data && (
          <a
            className="inline-flex items-center gap-1 text-sm font-medium underline-offset-4 hover:underline"
            href={data.links.overview_dashboard}
            target="_blank"
            rel="noreferrer"
          >
            Grafana overview
            <ExternalLink aria-hidden="true" className="size-3.5" />
          </a>
        )}
        <ThemeToggle />
        {me.data && !signedOut ? (
          <SignedIn me={me.data} />
        ) : (
          signedOut && (
            <Button asChild>
              <a href={LOGIN_PATH}>
                <LogIn aria-hidden="true" />
                Login
              </a>
            </Button>
          )
        )}
      </header>

      {signedOut ? (
        <SignInPrompt />
      ) : (
        <main className="flex flex-col gap-6">
          <section
            aria-live="polite"
            aria-label="Overall status"
            className="flex flex-wrap items-center gap-3 rounded-xl border p-4"
          >
            {data ? (
              <>
                <StatusBadge
                  status={data.status}
                  className="h-7 px-3 text-sm"
                />
                <span className="font-medium">{SUMMARY[data.status]}</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  Updated {formatTime(data.generated_at)}
                  {services.isFetching && " · refreshing"}
                </span>
              </>
            ) : (
              <Skeleton className="h-7 w-64" />
            )}
          </section>

          {services.isError && (
            <Alert variant="destructive">
              <AlertTitle>Status API unreachable</AlertTitle>
              <AlertDescription>
                {String(services.error.message)}.{" "}
                {data
                  ? `Showing the last answer from ${formatTime(data.generated_at)}.`
                  : "Retrying every 10 seconds."}
              </AlertDescription>
            </Alert>
          )}
          {unavailable.length > 0 && data && (
            <Alert>
              <AlertTitle>Monitoring data incomplete</AlertTitle>
              <AlertDescription>
                {unavailable
                  .map(
                    (name) =>
                      `${name}: ${data.sources[name].error ?? "unavailable"}`
                  )
                  .join("; ")}
                . Statuses that depend on it show UNKNOWN or are based on the
                remaining source.
              </AlertDescription>
            </Alert>
          )}

          <section aria-label="Services" className="grid gap-4 lg:grid-cols-3">
            {data
              ? data.services.map((service) => (
                  <ServiceCard
                    key={service.name}
                    service={service}
                    thresholds={data.thresholds}
                  />
                ))
              : [0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-64 rounded-xl" />
                ))}
          </section>

          <Card>
            <CardHeader>
              <CardTitle>
                <h2>Active alerts</h2>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {alerts.data ? (
                alerts.data.source.status === "ok" ? (
                  <AlertsTable alerts={alerts.data.alerts} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Alertmanager is unreachable ({alerts.data.source.error}).
                  </p>
                )
              ) : (
                <Skeleton className="h-20" />
              )}
            </CardContent>
          </Card>
        </main>
      )}
    </div>
  )
}

function SignedIn({ me }: { me: Me }) {
  const groups = me.groups.length > 0 ? me.groups.join(", ") : "no group"
  return (
    <>
      <span className="text-sm" aria-live="polite">
        Signed in as{" "}
        <span className="font-medium">{me.name ?? me.username}</span>{" "}
        <span className="text-muted-foreground">({groups})</span>
      </span>
      <Button variant="outline" asChild>
        <a href={LOGOUT_PATH}>
          <LogOut aria-hidden="true" />
          Logout
        </a>
      </Button>
    </>
  )
}

function SignInPrompt() {
  return (
    <main className="flex flex-1 items-start justify-center pt-12">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>
            <h2>Sign in to see the service status</h2>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 text-sm text-muted-foreground">
          <p>
            The status page is for engineers (Keycloak realm <code>ops</code>).
            If you already signed in to another engineering tool, this takes you
            straight back without a password.
          </p>
          <Button asChild className="self-start">
            <a href={LOGIN_PATH}>
              <LogIn aria-hidden="true" />
              Login with Keycloak
            </a>
          </Button>
        </CardContent>
      </Card>
    </main>
  )
}
