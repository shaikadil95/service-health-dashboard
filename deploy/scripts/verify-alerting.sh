#!/usr/bin/env bash
# Automated Phase 5 checks against the running kind cluster (`make verify`): rules, Alertmanager
# configuration, Mailpit and the observability NetworkPolicies. The failure scenarios themselves
# (alerts firing, emails, inhibition, recovery) are exercised by `scripts/demo.sh all`.
#   1. The project's PrometheusRules are loaded and healthy, no rule evaluation fails.
#   2. Watchdog is firing in Alertmanager; Prometheus has discovered Alertmanager.
#   3. Alertmanager runs the project's configuration (receivers, inhibition), routes to Mailpit.
#   4. Mailpit receives SMTP from Alertmanager (a test alert is posted and its email checked).
#   5. observability: default deny, and only the allowed flows work.
# Prometheus, Alertmanager and Mailpit are reached with kubectl port-forward (operator access that does
# not depend on the gateway or single sign-on).
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
CURL_IMAGE=${CURL_IMAGE:-docker.io/curlimages/curl:8.23.0}
WAIT_SECONDS=${WAIT_SECONDS:-240}
CHECK_NS=netcheck-alerting
PROM_PORT=19190
AM_PORT=19193
MAIL_PORT=19125

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
  $KUBECTL delete namespace "$CHECK_NS" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

port_forward() { # <namespace> <resource> <local> <remote>
  $KUBECTL -n "$1" port-forward "$2" "$3:$4" >/dev/null 2>&1 &
  pids+=($!)
  for _ in $(seq 1 50); do
    curl -s -o /dev/null "http://127.0.0.1:$3/" && return 0
    sleep 0.2
  done
  ko "port-forward to $1/$2"
}

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

port_forward observability svc/kps-prometheus $PROM_PORT 9090
port_forward observability svc/kps-alertmanager $AM_PORT 9093
port_forward observability svc/mailpit $MAIL_PORT 8025
PROM=http://127.0.0.1:$PROM_PORT
AM=http://127.0.0.1:$AM_PORT
MAIL=http://127.0.0.1:$MAIL_PORT

echo "== 1. Alert and recording rules (Prometheus)"
rules_loaded() {
  curl -s "$PROM/api/v1/rules" | python3 -c '
import json, sys
groups = [g for g in json.load(sys.stdin)["data"]["groups"] if g["name"].startswith("shd-")]
alerts = sorted({r["name"] for g in groups for r in g["rules"] if r["type"] == "alerting"})
bad = [r["name"] for g in groups for r in g["rules"] if r.get("health") != "ok"]
want = {"ServiceDown", "HighErrorRate", "HighLatencyP95", "ErrorBudgetBurn", "PodNotReady",
        "PodCrashLooping", "TelemetryPipelineDown", "Watchdog",
        "KeycloakDown", "LoginFailureSpike", "TokenLatencyHigh"}
missing = want - set(alerts)
if missing or bad:
    print("missing", sorted(missing), "unhealthy", bad); sys.exit(1)
print(len(groups), "groups, alerts:", " ".join(alerts))'
}
eventually "project rules loaded and healthy" rules_loaded
expect "rule evaluation failures (last 10 m)" 0 \
  "$(curl -s "$PROM/api/v1/query" --data-urlencode 'query=sum(increase(prometheus_rule_evaluation_failures_total[10m])) or vector(0)' |
    python3 -c 'import json,sys; print(round(float(json.load(sys.stdin)["data"]["result"][0]["value"][1])))')"
recording_has_data() {
  curl -s "$PROM/api/v1/query" --data-urlencode 'query=service:http_server_errors:ratio_rate5m' | python3 -c '
import json, sys
r = sorted(x["metric"]["service"] for x in json.load(sys.stdin)["data"]["result"])
assert r == ["order", "payment", "user"], r
print(" ".join(r))'
}
eventually "recording rule service:http_server_errors:ratio_rate5m has user/order/payment" recording_has_data
pod_service_join() {
  curl -s "$PROM/api/v1/query" --data-urlencode 'query=count by (service) (namespace_pod:shd_service:info)' | python3 -c '
import json, sys
r = sorted(x["metric"]["service"] for x in json.load(sys.stdin)["data"]["result"])
assert {"order", "payment", "user"} <= set(r), r
print(" ".join(r))'
}
eventually "pod -> service label (kube_pod_labels allowlist)" pod_service_join

echo "== 2. Alerting pipeline"
watchdog() {
  curl -s "$AM/api/v2/alerts" | python3 -c '
import json, sys
a = [x for x in json.load(sys.stdin) if x["labels"].get("alertname") == "Watchdog"]
assert a and a[0]["status"]["state"] == "active" and a[0]["labels"].get("service") == "alerting-pipeline"
print("active, receivers", [r["name"] for r in a[0]["receivers"]])'
}
eventually "Watchdog firing in Alertmanager (dead man's switch)" watchdog
expect "Prometheus discovered Alertmanager" 1 \
  "$(curl -s "$PROM/api/v1/alertmanagers" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["data"]["activeAlertmanagers"]))')"

echo "== 3. Alertmanager configuration"
am_config() {
  curl -s "$AM/api/v2/status" | python3 -c '
import json, sys, re
c = json.load(sys.stdin)["config"]["original"]
receivers = re.findall(r"^- name: (\S+)", c, re.M)
assert {"oncall-email", "team-email", "heartbeat"} <= set(receivers), receivers
assert "mailpit.observability.svc:1025" in c
assert "group_by:\n  - alertname\n  - service" in c
assert c.count("source_matchers") >= 5
print("receivers " + " ".join(receivers) + "; group_by [alertname, service]; " + str(c.count("source_matchers")) + " inhibit rules")'
}
eventually "project configuration loaded (configSecret alertmanager-shd)" am_config

echo "== 4. Alertmanager -> Mailpit (SMTP)"
marker="verify-$(date +%s)"
curl -s -X DELETE "$MAIL/api/v1/messages" >/dev/null
starts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
ends=$(date -u -v+3M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '+3 min' +%Y-%m-%dT%H:%M:%SZ)
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$AM/api/v2/alerts" -H 'content-type: application/json' -d "[{
  \"labels\": {\"alertname\": \"VerifyEmailPath\", \"severity\": \"warning\", \"service\": \"$marker\"},
  \"annotations\": {\"summary\": \"make verify: test of the email path\", \"description\": \"Posted by deploy/scripts/verify-alerting.sh.\",
    \"runbook_url\": \"https://github.com/shaikadil95/service-health-dashboard/blob/main/docs/runbooks/README.md\",
    \"dashboard_url\": \"https://grafana.localtest.me/d/shd-overview/service-health-overview\"},
  \"startsAt\": \"$starts\", \"endsAt\": \"$ends\"}]")
expect "POST test alert (severity warning) to Alertmanager" 200 "$code"
test_email() {
  curl -s "$MAIL/api/v1/messages" | python3 -c '
import json, sys
marker = sys.argv[1]
for m in json.load(sys.stdin).get("messages", []):
    if marker in m["Subject"]:
        print(m["To"][0]["Address"], "|", m["Subject"]); sys.exit(0)
sys.exit(1)' "$marker"
}
# group_wait of the warning route is 1 minute.
eventually "email in Mailpit, routed to the team mailbox" test_email

echo "== 5. NetworkPolicy (namespace observability)"
expect "NetworkPolicy default-deny-all in observability" default-deny-all \
  "$($KUBECTL -n observability get networkpolicy default-deny-all -o jsonpath='{.metadata.name}' 2>/dev/null)"
targets_up() {
  curl -s "$PROM/api/v1/targets?state=active" | python3 -c '
import json, sys
t = json.load(sys.stdin)["data"]["activeTargets"]
down = sorted({x["labels"].get("job", "?") for x in t if x["health"] != "up"})
if down: print("down:", down); sys.exit(1)
print(f"{len(t)} targets up")'
}
eventually "every scrape target up under default deny" targets_up
$KUBECTL create namespace "$CHECK_NS" --dry-run=client -o yaml | $KUBECTL apply -f - >/dev/null
$KUBECTL -n "$CHECK_NS" run curl --image="$CURL_IMAGE" --image-pull-policy=IfNotPresent --restart=Never \
  --command -- sleep 300 >/dev/null
$KUBECTL -n "$CHECK_NS" wait --for=condition=Ready pod/curl --timeout=120s >/dev/null
from_pod() { $KUBECTL -n "$CHECK_NS" exec curl -- curl -s -o /dev/null -m 5 -w '%{http_code}' "$1" 2>/dev/null || true; }
for target in kps-prometheus:9090/-/ready kps-alertmanager:9093/-/ready grafana:80/api/health loki:3100/ready \
  tempo:3200/ready mailpit:8025/livez; do
  svc=${target%%:*} rest=${target#*:}
  expect "pod outside observability -> $svc:${rest%%/*} directly (blocked)" 000 \
    "$(from_pod "http://$svc.observability.svc:${rest%%/*}/${rest#*/}")"
done

printf '\nverify-alerting: %d passed, %d failed\n' "$pass" "$failed"
((failed == 0))
