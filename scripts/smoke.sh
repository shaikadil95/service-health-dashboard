#!/usr/bin/env bash
# End-to-end smoke test for the compose stack (`make compose-up` first).
# Checks probes, the order flow, fault injection, and that one order produced one distributed
# trace across order, user and payment in the OTel Collector debug output.
set -euo pipefail

COMPOSE=${COMPOSE:-docker compose}
USER_URL=${USER_URL:-http://127.0.0.1:8081}
ORDER_URL=${ORDER_URL:-http://127.0.0.1:8082}
PAYMENT_URL=${PAYMENT_URL:-http://127.0.0.1:8083}
ORDER='{"user_id":"u-1001","items":[{"sku":"book","quantity":2,"unit_price":"12.50"}],"currency":"EUR"}'

pass() { printf '  \033[32mok\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1" >&2; exit 1; }

expect_status() { # expect_status <description> <expected> <curl args...>
  local description=$1 expected=$2 actual
  shift 2
  actual=$(curl -s -o /dev/null -w '%{http_code}' "$@")
  [[ $actual == "$expected" ]] || fail "$description: expected HTTP $expected, got $actual"
  pass "$description -> $actual"
}

put_faults() { # put_faults <base url> <json>
  curl -sf -X PUT "$1/admin/faults" -H 'content-type: application/json' -d "$2" >/dev/null
}

reset_faults() {
  for url in "$USER_URL" "$ORDER_URL" "$PAYMENT_URL"; do
    curl -s -X DELETE "$url/admin/faults" >/dev/null || true
  done
}
trap reset_faults EXIT

echo "Waiting for readiness"
for url in "$USER_URL" "$ORDER_URL" "$PAYMENT_URL"; do
  for _ in $(seq 1 30); do
    curl -sf "$url/readyz" >/dev/null && break
    sleep 1
  done
  expect_status "$url/readyz" 200 "$url/readyz"
  expect_status "$url/livez" 200 "$url/livez"
done

echo "Business flow"
response=$(curl -sf -X POST "$ORDER_URL/orders" -H 'content-type: application/json' -d "$ORDER")
order_id=$(sed -E 's/.*"id":"([^"]+)".*/\1/' <<<"$response")
grep -q '"status":"confirmed"' <<<"$response" || fail "order not confirmed: $response"
pass "POST /orders -> confirmed ($order_id)"
expect_status "GET /orders/$order_id" 200 "$ORDER_URL/orders/$order_id"
expect_status "unknown user" 422 -X POST "$ORDER_URL/orders" -H 'content-type: application/json' \
  -d "${ORDER/u-1001/u-9999}"

echo "Fault injection"
put_faults "$PAYMENT_URL" '{"error_rate": 1.0}'
expect_status "payment error_rate=1 -> order" 502 -X POST "$ORDER_URL/orders" \
  -H 'content-type: application/json' -d "$ORDER"
put_faults "$PAYMENT_URL" '{"error_rate": 0}'
put_faults "$USER_URL" '{"ready": false}'
expect_status "user ready=false -> user /readyz" 503 "$USER_URL/readyz"
expect_status "user ready=false -> user /livez" 200 "$USER_URL/livez"
expect_status "order /readyz unaffected by user" 200 "$ORDER_URL/readyz"
reset_faults

echo "Distributed trace in the Collector"
# Capture logs first: `grep -q` closing a pipe early would fail the pipeline under pipefail.
logs() { $COMPOSE logs --no-log-prefix "$1" 2>/dev/null; }
order_logs=$(logs order-service)
trace_id=$(grep "\"order.id\": \"$order_id\"" <<<"$order_logs" | head -1 \
  | sed -E 's/.*"trace_id": "([0-9a-f]{32})".*/\1/' || true)
[[ $trace_id =~ ^[0-9a-f]{32}$ ]] || fail "no trace_id logged for order $order_id"
for svc in user-service payment-service; do
  service_logs=$(logs "$svc")
  grep -q "\"trace_id\": \"$trace_id\"" <<<"$service_logs" \
    || fail "$svc has no log line with trace_id $trace_id"
done
pass "trace_id $trace_id in the JSON logs of order, user and payment"
for _ in $(seq 1 15); do
  collector_logs=$(logs otel-collector)
  spans=$(grep -c "Trace ID       : $trace_id" <<<"$collector_logs" || true)
  [[ $spans -ge 5 ]] && break
  sleep 1
done
[[ $spans -ge 5 ]] || fail "expected >= 5 spans for trace $trace_id in the Collector, saw $spans"
pass "Collector received $spans spans for trace $trace_id"
echo "Smoke test passed"
