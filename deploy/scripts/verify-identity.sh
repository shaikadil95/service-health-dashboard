#!/usr/bin/env bash
# Automated Phase 6 checks against the running kind cluster (`make verify`, last):
#   1. Identity workloads: Keycloak (operator, CR Ready), PostgreSQL, realm imports done; the
#      *.localtest.me certificate is issued by the mkcert CA.
#   2. TLS and redirects: every host serves HTTPS with the certificate (verified with the mkcert CA);
#      plain HTTP redirects browser hosts to HTTPS and does not serve the API at all.
#   3. Single sign-on (ops realm): without a session the monitoring UIs redirect to Keycloak and
#      fetch() calls get 401; "sre" reaches Prometheus, Alertmanager, Mailpit and the status page
#      with one login; "viewer" is denied (403) on Prometheus, Alertmanager and Mailpit but sees the
#      status page; Grafana's own Keycloak login maps sre/dev/viewer to Admin/Editor/Viewer and the
#      break-glass admin still works.
#   4. API: api.localtest.me rejects missing and invalid tokens with 401 (and those never count as
#      5xx), accepts a client-credentials token; payment is not exposed.
#   5. Customer shop (customers realm): login through the gateway, profile, order placed and listed
#      with no token in the browser; Order -> User/Payment with its own client-credentials token,
#      the customer's subject in their audit logs.
#   6. Identity observability: Keycloak scraped, user event metrics, NetworkPolicies of identity.
# KeycloakDown is exercised by `scripts/demo.sh e` (scales Keycloak to 0).
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
CURL_IMAGE=${CURL_IMAGE:-docker.io/curlimages/curl:8.23.0}
WAIT_SECONDS=${WAIT_SECONDS:-240}
CHECK_NS=netcheck-identity
# shellcheck source=edge-lib.sh
source "$(dirname "$0")/edge-lib.sh"
SCRIPTS=$(cd "$(dirname "$0")" && pwd)
TMP=$(mktemp -d)
PROM_PORT=19290

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
expect() { # <description> <expected> <actual>
  [[ $2 == "$3" ]] && ok "$1 -> $3" || ko "$1 -> $3 (expected $2)"
}
pids=()
cleanup() {
  for pid in "${pids[@]+"${pids[@]}"}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$TMP"
  $KUBECTL delete namespace "$CHECK_NS" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

eventually() { # <description> <command...>: retry until success or WAIT_SECONDS pass
  local desc=$1 out deadline=$((SECONDS + WAIT_SECONDS))
  shift
  while true; do
    if out=$("$@" 2>/dev/null); then
      ok "$desc${out:+ -> $out}"
      return 0
    fi
    if ((SECONDS >= deadline)); then
      ko "$desc${out:+ -> $out}"
      return 0
    fi
    sleep 10
  done
}

code() { edge_curl -o /dev/null -w '%{http_code}' "$@"; }
login_as() { # <user> <url...>: one browser session; prints "<status> <url> <body...>" per URL
  local user=$1
  shift
  OIDC_USERNAME=$user OIDC_PASSWORD=$(realm_password "$user") \
    python3 "$SCRIPTS/oidc-login.py" --cacert "$CA_FILE" "$@"
}
status_of() { awk -v u="$1" '$2 == u {print $1}'; }

echo "== 1. Identity workloads and certificate"
$KUBECTL -n identity wait --for=condition=Ready keycloak/keycloak --timeout=300s >/dev/null 2>&1 &&
  ok "Keycloak CR identity/keycloak Ready" || ko "Keycloak CR not Ready"
$KUBECTL -n identity rollout status statefulset/postgres --timeout=120s >/dev/null 2>&1 &&
  ok "PostgreSQL StatefulSet ready (PVC $($KUBECTL -n identity get pvc data-postgres-0 -o jsonpath='{.status.phase} {.status.capacity.storage}'))" ||
  ko "PostgreSQL not ready"
for realm in customers ops; do
  expect "KeycloakRealmImport realm-$realm" "Done=True HasErrors=False" \
    "$($KUBECTL -n identity get keycloakrealmimport "realm-$realm" -o jsonpath='Done={.status.conditions[?(@.type=="Done")].status} HasErrors={.status.conditions[?(@.type=="HasErrors")].status}')"
done
expect "Certificate envoy-gateway-system/localtest-me Ready" True \
  "$($KUBECTL -n envoy-gateway-system get certificate localtest-me -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
issuer=$(echo | openssl s_client -connect 127.0.0.1:"$HTTPS_PORT" -servername grafana.localtest.me 2>/dev/null |
  openssl x509 -noout -issuer -ext subjectAltName 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')
[[ $issuer == *mkcert* && $issuer == *'*.localtest.me'* ]] && ok "served certificate: $issuer" || ko "served certificate: $issuer"

echo "== 2. HTTPS and redirects"
for host in api grafana prometheus alertmanager mail status shop sso; do
  c=$(code "$(edge_url $host.localtest.me /)")
  [[ $c =~ ^(200|302|401|404)$ ]] && ok "https://$host.localtest.me: TLS verified with the mkcert CA -> $c" ||
    ko "https://$host.localtest.me -> $c"
done
http_port=${GATEWAY_HTTP_PORT:-80}
for host in grafana prometheus status shop sso; do
  expect "http://$host.localtest.me/x -> https" "301 https://$host.localtest.me/x" \
    "$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --resolve "$host.localtest.me:$http_port:127.0.0.1" "http://$host.localtest.me:$http_port/x")"
done
expect "http://api.localtest.me/orders (no plain-HTTP API, no redirect)" 404 \
  "$(curl -s -o /dev/null -w '%{http_code}' --resolve "api.localtest.me:$http_port:127.0.0.1" "http://api.localtest.me:$http_port/orders")"

echo "== 3. Single sign-on (ops realm)"
for host in prometheus alertmanager mail status; do
  expect "https://$host.localtest.me without a session" "302 https://sso.localtest.me/realms/ops/" \
    "$(edge_curl -o /dev/null -w '%{http_code} %{redirect_url}' "$(edge_url $host.localtest.me /)" | cut -c1-40)"
done
expect "fetch() without a session (X-Requested-With) gets 401, not a redirect" 401 \
  "$(code -H 'X-Requested-With: fetch' "$(edge_url status.localtest.me /api/v1/services)")"
P=$(edge_url prometheus.localtest.me '/api/v1/query?query=up')
A=$(edge_url alertmanager.localtest.me /api/v2/status)
M=$(edge_url mail.localtest.me /api/v1/messages)
S=$(edge_url status.localtest.me /api/v1/services)
out=$(login_as sre "$P" "$A" "$M" "$S" || true)
expect "sre, one login: Prometheus, Alertmanager, Mailpit, status page" "200 200 200 200" \
  "$(status_of "$P" <<<"$out") $(status_of "$A" <<<"$out") $(status_of "$M" <<<"$out") $(status_of "$S" <<<"$out")"
out=$(login_as viewer "$P" "$A" "$M" "$S" || true)
expect "viewer: Prometheus, Alertmanager, Mailpit denied (group sre only), status page allowed" "403 403 403 200" \
  "$(status_of "$P" <<<"$out") $(status_of "$A" <<<"$out") $(status_of "$M" <<<"$out") $(status_of "$S" <<<"$out")"
G=$(edge_url grafana.localtest.me /api/user/orgs)
for pair in sre:Admin dev:Editor viewer:Viewer; do
  user=${pair%%:*}
  role=$(login_as "$user" "$(edge_url grafana.localtest.me /login/generic_oauth)" "$G" | awk -v u="$G" '$2 == u' |
    sed -n 's/.*"role":"\([A-Za-z]*\)".*/\1/p')
  expect "Grafana login with Keycloak as $user -> role" "${pair#*:}" "$role"
done
password=$($KUBECTL -n observability get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d)
expect "Grafana break-glass admin (local login) still works" 200 \
  "$(code -u "admin:$password" "$(edge_url grafana.localtest.me /api/user)")"

echo "== 4. API (api.localtest.me, customers realm)"
API=$(edge_url api.localtest.me "")
ORDER='{"user_id":"u-1001","items":[{"sku":"book","quantity":1,"unit_price":"12.50"}],"currency":"EUR"}'
expect "POST /orders without a token" 401 "$(code -X POST "$API/orders" -H 'content-type: application/json' -d "$ORDER")"
expect "GET /users/u-1001 with a forged token" 401 \
  "$(code -H 'Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl' "$API/users/u-1001")"
TOKEN=$(client_token customers loadgen loadgen loadgen-client)
expect "POST /orders with the load generator's client-credentials token" 201 \
  "$(code -X POST "$API/orders" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d "$ORDER")"
expect "POST /payments (internal, not exposed) with a valid token" 404 \
  "$(code -X POST "$API/payments" -H "Authorization: Bearer $TOKEN")"

# Port-forward to Prometheus (operator access) for the metric checks below.
$KUBECTL -n observability port-forward svc/kps-prometheus $PROM_PORT:9090 >/dev/null 2>&1 &
pids+=($!)
for _ in $(seq 1 50); do curl -s -o /dev/null "http://127.0.0.1:$PROM_PORT/-/ready" && break; sleep 0.2; done
promql() { # <query> -> first value or empty
  curl -s "http://127.0.0.1:$PROM_PORT/api/v1/query" --data-urlencode "query=$1" |
    python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else "")'
}
rejected() {
  local v
  v=$(promql 'sum(envoy_http_jwt_authn_denied)')
  [[ -n $v && ${v%.*} -ge 2 ]] && echo "$v requests rejected by the gateway's JWT filter"
}
eventually "401s are counted at the gateway (envoy_http_jwt_authn_denied)" rejected
expect "401/403 never counted as 5xx: HighErrorRate firing" "" \
  "$(promql 'ALERTS{alertname="HighErrorRate", alertstate="firing"}')"

echo "== 5. Customer shop (https://shop.localtest.me)"
SHOP=$(edge_url shop.localtest.me "")
out=$(login_as customer "$SHOP/" "$SHOP/api/me" \
  --post "$SHOP/api/orders" '{"items":[{"sku":"pen","quantity":2,"unit_price":"1.99"}],"currency":"EUR"}' || true)
expect "customer login, then the shop page" 200 "$(status_of "$SHOP/" <<<"$out")"
me=$(awk -v u="$SHOP/api/me" '$2 == u' <<<"$out")
sub=$(sed -n 's/.*"id":"\([^"]*\)".*/\1/p' <<<"$me")
expect "GET /api/me (profile created from the token)" "200 customer@shd.localtest.me" \
  "$(awk '{print $1}' <<<"$me") $(sed -n 's/.*"email":"\([^"]*\)".*/\1/p' <<<"$me")"
posted=$(awk -v u="$SHOP/api/orders" '$2 == "POST" && $3 == u' <<<"$out")
order_id=$(sed -n 's/.*"id":"\([^"]*\)".*/\1/p' <<<"$posted" | head -1)
expect "POST /api/orders: order for the signed-in customer (no user_id, no token in the browser)" "201 $sub" \
  "$(awk '{print $1}' <<<"$posted") $(sed -n 's/.*"user_id":"\([^"]*\)".*/\1/p' <<<"$posted")"
listed=$(login_as customer "$SHOP/api/orders" | awk -v u="$SHOP/api/orders" '$2 == u')
[[ $listed == 200* && $listed == *"$order_id"* ]] && ok "GET /api/orders lists the new order $order_id" ||
  ko "GET /api/orders -> ${listed:0:120}"
audit() {
  $KUBECTL -n apps logs deploy/payment --since=10m | grep -F "\"order.id\": \"$order_id\"" |
    python3 -c '
import json, sys
line = json.loads(sys.stdin.readline())
assert line["oauth.client_id"] == "order-service", line
print("client " + line["oauth.client_id"] + ", end user " + str(line["enduser.id"]))'
}
eventually "payment called with order's client-credentials token, customer in the audit log" audit
[[ -n $sub && $(audit 2>/dev/null) == *"$sub"* ]] && ok "audit enduser.id is the customer's subject" ||
  ko "audit enduser.id is not the customer's subject"

echo "== 6. Identity observability and NetworkPolicy"
expect "Keycloak scraped by Prometheus (up)" 1 "$(promql 'up{namespace="identity", job="keycloak-service"}')"
events() {
  local v
  v=$(promql 'sum(keycloak_user_events_total{event="login"})')
  [[ -n $v ]] && echo "$v logins counted (keycloak_user_events_total)"
}
eventually "Keycloak user event metrics" events
expect "identity alert rules loaded" "KeycloakDown LoginFailureSpike TokenLatencyHigh" \
  "$(curl -s "http://127.0.0.1:$PROM_PORT/api/v1/rules" | python3 -c '
import json, sys
g = [x for x in json.load(sys.stdin)["data"]["groups"] if x["name"] == "shd-identity.alerts"]
print(" ".join(r["name"] for r in g[0]["rules"]) if g else "")')"
$KUBECTL create namespace "$CHECK_NS" --dry-run=client -o yaml | $KUBECTL apply -f - >/dev/null
$KUBECTL -n "$CHECK_NS" run curl --image="$CURL_IMAGE" --restart=Never \
  --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":100,"runAsGroup":101,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"curl","image":"'"$CURL_IMAGE"'","command":["sleep","300"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}' \
  >/dev/null
$KUBECTL -n "$CHECK_NS" wait --for=condition=Ready pod/curl --timeout=120s >/dev/null
pc() { $KUBECTL -n "$CHECK_NS" exec curl -- curl -s -m 5 -o /dev/null -w '%{http_code}' "$@" 2>/dev/null || true; }
expect "pod outside identity -> Keycloak HTTP port directly (blocked: forwarded headers are trusted)" 000 \
  "$(pc http://keycloak-service.identity:8080/realms/ops)"
# A TCP connect to PostgreSQL: time_connect stays 0 when the connection is refused or dropped.
expect "pod outside identity -> PostgreSQL 5432 (blocked)" "0.000000" \
  "$($KUBECTL -n "$CHECK_NS" exec curl -- curl -s -m 3 -o /dev/null -w '%{time_connect}' telnet://postgres.identity:5432 2>/dev/null || true)"

printf '\nverify-identity: %d passed, %d failed\n' "$pass" "$failed"
((failed == 0))
