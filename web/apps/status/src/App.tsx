import { useQuery } from "@tanstack/react-query"
import { Activity, ExternalLink } from "lucide-react"

import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
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
import { fetchAlerts, fetchServices } from "@/lib/api"
import { formatTime } from "@/lib/format"

// Matches the Status API's server-side cache; polling faster would only return cached data.
export const REFRESH_MS = 10_000

const SUMMARY = {
  UP: "All systems operational",
  DEGRADED: "Some services are degraded",
  DOWN: "Service outage",
  UNKNOWN: "Status unknown",
} as const

export function App() {
  const services = useQuery({
    queryKey: ["services"],
    queryFn: ({ signal }) => fetchServices(signal),
    refetchInterval: REFRESH_MS,
  })
  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: ({ signal }) => fetchAlerts(signal),
    refetchInterval: REFRESH_MS,
  })
  const data = services.data
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
      </header>

      <main className="flex flex-col gap-6">
        <section
          aria-live="polite"
          aria-label="Overall status"
          className="flex flex-wrap items-center gap-3 rounded-xl border p-4"
        >
          {data ? (
            <>
              <StatusBadge status={data.status} className="h-7 px-3 text-sm" />
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
    </div>
  )
}
