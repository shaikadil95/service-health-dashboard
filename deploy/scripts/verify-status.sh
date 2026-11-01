#!/usr/bin/env bash
# Automated Phase 4 checks against the running kind cluster (`make verify`, after verify-telemetry.sh).
#   1. Status API and status page workloads are available.
#   2. https://status.localtest.me (signed in as the demo user "viewer"): the page (SPA fallback, hashed assets), the documented JSON of
#      /api/v1/services, /services/{name} and /alerts, all three services UP; operational
#      endpoints of the Status API are not routed.
#   3. NetworkPolicy: the Status API and the page are only reachable through the gateway, and the
#      gateway asks for a login first.
#   4. Grafana: both dashboards provisioned, every Prometheus query has data for all three services,
#      the logs panel returns lines.
#   5. Correlations: datasource settings, and links that resolve: exemplar -> trace,
#      log line -> trace, trace -> logs, service map metrics.
# Host requests go through the edge Gateway, pinned to 127.0.0.1 with --resolve (as verify.sh). Since
# Phase 6 the status host requires single sign-on (ops realm): the script logs in once as "viewer"
# and reuses the gateway's session cookies; Grafana is queried with its break-glass admin.
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
# shellcheck source=lib/edge.sh
source "$(dirname "$0")/lib/edge.sh"
JAR=$(mktemp)
CURL_IMAGE=${CURL_IMAGE:-docker.io/curlimages/curl:8.23.0}
WAIT_SECONDS=${WAIT_SECONDS:-240}
CHECK_NS=netcheck-status
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
expect() { # <description> <expected> <actual>
  [[ $2 == "$3" ]] && ok "$1 -> $3" || ko "$1 -> $3 (expected $2)"
}
cleanup() {
  rm -f "$JAR"
  $KUBECTL delete namespace "$CHECK_NS" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

ui() { # ui <host> <curl args...>: through the gateway, with the SSO session
  shift
  edge_curl -b "$JAR" -c "$JAR" "$@"
}
url() { edge_url "$1" "$2"; }
STATUS=status.localtest.me
GRAFANA=grafana.localtest.me

eventually() { # <description> <command...>: retry until success or WAIT_SECONDS pass
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

echo "== 1. Status workloads"
for d in status-api status-web; do
  if $KUBECTL -n apps rollout status "deployment/$d" --timeout=180s >/dev/null 2>&1; then
    ok "deployment apps/$d available"
  else
    ko "deployment apps/$d not available"
  fi
done

echo "== 2. Status page and Status API (https://$STATUS, signed in as viewer)"
if sso_login viewer "$(url $STATUS /)" "$JAR"; then
  ok "single sign-on as viewer (ops realm)"
else
  ko "single sign-on as viewer failed"
fi
page=$(ui $STATUS -w '\n%{http_code} %{content_type}' "$(url $STATUS /)")
expect "GET / (status page)" "200 text/html" "${page##*$'\n'}"
[[ $page == *"<title>Service status</title>"* ]] && ok "index.html is the status page" || ko "index.html title missing"
expect "GET /services/payment (SPA fallback)" "200 text/html" \
  "$(ui $STATUS -o /dev/null -w '%{http_code} %{content_type}' "$(url $STATUS /services/payment)")"
asset=$(sed -n 's/.*src="\(\/assets\/[^"]*\.js\)".*/\1/p' <<<"$page" | head -1)
cache=$(ui $STATUS -o /dev/null -D - "$(url $STATUS "$asset")" | tr -d '\r' | sed -n 's/^[Cc]ache-[Cc]ontrol: //p')
expect "GET $asset (hashed asset, long-lived cache)" "public, max-age=31536000, immutable" "$cache"

services_json() { ui $STATUS -H 'Accept: application/json' "$(url $STATUS /api/v1/services)"; }
# The documented contract (docs/architecture.md section 8 and services/README.md).
contract() {
  services_json | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert set(d) == {"status", "services", "sources", "thresholds", "links", "generated_at"}, set(d)
assert d["sources"]["prometheus"]["status"] == "ok" and d["sources"]["alertmanager"]["status"] == "ok", d["sources"]
names = [s["name"] for s in d["services"]]
assert names == ["user", "order", "payment"], names
for s in d["services"]:
    assert set(s) == {"name", "status", "reasons", "metrics", "series", "alerts", "links", "updated_at"}, set(s)
    m = s["metrics"]
    assert set(m) == {"probe_success", "ready_replicas", "desired_replicas", "rps", "error_ratio_5m", "latency_p95_ms"}
    assert m["probe_success"] is True and m["rps"] and m["rps"] > 0, m
    assert len(s["series"]["rps"]) >= 5, "sparkline series too short"
    assert "var-service=" + s["name"] in s["links"]["dashboard"]
print("keys, sources ok, metrics and series for user/order/payment")'
}
all_up() {
  services_json | python3 -c '
import json, sys
d = json.load(sys.stdin)
got = " ".join("%s=%s" % (s["name"], s["status"]) for s in d["services"])
print("overall=%s %s" % (d["status"], got))
sys.exit(0 if d["status"] == "UP" else 1)'
}
eventually "GET /api/v1/services matches the contract" contract
eventually "all three services UP" all_up
expect "GET /api/v1/services/payment" "200 payment" \
  "$(ui $STATUS -w ' %{http_code}' "$(url $STATUS /api/v1/services/payment)" |
    python3 -c 'import json,sys; b,c=sys.stdin.read().rsplit(" ",1); print(c, json.loads(b)["name"])')"
expect "GET /api/v1/services/unknown" 404 "$(ui $STATUS -o /dev/null -w '%{http_code}' "$(url $STATUS /api/v1/services/unknown)")"
expect "GET /api/v1/alerts" "200 ok" \
  "$(ui $STATUS -w ' %{http_code}' "$(url $STATUS /api/v1/alerts)" |
    python3 -c 'import json,sys; b,c=sys.stdin.read().rsplit(" ",1); d=json.loads(b); assert isinstance(d["alerts"], list); print(c, d["source"]["status"])')"
# Only /api is routed to the Status API: its docs and fault injection fall through to the static
# page (HTML), so they never reach the API process. (/livez and /readyz are nginx's own probes.)
for path in /admin/faults /docs /openapi.json /api/../admin/faults; do
  expect "GET $path is not the Status API (served by the page)" "text/html" \
    "$(ui $STATUS --path-as-is -o /dev/null -w '%{content_type}' "$(url $STATUS "$path")")"
done
expect "PUT /admin/faults (not routed to the API)" 405 \
  "$(ui $STATUS -o /dev/null -w '%{http_code}' -X PUT "$(url $STATUS /admin/faults)" -d '{}')"

echo "== 3. NetworkPolicy (namespace $CHECK_NS, outside apps)"
$KUBECTL wait --for=delete "namespace/$CHECK_NS" --timeout=120s >/dev/null 2>&1 || true
$KUBECTL create namespace "$CHECK_NS" --dry-run=client -o yaml | $KUBECTL apply -f - >/dev/null
$KUBECTL -n "$CHECK_NS" create configmap localtest-ca --from-file=ca.crt="$CA_FILE" --dry-run=client -o yaml |
  $KUBECTL apply -f - >/dev/null
$KUBECTL -n "$CHECK_NS" run curl --image="$CURL_IMAGE" --restart=Never \
  --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":100,"runAsGroup":101,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"curl","image":"'"$CURL_IMAGE"'","command":["sleep","600"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}},"volumeMounts":[{"name":"ca","mountPath":"/ca","readOnly":true}]}],"volumes":[{"name":"ca","configMap":{"name":"localtest-ca"}}]}}' \
  >/dev/null
$KUBECTL -n "$CHECK_NS" wait --for=condition=Ready pod/curl --timeout=120s >/dev/null
pc() { $KUBECTL -n "$CHECK_NS" exec curl -- curl -s -m 5 --cacert /ca/ca.crt "$@" 2>/dev/null || true; }
expect "pod outside apps -> status-api.apps directly (blocked)" 000 "$(pc -o /dev/null -w '%{http_code}' http://status-api.apps/api/v1/services)"
expect "pod outside apps -> status-web.apps directly (blocked)" 000 "$(pc -o /dev/null -w '%{http_code}' http://status-web.apps/)"
expect "pod: GET https://$STATUS/api/v1/services via the gateway, no session (login first)" \
  "302 https://sso.localtest.me/realms/ops/" \
  "$(pc -o /dev/null -w '%{http_code} %{redirect_url}' "https://$STATUS/api/v1/services" | cut -c1-40)"
ok "status-api -> Prometheus 9090 and Alertmanager 9093 allowed (both sources ok above)"

echo "== 4. Grafana dashboards (via https://$GRAFANA)"
password=$($KUBECTL -n observability get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d)
gf() { edge_curl -u "admin:$password" "$@"; }
export GF_URL GF_AUTH CA_FILE
GF_URL=$(url $GRAFANA "")
GF_AUTH="admin:$password"
# grafana_py <script>: Python with a small client for Grafana's API (datasource queries via /api/ds/query).
grafana_py() {
  python3 - "$@" <<PY
import base64, json, os, socket, ssl, sys, time, urllib.request
BASE, AUTH = os.environ["GF_URL"], base64.b64encode(os.environ["GF_AUTH"].encode()).decode()
# Pin *.localtest.me to the gateway on 127.0.0.1 (like curl --resolve) and trust the mkcert CA.
_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda host, *a, **k: _getaddrinfo(
    "127.0.0.1" if str(host).endswith(".localtest.me") else host, *a, **k)
CTX = ssl.create_default_context(cafile=os.environ["CA_FILE"])
def call(path, body=None):
    req = urllib.request.Request(BASE + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Basic " + AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
        return json.load(r)
def ds_query(queries, frm="now-15m", to="now"):
    return call("/api/ds/query", {"queries": queries, "from": frm, "to": to})["results"]
def frames(result):
    return result.get("frames", [])
def labels(frame):
    return [f.get("labels") or {} for f in frame["schema"]["fields"] if f.get("type") == "number"]
$(cat)
PY
}
dashboards() {
  grafana_py <<'PY'
found = {d["uid"]: d["title"] for d in call("/api/search?type=dash-db&tag=service-health-dashboard")}
for uid in ("shd-overview", "shd-service-detail"):
    panels = call(f"/api/dashboards/uid/{uid}")["dashboard"]["panels"]
    assert len(panels) <= 8, (uid, len(panels))
    found[uid] += f" ({len(panels)} panels)"
assert len(found) == 2, found
print("; ".join(found.values()))
PY
}
eventually "dashboards provisioned (sidecar): Service Health Overview, Service Detail" dashboards

overview_data() {
  grafana_py <<'PY'
d = call("/api/dashboards/uid/shd-overview")["dashboard"]
out = []
for p in d["panels"]:
    for t in p["targets"]:
        if p["type"] == "table" or p["id"] >= 6:
            continue  # firing alerts: empty while healthy; identity panels: checked in verify-identity.sh
        q = {"refId": "A", "datasource": t["datasource"], "expr": t["expr"], "instant": t.get("instant", False),
             "range": t.get("range", True), "intervalMs": 15000, "maxDataPoints": 100}
        res = ds_query([q])["A"]
        seen = {l.get("service") or l.get("service_name") for f in frames(res) for l in labels(f)}
        missing = {"user", "order", "payment"} - seen
        assert not missing and "error" not in res, (p["title"], missing, res.get("error"))
        out.append(p["title"])
print("data for user/order/payment in: " + ", ".join(out))
PY
}
eventually "Overview: every panel has data for all three services" overview_data

detail_data() {
  grafana_py <<'PY'
d = call("/api/dashboards/uid/shd-service-detail")["dashboard"]
summary = []
for svc in ("user", "order", "payment"):
    empty = []
    for p in d["panels"]:
        for t in p["targets"]:
            expr = t["expr"].replace("$service", svc)
            if t["datasource"]["type"] == "loki":
                q = {"refId": "A", "datasource": t["datasource"], "expr": expr, "queryType": "range", "maxLines": 20}
            else:
                q = {"refId": "A", "datasource": t["datasource"], "expr": expr, "instant": t.get("instant", False),
                     "range": t.get("range", True), "intervalMs": 15000, "maxDataPoints": 100}
            res = ds_query([q])["A"]
            if "error" in res or not any(f["data"]["values"] and f["data"]["values"][0] for f in frames(res)):
                empty.append(f'{p["title"]}/{t["refId"]}')
    assert not empty, (svc, empty)
    summary.append(svc)
print("all panels (incl. logs) have data for " + "/".join(summary))
PY
}
eventually "Service Detail: every panel has data for each service" detail_data

echo "== 5. Correlations"
datasources() {
  grafana_py <<'PY'
prom = call("/api/datasources/uid/prometheus")["jsonData"]
loki = call("/api/datasources/uid/loki")["jsonData"]
tempo = call("/api/datasources/uid/tempo")["jsonData"]
assert prom["exemplarTraceIdDestinations"][0] == {"datasourceUid": "tempo", "name": "trace_id", "urlDisplayLabel": "View trace"}, prom
df = loki["derivedFields"][0]
assert (df["matcherType"], df["matcherRegex"], df["datasourceUid"], df["url"]) == ("label", "trace_id", "tempo", "${__value.raw}"), df
assert tempo["tracesToLogsV2"]["datasourceUid"] == "loki" and "${__trace.traceId}" in tempo["tracesToLogsV2"]["query"], tempo
assert tempo["tracesToMetrics"]["datasourceUid"] == "prometheus" and "$__tags" in tempo["tracesToMetrics"]["queries"][0]["query"]
assert tempo["serviceMap"]["datasourceUid"] == "prometheus" and tempo["nodeGraph"]["enabled"] is True
print("exemplars->tempo, loki trace_id->tempo, tempo->loki/prometheus, service map, node graph")
PY
}
eventually "datasource correlation settings (provisioned, macros not expanded)" datasources

trace_found() { # <trace_id> -> span count
  gf "$(url $GRAFANA "/api/datasources/proxy/uid/tempo/api/v2/traces/$1")" |
    python3 -c 'import json,sys; t=json.load(sys.stdin)["trace"]; n=sum(len(s["spans"]) for r in t["resourceSpans"] for s in r["scopeSpans"]); print(n); sys.exit(0 if n else 1)'
}
exemplar_to_trace() {
  local id
  # Exemplars as Grafana's p95 panel requests them; the newest one older than 30 s, so that all
  # spans of the trace are in Tempo.
  id=$(grafana_py <<'PY'
import time
q = {"refId": "A", "datasource": {"type": "prometheus", "uid": "prometheus"}, "exemplar": True, "range": True,
     "expr": 'histogram_quantile(0.95, sum by (service_name, le) (rate(http_server_request_duration_seconds_bucket{k8s_namespace_name="apps", service_name="order"}[2m])))'}
res = ds_query([q], frm="now-10m")["A"]
best = None
for f in frames(res):
    if f["schema"].get("name") != "exemplar":
        continue
    names = [x["name"] for x in f["schema"]["fields"]]
    cols = dict(zip(names, f["data"]["values"]))
    for ts, tid in zip(cols["Time"], cols["trace_id"]):
        if ts < (time.time() - 30) * 1000 and (best is None or ts > best[0]):
            best = (ts, tid)
assert best, "no exemplar frame"
print(best[1])
PY
  ) || return 1
  echo -n "trace_id $id: "
  echo "$(trace_found "$id") spans in Tempo"
}
eventually "exemplar on the p95 panel -> trace in Tempo" exemplar_to_trace

log_to_trace_to_logs() {
  grafana_py <<'PY'
import time
q = {"refId": "A", "datasource": {"type": "loki", "uid": "loki"}, "queryType": "range", "maxLines": 1,
     "expr": '{service_name="payment", k8s_namespace_name="apps"} | trace_id != ""'}
# A line at least 30 s old: by then every service has exported its spans of that trace.
res = ds_query([q], frm="now-5m", to="now-30s")["A"]
f = frames(res)[0]
names = [x["name"] for x in f["schema"]["fields"]]
lbls = f["data"]["values"][names.index("labels")][0]
tid = lbls["trace_id"]
trace = call(f"/api/datasources/proxy/uid/tempo/api/v2/traces/{tid}")["trace"]
services = sorted({a["value"]["stringValue"] for r in trace["resourceSpans"] for a in r["resource"]["attributes"] if a["key"] == "service.name"})
# Trace -> logs: the query the Tempo datasource builds for an order span (tracesToLogsV2).
q2 = {"refId": "A", "datasource": {"type": "loki", "uid": "loki"}, "queryType": "range", "maxLines": 50,
      "expr": '{service_name="order"} | trace_id="%s"' % tid}
lines = sum(len(f["data"]["values"][0]) for f in frames(ds_query([q2], frm="now-15m")["A"]))
assert lines > 0 and {"order", "payment"} <= set(services), (services, lines)
print(f"trace_id {tid} (payment log line) -> Tempo services {services} -> {lines} order log lines")
PY
}
eventually "log line -> trace (derived field) -> logs of another service (traces to logs)" log_to_trace_to_logs

service_map() {
  grafana_py <<'PY'
q = {"refId": "A", "datasource": {"type": "prometheus", "uid": "prometheus"}, "instant": True, "range": False,
     "expr": "sum by (client, server) (rate(traces_service_graph_request_total[5m]))"}
edges = sorted({f'{l["client"]}->{l["server"]}' for f in frames(ds_query([q])["A"]) for l in labels(f)})
need = {"gateway->order", "order->user", "order->payment"}
assert need <= set(edges), edges
print(" ".join(e for e in edges if e in need))
PY
}
eventually "service map metrics (Tempo service graph) for the Tempo datasource" service_map

echo
echo "verify-status: $pass passed, $failed failed"
[[ $failed -eq 0 ]]
