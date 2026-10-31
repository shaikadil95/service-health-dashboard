import { ExternalLink } from "lucide-react"

import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"

import { Sparkline } from "@/components/sparkline"
import { StatusBadge } from "@/components/status-badge"
import type { ServiceStatus, ServicesResponse } from "@/lib/api"
import { formatMs, formatPercent, formatRps } from "@/lib/format"

type MetricProps = {
  label: string
  hint: string
  value: string
  children: React.ReactNode
}

function Metric({ label, hint, value, children }: MetricProps) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <Tooltip>
        <TooltipTrigger asChild>
          <dt className="w-fit cursor-help text-xs text-muted-foreground underline decoration-dotted underline-offset-4">
            {label}
          </dt>
        </TooltipTrigger>
        <TooltipContent>{hint}</TooltipContent>
      </Tooltip>
      <dd className="text-base font-medium tabular-nums">{value}</dd>
      {children}
    </div>
  )
}

export function ServiceCard({
  service,
  thresholds,
}: {
  service: ServiceStatus
  thresholds: ServicesResponse["thresholds"]
}) {
  const { metrics, series } = service
  const replicas =
    metrics.ready_replicas === null
      ? "–"
      : `${metrics.ready_replicas}/${metrics.desired_replicas ?? "?"}`
  return (
    <Card
      aria-labelledby={`svc-${service.name}`}
      data-testid={`service-${service.name}`}
    >
      <CardHeader>
        <CardTitle id={`svc-${service.name}`} className="capitalize">
          {service.name}
        </CardTitle>
        <CardDescription>
          {service.reasons.length === 0 ? (
            "All checks passing"
          ) : (
            <ul className="list-disc pl-4">
              {service.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
        </CardDescription>
        <CardAction>
          <StatusBadge status={service.status} />
        </CardAction>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-3 gap-4">
          <Metric
            label="Requests"
            hint="Requests per second, 5-minute average (sparkline: 1-minute rate)"
            value={formatRps(metrics.rps)}
          >
            <Sparkline
              label="Request rate"
              points={series.rps}
              format={formatRps}
            />
          </Metric>
          <Metric
            label="Errors"
            hint={`Share of 5xx responses over 5 minutes; degraded above ${formatPercent(thresholds.error_ratio)}`}
            value={formatPercent(metrics.error_ratio_5m)}
          >
            <Sparkline
              label="5xx error ratio"
              points={series.error_ratio}
              format={formatPercent}
              threshold={thresholds.error_ratio}
              color="var(--chart-5)"
            />
          </Metric>
          <Metric
            label="p95 latency"
            hint={`95th percentile server latency over 5 minutes; degraded above ${formatMs(thresholds.latency_p95_ms)}`}
            value={formatMs(metrics.latency_p95_ms)}
          >
            <Sparkline
              label="p95 latency"
              points={series.latency_p95_ms}
              format={formatMs}
              threshold={thresholds.latency_p95_ms}
              color="var(--chart-3)"
            />
          </Metric>
        </dl>
      </CardContent>
      <CardFooter className="justify-between gap-4 text-xs text-muted-foreground">
        <span>
          Ready replicas {replicas} · probe{" "}
          {metrics.probe_success === null
            ? "–"
            : metrics.probe_success
              ? "passing"
              : "failing"}
        </span>
        <a
          className="inline-flex items-center gap-1 font-medium text-foreground underline-offset-4 hover:underline"
          href={service.links.dashboard}
          target="_blank"
          rel="noreferrer"
        >
          Grafana
          <ExternalLink aria-hidden="true" className="size-3" />
          <span className="sr-only">
            (opens the {service.name} dashboard in a new tab)
          </span>
        </a>
      </CardFooter>
    </Card>
  )
}
