import type { AlertsResponse, ServiceStatus, ServicesResponse } from "@/lib/api"

const series = [
  { t: 1_800_000_000, v: 1 },
  { t: 1_800_000_060, v: 2 },
]

export function service(overrides: Partial<ServiceStatus> = {}): ServiceStatus {
  return {
    name: "user",
    status: "UP",
    reasons: [],
    metrics: {
      probe_success: true,
      ready_replicas: 1,
      desired_replicas: 1,
      rps: 2.5,
      error_ratio_5m: 0,
      latency_p95_ms: 4.8,
    },
    series: { rps: series, error_ratio: series, latency_p95_ms: series },
    alerts: [],
    links: {
      dashboard:
        "http://grafana.test/d/shd-service-detail/service-detail?var-service=user",
    },
    updated_at: "2026-10-31T22:00:00Z",
    ...overrides,
  }
}

export function servicesResponse(
  overrides: Partial<ServicesResponse> = {}
): ServicesResponse {
  return {
    status: "UP",
    services: [service()],
    sources: {
      prometheus: {
        status: "ok",
        error: null,
        last_success_at: "2026-10-31T22:00:00Z",
      },
      alertmanager: {
        status: "ok",
        error: null,
        last_success_at: "2026-10-31T22:00:00Z",
      },
    },
    thresholds: { error_ratio: 0.05, latency_p95_ms: 500 },
    links: {
      grafana: "http://grafana.test",
      overview_dashboard:
        "http://grafana.test/d/shd-overview/service-health-overview",
    },
    generated_at: "2026-10-31T22:00:00Z",
    ...overrides,
  }
}

export const noAlerts: AlertsResponse = {
  alerts: [],
  source: {
    status: "ok",
    error: null,
    last_success_at: "2026-10-31T22:00:00Z",
  },
  generated_at: "2026-10-31T22:00:00Z",
}
