// Steady, low background traffic for the demo: a few customers create orders and read them back
// through the public edge (http://api.localtest.me), so every request crosses the gateway and order
// calls user and payment. Run in the cluster by the loadgen release, or from the host:
//   k6 run loadgen/scripts/orders.js
//   BASE_URL=http://api.localtest.me:8080 RATE=5 k6 run loadgen/scripts/orders.js
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://api.localtest.me";
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

export default function () {
  const user = pick(USERS);
  const item = pick(SKUS);
  const created = http.post(
    `${BASE_URL}/orders`,
    JSON.stringify({
      user_id: user,
      items: [{ sku: item.sku, quantity: 1 + Math.floor(Math.random() * 3), unit_price: item.unit_price }],
      currency: "EUR",
    }),
    { headers: { "content-type": "application/json" }, tags: { name: "POST /orders" } },
  );
  // 402 is a business outcome (payment declined), not a failure of the service.
  check(created, { "order accepted (201/402)": (r) => r.status === 201 || r.status === 402 });

  if (created.status === 201 || created.status === 402) {
    const id = created.json("id");
    const fetched = http.get(`${BASE_URL}/orders/${id}`, { tags: { name: "GET /orders/{id}" } });
    check(fetched, { "order readable (200)": (r) => r.status === 200 });
  }

  if (Math.random() < 0.3) {
    const profile = http.get(`${BASE_URL}/users/${user}`, { tags: { name: "GET /users/{id}" } });
    check(profile, { "user readable (200)": (r) => r.status === 200 });
  }
}
