#!/usr/bin/env bash
# Automated Phase 3 checks against the running kind cluster (`make verify`, after verify.sh).
#   1. Observability workloads are ready and the PVCs are bound with the planned sizes.
#   2. Prometheus: no target down; OTLP RED + business metrics per service; Tempo service graph;
#      blackbox probe_success = 1; Envoy and Collector metrics; exemplars.
#   3. Edge: the UIs are routed, Prometheus write/lifecycle endpoints are not.
#   4. Grafana: login with the generated password, no anonymous access, datasources healthy.
#   5. Loki: JSON logs of every service with trace_id; Tempo: the trace of one of those log lines
#      spans gateway -> order -> user and order -> payment.
# Queries go through the edge Gateway (https://<ui>.localtest.me), pinned to 127.0.0.1 with --resolve.
# Since Phase 6 Prometheus and Alertmanager require single sign-on: the script logs in once as the
# demo user "sre" (deploy/scripts/oidc-login.py) and reuses the gateway's session cookies. Grafana
# is queried with its break-glass admin (basic auth).
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
# shellcheck source=lib/edge.sh
source "$(dirname "$0")/lib/edge.sh"
JAR=$(mktemp)
trap 'rm -f "$JAR"' EXIT
# Telemetry needs a few export/scrape cycles after a fresh deploy (k6 runs continuously).
WAIT_SECONDS=${WAIT_SECONDS:-240}
SERVICES=(user order payment)

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

ui() { # ui <host> <curl args...>: through the gateway, with the SSO session of "sre"
  shift
  sso_curl "$JAR" "$@"
}
url() { edge_url "$1" "$2"; }

# promql <query> -> one line per series: "<label=value,...> <value>"
promql() {
  ui prometheus.localtest.me "$(url prometheus.localtest.me /api/v1/query)" --data-urlencode "query=$1" |
    python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)["data"]["result"]
except Exception:
    sys.exit(0)
for r in data:
    labels = ",".join(f"{k}={v}" for k, v in sorted(r["metric"].items()))
    print(labels, r["value"][1])'
}

# eventually <description> <command...>: retries until the command succeeds or WAIT_SECONDS pass.
eventually() {
  local desc=$1
  shift
  local deadline=$((SECONDS + WAIT_SECONDS)) out
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

# Check helpers (exit 0 = pass; stdout = evidence).
series_for_all_services() { # <metric selector> <label>
  local got
  got=$(promql "count by ($2) ($1)" | sed -n "s/.*$2=\([^, ]*\).*/\1/p" | sort | tr '\n' ' ')
  echo "$got"
  for s in "${SERVICES[@]}"; do [[ " $got" == *" $s "* ]] || return 1; done
}
edges_present() {
  local got
  got=$(promql 'sum by (client, server) (traces_service_graph_request_total)' |
    sed -n 's/^client=\([^,]*\),server=\([^ ]*\) .*/\1->\2/p' | sort | tr '\n' ' ')
  echo "$got"
  for e in gateway-\>order order-\>user order-\>payment; do [[ " $got" == *" $e "* ]] || return 1; done
}
probes_up() {
  local got
  got=$(promql 'probe_success{job="blackbox-readyz"}' | sed -n 's/.*service=\([^, ]*\).* \(.*\)$/\1=\2/p' | sort | tr '\n' ' ')
  echo "$got"
  for s in "${SERVICES[@]}"; do [[ " $got" == *" $s=1 "* ]] || return 1; done
}
no_down_targets() {
  local res
  res=$(ui prometheus.localtest.me "$(url prometheus.localtest.me '/api/v1/targets?state=active')" |
    python3 -c '
import json, sys
t = json.load(sys.stdin)["data"]["activeTargets"]
down = sorted({x["labels"].get("job", "?") for x in t if x["health"] != "up"})
print(f"{len(t)} targets, down: {down if down else 0}")
sys.exit(1 if down or not t else 0)')
  echo "$res"
  [[ $res == *"down: 0" ]]
}
nonempty() { # <promql>
  local got
  got=$(promql "$1")
  [[ -n $got ]] || return 1
  echo "${got##* }"
}
exemplars() {
  local now
  now=$(date +%s)
  ui prometheus.localtest.me "$(url prometheus.localtest.me /api/v1/query_exemplars)" \
    --data-urlencode 'query=http_server_request_duration_seconds_bucket{job="order"}' \
    --data-urlencode "start=$((now - 600))" --data-urlencode "end=$now" |
    python3 -c '
import json, sys
d = json.load(sys.stdin)["data"]
n = sum(len(s["exemplars"]) for s in d)
print(f"{n} exemplars with trace_id" if n else "none")
sys.exit(0 if n else 1)'
}

echo "== 1. Observability workloads and storage"
for ns in observability loadgen; do
  if $KUBECTL -n "$ns" wait --for=condition=Ready pod --all --timeout=300s >/dev/null 2>&1; then
    ok "all pods Ready in $ns ($($KUBECTL -n "$ns" get pods --no-headers | wc -l | tr -d ' '))"
  else
    ko "pods not Ready in $ns: $($KUBECTL -n "$ns" get pods --no-headers | grep -v Running | tr '\n' ';')"
  fi
done
$KUBECTL -n observability rollout status daemonset/otel-collector-agent --timeout=120s >/dev/null &&
  ok "OTel Collector DaemonSet: one agent per node" || ko "OTel Collector DaemonSet not rolled out"
for pvc in prometheus-kps-prometheus-db-prometheus-kps-prometheus-0=2Gi \
  alertmanager-kps-alertmanager-db-alertmanager-kps-alertmanager-0=1Gi storage-loki-0=2Gi storage-tempo-0=2Gi; do
  name=${pvc%%=*}
  want=${pvc#*=}
  got=$($KUBECTL -n observability get pvc "$name" -o jsonpath='{.status.phase} {.status.capacity.storage}' 2>/dev/null || true)
  [[ $got == "Bound $want" ]] && ok "PVC $name -> $got" || ko "PVC $name -> ${got:-missing} (expected Bound $want)"
done

echo "== 2. Prometheus (via https://prometheus.localtest.me, signed in as sre)"
if sso_login sre "$(url prometheus.localtest.me /-/ready)" "$JAR"; then
  ok "single sign-on as sre (ops realm) for prometheus/alertmanager.localtest.me"
else
  ko "single sign-on as sre failed"
fi
eventually "no scrape target down" no_down_targets
eventually "OTLP http_server_request_duration_seconds for user/order/payment" \
  series_for_all_services http_server_request_duration_seconds_count job
eventually "business metric orders_created_total" nonempty 'sum(orders_created_total)'
eventually "business metric payments_processed_total" nonempty 'sum(payments_processed_total)'
eventually "Tempo service graph edges (traces_service_graph_request_total)" edges_present
eventually "Tempo span metrics (traces_spanmetrics_calls_total)" nonempty 'sum(traces_spanmetrics_calls_total)'
eventually "blackbox probe_success for user/order/payment" probes_up
eventually "Envoy gateway metrics (envoy_cluster_upstream_rq_total)" nonempty 'sum(envoy_cluster_upstream_rq_total)'
eventually "Collector metrics: spans accepted" nonempty 'sum(otelcol_receiver_accepted_spans)'
eventually "Collector metrics: log records accepted" nonempty 'sum(otelcol_receiver_accepted_log_records)'
eventually "Collector metrics: metric points accepted" nonempty 'sum(otelcol_receiver_accepted_metric_points)'
# Informational: exports retried while a backend was still starting count here too.
failed_exports=$(promql 'sum(otelcol_exporter_send_failed_spans or otelcol_exporter_send_failed_metric_points or otelcol_exporter_send_failed_log_records)')
failed_exports=${failed_exports##* }
printf '  INFO  Collector export failures since start -> %s\n' "${failed_exports:-0}"
eventually "exemplars on http_server_request_duration_seconds" exemplars

echo "== 3. Edge routes for the UIs"
for host in grafana.localtest.me/api/health prometheus.localtest.me/-/ready alertmanager.localtest.me/-/ready; do
  code=$(ui "${host%%/*}" -o /dev/null -w '%{http_code}' "$(url "${host%%/*}" "/${host#*/}")")
  [[ $code == 200 ]] && ok "GET https://$host -> $code" || ko "GET https://$host -> $code"
done
for path in /api/v1/write /api/v1/otlp/v1/metrics /-/reload /-/quit; do
  code=$(ui prometheus.localtest.me -o /dev/null -w '%{http_code}' -X POST "$(url prometheus.localtest.me "$path")")
  [[ $code == 403 ]] && ok "POST prometheus.localtest.me$path (blocked at the edge) -> $code" ||
    ko "POST prometheus.localtest.me$path -> $code (expected 403)"
done

echo "== 4. Grafana (via https://grafana.localtest.me)"
password=$($KUBECTL -n observability get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d)
gf() { edge_curl -u "admin:$password" "$@"; }
code=$(edge_curl -o /dev/null -w '%{http_code}' "$(url grafana.localtest.me /api/datasources)")
[[ $code == 401 ]] && ok "anonymous API access refused -> $code" || ko "anonymous API access -> $code (expected 401)"
code=$(edge_curl -u admin:prom-operator -o /dev/null -w '%{http_code}' "$(url grafana.localtest.me /api/user)")
[[ $code == 401 ]] && ok "chart default password rejected -> $code" || ko "chart default password -> $code (expected 401)"
code=$(gf -o /dev/null -w '%{http_code}' "$(url grafana.localtest.me /api/user)")
[[ $code == 200 ]] && ok "login with the generated admin password -> $code" || ko "login with the generated password -> $code"
for ds in prometheus loki tempo; do
  status=$(gf "$(url grafana.localtest.me "/api/datasources/uid/$ds/health")" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status"))' 2>/dev/null || true)
  [[ $status == OK ]] && ok "datasource $ds health -> $status" || ko "datasource $ds health -> ${status:-error}"
done

echo "== 5. Loki logs and Tempo traces (through Grafana's datasource proxy)"
loki_line() { # <service> [<filter>] [<min age s>] -> "<trace_id> <severity> <message>" of a recent line
  local now
  now=$(date +%s)
  gf -G "$(url grafana.localtest.me /api/datasources/proxy/uid/loki/loki/api/v1/query_range)" \
    --data-urlencode "query={service_name=\"$1\", k8s_namespace_name=\"apps\"} | trace_id != \"\" ${2:-}" \
    --data-urlencode "start=$((now - 600))000000000" --data-urlencode "end=$((now - ${3:-0}))000000000" \
    --data-urlencode "limit=1" |
    python3 -c '
import json, sys
r = json.load(sys.stdin)["data"]["result"]
if not r:
    sys.exit(1)
s = r[0]
print(s["stream"]["trace_id"], s["stream"].get("severity_text", "?"), repr(s["values"][0][1]))'
}
for svc in "${SERVICES[@]}"; do
  eventually "Loki: $svc JSON log line with trace_id, severity, message" loki_line "$svc"
done

trace_spans() { # <trace_id> -> "service:kind:name<-parent_service" per span
  gf "$(url grafana.localtest.me "/api/datasources/proxy/uid/tempo/api/v2/traces/$1")" | python3 -c '
import json, sys
spans = {}
for rs in json.load(sys.stdin)["trace"]["resourceSpans"]:
    svc = next(a["value"]["stringValue"] for a in rs["resource"]["attributes"] if a["key"] == "service.name")
    for ss in rs["scopeSpans"]:
        for s in ss["spans"]:
            spans[s["spanId"]] = (svc, s.get("kind", "").replace("SPAN_KIND_", ""), s["name"], s.get("parentSpanId"))
edges = set()
for svc, kind, name, parent in spans.values():
    if parent in spans and spans[parent][0] != svc:
        edges.add(f"{spans[parent][0]}->{svc}")
print(len(spans), "spans, edges:", " ".join(sorted(edges)))
need = {"gateway->order", "order->user", "order->payment"}
sys.exit(0 if need <= edges else 1)'
}
order_trace() {
  local id
  # A line at least 30 s old: by then every service has exported its spans (batching) and Tempo
  # returns the complete trace.
  id=$(loki_line order '| http_route="/orders" | http_request_method="POST"' 30 | cut -d' ' -f1) || return 1
  echo -n "trace_id $id from Loki: "
  trace_spans "$id"
}
eventually "Tempo: POST /orders trace (trace_id from a Loki line) spans gateway -> order -> user/payment" order_trace

echo
echo "verify-telemetry: $pass passed, $failed failed"
[[ $failed -eq 0 ]]
