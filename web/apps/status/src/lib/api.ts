// Types of the Status API v1 contract (services/status-api, docs/architecture.md section 8).

export type Status = "UP" | "DEGRADED" | "DOWN" | "UNKNOWN"

export type Point = { t: number; v: number | null }

export type Metrics = {
  probe_success: boolean | null
  ready_replicas: number | null
  desired_replicas: number | null
  rps: number | null
  error_ratio_5m: number | null
  latency_p95_ms: number | null
}

export type Alert = {
  name: string
  service: string | null
  severity: string
  summary: string | null
  description: string | null
  runbook_url: string | null
  starts_at: string
}

export type ServiceStatus = {
  name: string
  status: Status
  reasons: string[]
  metrics: Metrics
  series: { rps: Point[]; error_ratio: Point[]; latency_p95_ms: Point[] }
  alerts: Alert[]
  links: { dashboard: string }
  updated_at: string | null
}

export type Source = {
  status: "ok" | "unavailable"
  error: string | null
  last_success_at: string | null
}

export type ServicesResponse = {
  status: Status
  services: ServiceStatus[]
  sources: { prometheus: Source; alertmanager: Source }
  thresholds: { error_ratio: number; latency_p95_ms: number }
  links: { grafana: string; overview_dashboard: string }
  generated_at: string
}

export type AlertsResponse = {
  alerts: Alert[]
  source: Source
  generated_at: string
}

// Same origin: the gateway routes /api on status.localtest.me to the Status API (no CORS).
async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    signal,
    headers: { Accept: "application/json" },
  })
  if (!response.ok) {
    throw new Error(`${path}: HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

export const fetchServices = (signal?: AbortSignal) =>
  getJson<ServicesResponse>("/api/v1/services", signal)

export const fetchAlerts = (signal?: AbortSignal) =>
  getJson<AlertsResponse>("/api/v1/alerts", signal)
