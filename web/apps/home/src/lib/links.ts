// Every URL is on the shared gateway (*.localtest.me, HTTPS with the mkcert CA). The landing page
// itself is public; the targets below are not, so following a link visibly goes through Keycloak.

export type Realm = "customers" | "ops"

export type Tool = {
  name: string
  href: string
  description: string
  access: string
}

// Full-page navigation to the shop: the gateway has no session yet and redirects to the customers
// realm's branded login page, then back to the shop.
export const CUSTOMER_LOGIN = "https://shop.localtest.me/"

export const ENGINEERING_TOOLS: Tool[] = [
  {
    name: "Status page",
    href: "https://status.localtest.me/",
    description: "UP / DEGRADED / DOWN per service and the active alerts",
    access: "every engineer",
  },
  {
    name: "Grafana",
    // Starts Grafana's own Keycloak login directly (its /login page would ask which method first).
    href: "https://grafana.localtest.me/login/generic_oauth",
    description: "Dashboards, logs (Loki), traces (Tempo) and their links",
    access: "sre Admin · dev Editor · viewer Viewer",
  },
  {
    name: "Prometheus",
    href: "https://prometheus.localtest.me/",
    description: "Metrics, alert rules and scrape targets",
    access: "sre only",
  },
  {
    name: "Alertmanager",
    href: "https://alertmanager.localtest.me/",
    description: "Routing, grouping, inhibition and silences",
    access: "sre only",
  },
  {
    name: "Mailpit",
    href: "https://mail.localtest.me/",
    description: "The on-call inbox: alert emails",
    access: "sre only",
  },
  {
    name: "Keycloak admin",
    href: "https://sso.localtest.me/admin/",
    description: "Realms ops and customers, clients, users, sessions",
    access: "Keycloak admin (make sso-users)",
  },
]

// The gateway's logout path on a host of each session: it clears the session cookies, ends the
// Keycloak session (RP-initiated logout) and Keycloak sends the browser back here.
export const LOGOUT = {
  // The engineers' session is shared by the status page, Prometheus, Alertmanager and Mailpit.
  engineering: "https://status.localtest.me/oauth2/logout",
  shop: "https://shop.localtest.me/oauth2/logout",
} as const
