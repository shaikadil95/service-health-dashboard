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

export type Me = {
  username: string
  name: string | null
  email: string | null
  groups: string[]
}

/** No gateway session (never signed in, signed out or expired): the page shows its Login button. */
export class SessionExpiredError extends Error {
  constructor() {
    super("Not signed in")
    this.name = "SessionExpiredError"
  }
}

// The page itself is public. These paths are on the status-api route, which needs the engineers'
// gateway session (Keycloak realm ops):
//   /login          full-page navigation: Keycloak login (skipped when Keycloak already has a
//                   session), then the gateway redirects back to the page
//   /oauth2/logout  ends the gateway and Keycloak sessions, then the landing page
export const LOGIN_PATH = "/login"
export const LOGOUT_PATH = "/oauth2/logout"

// Same origin: the gateway routes /api on status.localtest.me to the Status API (no CORS).
// X-Requested-With makes the gateway's OIDC filter answer 401 instead of redirecting an expired
// session to the login page, which fetch() could not follow (Phase 6).
async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    signal,
    credentials: "same-origin",
    headers: { Accept: "application/json", "X-Requested-With": "fetch" },
  })
  if (response.status === 401) {
    throw new SessionExpiredError()
  }
  if (!response.ok) {
    throw new Error(`${path}: HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

export const fetchServices = (signal?: AbortSignal) =>
  getJson<ServicesResponse>("/api/v1/services", signal)

export const fetchAlerts = (signal?: AbortSignal) =>
  getJson<AlertsResponse>("/api/v1/alerts", signal)

export const fetchMe = (signal?: AbortSignal) =>
  getJson<Me>("/api/v1/me", signal)
