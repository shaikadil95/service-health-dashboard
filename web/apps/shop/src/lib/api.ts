// The shop's API: same origin, routed by the gateway (deploy/values/shop-web.yaml):
//   /api/me     -> user service  GET /users/me
//   /api/orders -> order service GET/POST /orders
// The browser holds no token. Envoy Gateway runs the OIDC login, keeps the session in encrypted
// HTTP-only cookies and adds the customer's access token to these calls (backend for frontend).

export type Profile = {
  id: string
  name: string
  email: string
  status: "active" | "suspended"
}

export type OrderItem = { sku: string; quantity: number; unit_price: string }

export type OrderStatus =
  "confirmed" | "payment_declined" | "payment_failed" | "payment_unknown"

export type Order = {
  id: string
  user_id: string
  items: OrderItem[]
  total: string
  currency: string
  status: OrderStatus
  payment_id: string | null
  created_at: string
}

/** The gateway session expired or is missing: a full page load starts a new login. */
export class SessionExpiredError extends Error {
  constructor() {
    super("Your session has expired")
    this.name = "SessionExpiredError"
  }
}

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, detail: string) {
    super(detail)
    this.name = "ApiError"
    this.status = status
  }
}

// X-Requested-With makes the gateway answer 401 instead of redirecting an expired session to
// the login page (a cross-origin redirect that fetch() cannot follow).
const HEADERS = { Accept: "application/json", "X-Requested-With": "fetch" }

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { ...HEADERS, ...(init.headers ?? {}) },
  })
  if (response.status === 401) {
    throw new SessionExpiredError()
  }
  const body = await response.json().catch(() => null)
  // 402 (payment declined) still returns the stored order.
  if (!response.ok && response.status !== 402) {
    const detail =
      body && typeof body.detail === "string"
        ? body.detail
        : `HTTP ${response.status}`
    throw new ApiError(response.status, detail)
  }
  return body as T
}

export const fetchProfile = (signal?: AbortSignal) =>
  call<Profile>("/api/me", { signal })

export const fetchOrders = (signal?: AbortSignal) =>
  call<Order[]>("/api/orders?limit=20", { signal })

// No user_id: the order service takes the customer from the access token.
export const placeOrder = (items: OrderItem[]) =>
  call<Order>("/api/orders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items, currency: "EUR" }),
  })
