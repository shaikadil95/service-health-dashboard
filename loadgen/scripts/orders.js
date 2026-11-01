// Steady, low background traffic for the demo: a few customers create orders and read them back
// through the public edge (https://api.localtest.me), so every request crosses the gateway and order
// calls user and payment. Run in the cluster by the loadgen release, or from the host:
//   CLIENT_SECRET=$(make -s loadgen-secret) k6 run loadgen/scripts/orders.js
//
// The API requires an OAuth 2.0 access token (Phase 6). k6 is a machine client, so it uses the
// client credentials grant with its own test client "loadgen" in Keycloak's customers realm
// (roles orders:read and orders:write, audience shop-api); the password grant stays disabled.
import http from "k6/http";
import { check, fail } from "k6";

const BASE_URL = __ENV.BASE_URL || "https://api.localtest.me";
const TOKEN_URL =
  __ENV.TOKEN_URL || "https://sso.localtest.me/realms/customers/protocol/openid-connect/token";
const CLIENT_ID = __ENV.CLIENT_ID || "loadgen";
const CLIENT_SECRET = __ENV.CLIENT_SECRET || "";
// Iterations per second. Each iteration makes 2-3 requests at the edge.
const RATE = parseInt(__ENV.RATE || "1", 10);
const DURATION = __ENV.DURATION || "24h";

// Active customers of the user service (u-1004 is suspended and would be rejected).
const USERS = ["u-1001", "u-1002", "u-1003"];
const SKUS = [
  { sku: "book", unit_price: "12.50" },
  { sku: "pen", unit_price: "1.99" },
  { sku: "laptop-sleeve", unit_price: "24.00" },
];

export const options = {
  scenarios: {
    orders: {
      // Open model: a fixed arrival rate, independent of how fast the services answer, so a slow
      // or failing service shows up as latency and errors rather than as less traffic.
      executor: "constant-arrival-rate",
      rate: RATE,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 4,
      maxVUs: 10,
    },
  },
  // A long-running background job: no end-of-test summary thresholds.
  summaryTrendStats: ["avg", "p(95)", "max"],
};

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

// Per VU: one token, renewed 30 s before it expires.
let token = "";
let tokenExpiresAt = 0;

function accessToken() {
  if (token && Date.now() < tokenExpiresAt) {
    return token;
  }
  const res = http.post(
    TOKEN_URL,
    { grant_type: "client_credentials", client_id: CLIENT_ID, client_secret: CLIENT_SECRET },
    { tags: { name: "token" } },
  );
  if (res.status !== 200) {
    fail(`token request failed: HTTP ${res.status}`);
  }
  token = res.json("access_token");
  tokenExpiresAt = Date.now() + (res.json("expires_in") - 30) * 1000;
  return token;
}

export default function () {
  const auth = { authorization: `Bearer ${accessToken()}` };
  const user = pick(USERS);
  const item = pick(SKUS);
  const created = http.post(
    `${BASE_URL}/orders`,
    JSON.stringify({
      user_id: user,
      items: [{ sku: item.sku, quantity: 1 + Math.floor(Math.random() * 3), unit_price: item.unit_price }],
      currency: "EUR",
    }),
    { headers: { ...auth, "content-type": "application/json" }, tags: { name: "POST /orders" } },
  );
  // 402 is a business outcome (payment declined), not a failure of the service.
  check(created, { "order accepted (201/402)": (r) => r.status === 201 || r.status === 402 });

  if (created.status === 201 || created.status === 402) {
    const id = created.json("id");
    const fetched = http.get(`${BASE_URL}/orders/${id}`, {
      headers: auth,
      tags: { name: "GET /orders/{id}" },
    });
    check(fetched, { "order readable (200)": (r) => r.status === 200 });
  }

  if (Math.random() < 0.3) {
    const profile = http.get(`${BASE_URL}/users/${user}`, {
      headers: auth,
      tags: { name: "GET /users/{id}" },
    });
    check(profile, { "user readable (200)": (r) => r.status === 200 });
  }
}
