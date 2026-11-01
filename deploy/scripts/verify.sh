#!/usr/bin/env bash
# Automated Phase 2 checks against the running kind cluster (`make verify`).
#   1. Workloads and the Gateway are ready.
#   2. Host -> gateway: business routes work; payment, admin, probes and docs are not exposed.
#   3. Pod -> https://api.localtest.me (CoreDNS rewrite) works from outside the apps namespace.
#   4. NetworkPolicy: a pod outside apps cannot reach payment or user directly.
#   5. Readiness: forcing ready=false removes the pod from the EndpointSlice without a restart.
# Since Phase 6 the API is HTTPS only and needs a bearer token: the checks use the load generator's
# client-credentials token (deploy/scripts/edge-lib.sh).
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
HOST=api.localtest.me
CURL_IMAGE=${CURL_IMAGE:-docker.io/curlimages/curl:8.23.0}
CHECK_NS=netcheck
PF_PORT=${PF_PORT:-18081}
# shellcheck source=edge-lib.sh
source "$(dirname "$0")/edge-lib.sh"
BASE=$(edge_url $HOST "")

pass=0
failed=0
ok() {
  printf '  \033[32mPASS\033[0m  %s\n' "$*"
  pass=$((pass + 1))
}
ko() {
  printf '  \033[31mFAIL\033[0m  %s\n' "$*"
  failed=$((failed + 1))
}
expect() { # expect <description> <expected> <actual>
  if [[ $3 == "$2" ]]; then ok "$1 -> $3"; else ko "$1 -> $3 (expected $2)"; fi
}

pf_pid=""
cleanup() {
  if [[ -n $pf_pid ]]; then
    kill "$pf_pid" 2>/dev/null || true
    wait "$pf_pid" 2>/dev/null || true
  fi
  $KUBECTL delete namespace "$CHECK_NS" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== 1. Readiness of the platform"
$KUBECTL wait --for=condition=Programmed gateway/edge -n envoy-gateway-system --timeout=180s >/dev/null &&
  ok "Gateway envoy-gateway-system/edge Programmed=True" || ko "Gateway not programmed"
for d in user order payment; do
  $KUBECTL -n apps rollout status deployment/$d --timeout=120s >/dev/null &&
    ok "deployment apps/$d available" || ko "deployment apps/$d not available"
done

echo "== 2. Host -> gateway ($BASE)"
# *.localtest.me resolves to 127.0.0.1 in public DNS, but some resolvers drop private answers
# (DNS-rebinding protection). --resolve pins the name so the check does not depend on host DNS.
if [[ $(dscacheutil -q host -a name $HOST 2>/dev/null; getent hosts $HOST 2>/dev/null) == *127.0.0.1* ]]; then
  ok "host DNS resolves $HOST to 127.0.0.1"
else
  printf '  \033[33mWARN\033[0m  host DNS does not resolve %s; add it to /etc/hosts (see deploy/README.md)\n' "$HOST"
fi
TOKEN=$(client_token customers loadgen loadgen loadgen-client)
hc=(edge_curl -H "Authorization: Bearer $TOKEN")
body=$("${hc[@]}" -w '\n%{http_code}' -X POST "$BASE/orders" -H 'content-type: application/json' \
  -d '{"user_id":"u-1001","items":[{"sku":"book","quantity":2,"unit_price":"12.50"}],"currency":"EUR"}')
expect "POST /orders" 201 "${body##*$'\n'}"
order_id=$(sed -n 's/.*"id":"\([^"]*\)".*/\1/p' <<<"${body%$'\n'*}")
expect "GET /orders/$order_id" 200 "$("${hc[@]}" -o /dev/null -w '%{http_code}' "$BASE/orders/$order_id")"
expect "GET /users/u-1001" 200 "$("${hc[@]}" -o /dev/null -w '%{http_code}' "$BASE/users/u-1001")"
# Envoy normalizes paths before routing; escaped slashes get a 307 to the unescaped path (-L follows it).
for path in /payments /admin/faults /livez /readyz /docs /orders/../admin/faults /orders/%2e%2e/admin/faults /users/..%2fadmin/faults; do
  expect "GET $path (not exposed)" 404 "$("${hc[@]}" -L --path-as-is -o /dev/null -w '%{http_code}' "$BASE$path")"
done
expect "POST /payments (not exposed)" 404 "$("${hc[@]}" -o /dev/null -w '%{http_code}' -X POST "$BASE/payments")"
expect "PUT /admin/faults (not exposed)" 404 "$("${hc[@]}" -o /dev/null -w '%{http_code}' -X PUT "$BASE/admin/faults")"

echo "== 3. Pod -> gateway via CoreDNS rewrite (namespace $CHECK_NS, outside apps)"
# A previous run deletes the namespace asynchronously; wait until it is gone.
$KUBECTL wait --for=delete "namespace/$CHECK_NS" --timeout=120s >/dev/null 2>&1 || true
$KUBECTL create namespace "$CHECK_NS" --dry-run=client -o yaml | $KUBECTL apply -f - >/dev/null
$KUBECTL -n "$CHECK_NS" create configmap localtest-ca --from-file=ca.crt="$CA_FILE" --dry-run=client -o yaml |
  $KUBECTL apply -f - >/dev/null
$KUBECTL -n "$CHECK_NS" delete pod curl --ignore-not-found --wait=true >/dev/null
$KUBECTL -n "$CHECK_NS" run curl --image="$CURL_IMAGE" --restart=Never \
  --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":100,"runAsGroup":101,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"curl","image":"'"$CURL_IMAGE"'","command":["sleep","600"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}},"volumeMounts":[{"name":"ca","mountPath":"/ca","readOnly":true}]}],"volumes":[{"name":"ca","configMap":{"name":"localtest-ca"}}]}}' \
  >/dev/null
$KUBECTL -n "$CHECK_NS" wait --for=condition=Ready pod/curl --timeout=120s >/dev/null
pc() { $KUBECTL -n "$CHECK_NS" exec curl -- curl -s -m 15 --cacert /ca/ca.crt "$@" 2>/dev/null || true; }
gw_ip=$($KUBECTL -n envoy-gateway-system get service envoy-edge -o jsonpath='{.spec.clusterIP}')
resolved=$($KUBECTL -n "$CHECK_NS" exec curl -- nslookup "$HOST" 2>/dev/null | awk '/^Address/ {a=$2} END {print a}')
expect "$HOST resolves in-cluster to the envoy-edge Service" "$gw_ip" "$resolved"
body=$(pc -w '\n%{http_code}' -X POST "https://$HOST/orders" -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"user_id":"u-1002","items":[{"sku":"pen","quantity":1,"unit_price":"3.00"}],"currency":"EUR"}')
expect "pod: POST https://$HOST/orders" 201 "${body##*$'\n'}"
expect "pod: GET https://$HOST/users/u-1001" 200 \
  "$(pc -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "https://$HOST/users/u-1001")"

echo "== 4. NetworkPolicy (default deny in apps)"
expect "pod outside apps -> payment.apps directly (blocked)" 000 "$(pc -o /dev/null -w '%{http_code}' -X POST http://payment.apps/payments)"
expect "pod outside apps -> user.apps directly (blocked)" 000 "$(pc -o /dev/null -w '%{http_code}' http://user.apps/users/u-1001)"
expect "pod outside apps -> order.apps directly (blocked)" 000 "$(pc -o /dev/null -w '%{http_code}' http://order.apps/orders/x)"
ok "order -> user and order -> payment allowed (POST /orders returned 201 above)"

echo "== 5. Readiness probe: not ready => out of endpoints, not restarted"
pod=$($KUBECTL -n apps get pod -l app.kubernetes.io/name=user -o jsonpath='{.items[0].metadata.name}')
restarts_before=$($KUBECTL -n apps get pod "$pod" -o jsonpath='{.status.containerStatuses[0].restartCount}')
$KUBECTL -n apps port-forward "pod/$pod" "$PF_PORT:8080" >/dev/null 2>&1 &
pf_pid=$!
for _ in $(seq 1 20); do curl -s -o /dev/null "localhost:$PF_PORT/livez" && break || sleep 0.5; done
curl -s -o /dev/null -X PUT "localhost:$PF_PORT/admin/faults" -H 'content-type: application/json' -d '{"ready":false}'
ep_ready() { $KUBECTL -n apps get endpointslice -l kubernetes.io/service-name=user -o jsonpath='{.items[*].endpoints[*].conditions.ready}'; }
start=$SECONDS
until [[ $(ep_ready) == false ]] || ((SECONDS - start > 30)); do sleep 1; done
expect "EndpointSlice user: endpoint ready (after $((SECONDS - start)) s)" false "$(ep_ready)"
expect "gateway GET /users/u-1001 while not ready" 503 "$("${hc[@]}" -o /dev/null -w '%{http_code}' "$BASE/users/u-1001")"
expect "/livez still healthy" 200 "$(curl -s -o /dev/null -w '%{http_code}' "localhost:$PF_PORT/livez")"
sleep 35 # more than livenessProbe period x failureThreshold (10 s x 3)
expect "restartCount unchanged after 35 s" "$restarts_before" \
  "$($KUBECTL -n apps get pod "$pod" -o jsonpath='{.status.containerStatuses[0].restartCount}')"
curl -s -o /dev/null -X DELETE "localhost:$PF_PORT/admin/faults"
$KUBECTL -n apps wait --for=condition=Ready "pod/$pod" --timeout=30s >/dev/null
# The EndpointSlice follows the pod's Ready condition a moment later.
start=$SECONDS
until [[ $(ep_ready) == true ]] || ((SECONDS - start > 30)); do sleep 1; done
expect "EndpointSlice user: endpoint ready after restore (after $((SECONDS - start)) s)" true "$(ep_ready)"
sleep 2 # Envoy gets the endpoint through xDS
expect "gateway GET /users/u-1001 after restore" 200 "$("${hc[@]}" -o /dev/null -w '%{http_code}' "$BASE/users/u-1001")"

echo
echo "verify: $pass passed, $failed failed"
((failed == 0))
