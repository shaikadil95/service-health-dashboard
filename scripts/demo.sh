#!/usr/bin/env bash
# Failure scenarios for the running kind cluster (`make up` first): break a service, watch the alert
# fire, the email arrive in Mailpit and the status page change, then repair it.
#
#   scripts/demo.sh all        a -> c -> b -> d, then reset and wait for every RESOLVED email (~25 min)
#   scripts/demo.sh a|b|c|d    one scenario, with reset (and its RESOLVED email unless NO_RESOLVE=1)
#   scripts/demo.sh reset      reset fault injection, scale the services back to 1
#   scripts/demo.sh status     status of each service, active alerts, latest emails
#
# Scenarios (docs/architecture.md, section 7):
#   a  payment returns 30 % errors          -> HighErrorRate (critical) for payment, email to on-call
#   b  user answers 800 ms slower           -> HighLatencyP95 (warning) for user, email to the team
#   c  payment scaled to 0                  -> ServiceDown (critical) for payment; in `all` it follows a,
#                                              so payment's HighErrorRate is still active and Alertmanager
#                                              inhibits it (one page for the cause, not its symptoms)
#   d  order readiness switched off         -> PodNotReady (warning) for order (and ServiceDown: its only
#                                              pod receives no traffic)
#
# Everything is reached with `kubectl port-forward` (fault-injection API, Alertmanager, Mailpit, Status
# API): operator access that does not depend on the gateway, DNS, TLS or single sign-on.
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl --context kind-shd}
FIRE_TIMEOUT=${FIRE_TIMEOUT:-600}       # seconds to wait for an alert or an email
RESOLVE_TIMEOUT=${RESOLVE_TIMEOUT:-900} # seconds to wait for RESOLVED emails after the reset
NO_RESOLVE=${NO_RESOLVE:-0}
AM_PORT=19093
MAIL_PORT=18025
STATUS_PORT=18090
SERVICES=(user order payment)

pass=0
failed=0
ok() { printf '  \033[32mPASS\033[0m  %s\n' "$*"; pass=$((pass + 1)); }
ko() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; failed=$((failed + 1)); }
info() { printf '  \033[36m....\033[0m  %s\n' "$*"; }
step() { printf '\n\033[1m== %s\033[0m  (%s)\n' "$*" "$(date +%H:%M:%S)"; }

pf_pids=()
cleanup() {
  for pid in "${pf_pids[@]+"${pf_pids[@]}"}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT

port_forward() { # <namespace> <resource> <local port> <remote port>
  $KUBECTL -n "$1" port-forward "$2" "$3:$4" >/dev/null 2>&1 &
  pf_pids+=($!)
  for _ in $(seq 1 50); do
    curl -s -o /dev/null "http://127.0.0.1:$3/" && return 0
    sleep 0.2
  done
  echo "port-forward to $1/$2 failed" >&2
  exit 1
}

start_port_forwards() {
  port_forward observability svc/kps-alertmanager $AM_PORT 9093
  port_forward observability svc/mailpit $MAIL_PORT 8025
  port_forward apps svc/status-api $STATUS_PORT 80
}

# --- fault injection ------------------------------------------------------------------------------
faults() { # <service> <method> [json]: call /admin/faults of the service's pod
  local svc=$1 method=$2 body=${3:-} port=18180 pid rc=0
  $KUBECTL -n apps port-forward "deploy/$svc" "$port:8080" >/dev/null 2>&1 &
  pid=$!
  for _ in $(seq 1 50); do curl -s -o /dev/null "http://127.0.0.1:$port/livez" && break; sleep 0.2; done
  curl -sf -X "$method" "http://127.0.0.1:$port/admin/faults" -H 'content-type: application/json' \
    ${body:+-d "$body"} >/dev/null || rc=$?
  kill $pid 2>/dev/null || true
  wait $pid 2>/dev/null || true
  return $rc
}

reset_all() {
  for svc in "${SERVICES[@]}"; do
    $KUBECTL -n apps scale "deploy/$svc" --replicas=1 >/dev/null
  done
  for svc in "${SERVICES[@]}"; do
    $KUBECTL -n apps rollout status "deploy/$svc" --timeout=180s >/dev/null
    faults "$svc" DELETE && info "faults of $svc reset" || ko "could not reset the faults of $svc"
  done
}

# --- Alertmanager, Mailpit, Status API --------------------------------------------------------------
# alert_state <alertname> <service> [severity]: "active", "suppressed" or "" (not present)
alert_state() {
  curl -s "http://127.0.0.1:$AM_PORT/api/v2/alerts" | python3 -c '
import json, sys
name, service, severity = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "")
states = [a["status"]["state"] for a in json.load(sys.stdin)
          if a["labels"].get("alertname") == name and a["labels"].get("service") == service
          and (not severity or a["labels"].get("severity") == severity)]
print("active" if "active" in states else (states[0] if states else ""))' "$@"
}

inhibited_by_names() { # <alertname> <service>: names of the alerts that inhibit it
  curl -s "http://127.0.0.1:$AM_PORT/api/v2/alerts" | python3 -c '
import json, sys
alerts = json.load(sys.stdin)
by_fp = {a["fingerprint"]: a["labels"].get("alertname") for a in alerts}
for a in alerts:
    if a["labels"].get("alertname") == sys.argv[1] and a["labels"].get("service") == sys.argv[2]:
        print(",".join(sorted({by_fp.get(fp, fp) for fp in a["status"]["inhibitedBy"]})))
        break' "$1" "$2"
}

# mail_id <subject words> <to>: ID of the newest message whose subject contains all words.
mail_id() {
  curl -s "http://127.0.0.1:$MAIL_PORT/api/v1/messages?limit=200" | python3 -c '
import json, sys
words, to = sys.argv[1].split(), sys.argv[2]
for m in json.load(sys.stdin).get("messages", []):
    if all(w in m["Subject"] for w in words) and any(t["Address"] == to for t in m["To"]):
        print(m["ID"])
        break' "$1" "$2"
}

mail_text() { curl -s "http://127.0.0.1:$MAIL_PORT/api/v1/message/$1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Text"])'; }
mail_subject() { curl -s "http://127.0.0.1:$MAIL_PORT/api/v1/message/$1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Subject"])'; }

service_status() { # <service>: UP / DEGRADED / DOWN / UNKNOWN from the Status API
  curl -s "http://127.0.0.1:$STATUS_PORT/api/v1/services/$1" | python3 -c '
import json, sys
s = json.load(sys.stdin)
print(s["status"], "|", "; ".join(s["reasons"]))'
}

wait_for() { # <timeout> <description> <command...>: retry every 10 s until the command succeeds
  local timeout=$1 desc=$2 start=$SECONDS out=""
  shift 2
  while ((SECONDS - start < timeout)); do
    if out=$("$@" 2>/dev/null) && [[ -n $out ]]; then
      ok "$desc after $((SECONDS - start)) s${out:+ -> $out}"
      return 0
    fi
    sleep 10
  done
  ko "$desc: not within $timeout s${out:+ (last: $out)}"
  return 1
}

firing() { [[ $(alert_state "$@") == active ]] && echo firing; }
inhibited() { # <alertname> <service>: the alert is suppressed by an inhibition rule
  local by
  [[ $(alert_state "$@") == suppressed ]] || return 1
  by=$(inhibited_by_names "$@")
  [[ -n $by ]] && echo "suppressed, inhibited by $by"
}
gone() { [[ -z $(alert_state "$@") ]] && echo resolved; }
status_is() { # <service> <regex>
  local s
  s=$(service_status "$1")
  [[ ${s%% |*} =~ ^($2)$ ]] && echo "$s"
}
email_firing() { # <alertname> <service> <to>: the email exists and links runbook and dashboard
  local id text
  id=$(mail_id "FIRING $1 on $2" "$3")
  [[ -n $id ]] || return 1
  text=$(mail_text "$id")
  [[ $text == *"Runbook: https://github.com/shaikadil95/service-health-dashboard/blob/main/docs/runbooks/$1.md"* &&
    $text == *"Dashboard: https://grafana.localtest.me/"* ]] || return 1
  echo "\"$(mail_subject "$id")\" to $3 (runbook + dashboard links)"
}
email_resolved() { # <alertname> <service> <to>
  local id
  id=$(mail_id "RESOLVED $1 on $2" "$3")
  [[ -n $id ]] && echo "\"$(mail_subject "$id")\" to $3"
}

ONCALL=oncall@shd.localtest.me
TEAM=team@shd.localtest.me

# --- scenarios --------------------------------------------------------------------------------------
scenario_a() {
  step "a) payment returns 30 % errors -> HighErrorRate (critical)"
  faults payment PUT '{"error_rate":0.3}' && info "payment: error_rate=0.3"
  wait_for 300 "status page: payment not UP (5xx above 5 %)" status_is payment 'DEGRADED|DOWN'
  wait_for "$FIRE_TIMEOUT" "HighErrorRate firing for payment" firing HighErrorRate payment
  wait_for 120 "status page: payment DOWN (critical alert)" status_is payment DOWN
  wait_for 180 "email to on-call" email_firing HighErrorRate payment $ONCALL
}

scenario_a_reset() {
  faults payment DELETE && info "payment: faults reset"
}

scenario_c() {
  step "c) payment scaled to 0 -> ServiceDown (critical), symptoms inhibited"
  local had_symptom
  had_symptom=$(alert_state HighErrorRate payment)
  $KUBECTL -n apps scale deploy/payment --replicas=0 >/dev/null && info "payment: replicas=0"
  wait_for "$FIRE_TIMEOUT" "ServiceDown firing for payment" firing ServiceDown payment
  wait_for 60 "status page: payment DOWN" status_is payment DOWN
  wait_for 180 "email to on-call" email_firing ServiceDown payment $ONCALL
  if [[ -n $had_symptom ]]; then
    wait_for 120 "HighErrorRate for payment inhibited by ServiceDown" inhibited HighErrorRate payment
  else
    info "no HighErrorRate for payment was active, inhibition not exercised (run 'all' to chain a -> c)"
  fi
}

scenario_c_reset() {
  $KUBECTL -n apps scale deploy/payment --replicas=1 >/dev/null
  $KUBECTL -n apps rollout status deploy/payment --timeout=180s >/dev/null && info "payment: replicas=1, ready"
}

scenario_b() {
  step "b) user answers 800 ms slower -> HighLatencyP95 (warning)"
  faults user PUT '{"latency_ms":800}' && info "user: latency_ms=800"
  wait_for 300 "status page: user DEGRADED (p95 above 500 ms)" status_is user 'DEGRADED|DOWN'
  wait_for "$FIRE_TIMEOUT" "HighLatencyP95 (warning) firing for user" firing HighLatencyP95 user warning
  wait_for 240 "email to the team" email_firing HighLatencyP95 user $TEAM
}

scenario_b_reset() {
  faults user DELETE && info "user: faults reset"
}

scenario_d() {
  step "d) order readiness off -> PodNotReady (warning)"
  faults order PUT '{"ready":false}' && info "order: ready=false"
  wait_for "$FIRE_TIMEOUT" "PodNotReady firing for order" firing PodNotReady order
  wait_for 60 "status page: order not UP" status_is order 'DEGRADED|DOWN'
  wait_for 240 "email to the team" email_firing PodNotReady order $TEAM
  local restarts
  restarts=$($KUBECTL -n apps get pods -l app.kubernetes.io/name=order -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}')
  [[ $restarts == 0 ]] && ok "order pod not restarted (readiness never restarts) -> restarts=$restarts" ||
    ko "order pod restarted -> restarts=$restarts"
}

scenario_d_reset() {
  faults order DELETE && info "order: faults reset"
}

wait_resolved() { # <alertname> <service> <to>...
  local name=$1 service=$2 to=$3
  wait_for "$RESOLVE_TIMEOUT" "$name for $service resolved" gone "$name" "$service"
  wait_for "$RESOLVE_TIMEOUT" "RESOLVED email for $name on $service" email_resolved "$name" "$service" "$to"
}

summary() {
  printf '\n%d passed, %d failed\n' "$pass" "$failed"
  ((failed == 0))
}

show_status() {
  step "Status API"
  for svc in "${SERVICES[@]}"; do printf '  %-8s %s\n' "$svc" "$(service_status "$svc")"; done
  step "Alertmanager (active and suppressed)"
  curl -s "http://127.0.0.1:$AM_PORT/api/v2/alerts" | python3 -c '
import json, sys
for a in sorted(json.load(sys.stdin), key=lambda a: a["labels"].get("alertname", "")):
    l = a["labels"]
    print("  %-24s %-9s %-20s %s" % (l.get("alertname"), l.get("severity", ""), l.get("service", "-"), a["status"]["state"]))'
  step "Mailpit (latest 10)"
  curl -s "http://127.0.0.1:$MAIL_PORT/api/v1/messages?limit=10" | python3 -c '
import json, sys
for m in json.load(sys.stdin).get("messages", []):
    print("  %s  %-26s %s" % (m["Created"][11:19], m["To"][0]["Address"], m["Subject"]))'
}

main() {
  local what=${1:-}
  case $what in
    a | b | c | d | all | reset | status) ;;
    *) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
  esac
  start_port_forwards
  case $what in
    status) show_status; return ;;
    reset) step "reset"; reset_all; return ;;
  esac

  step "preparation: reset, empty the Mailpit inbox"
  reset_all
  curl -s -X DELETE "http://127.0.0.1:$MAIL_PORT/api/v1/messages" >/dev/null && info "Mailpit inbox emptied"
  wait_for 120 "Watchdog firing (alerting pipeline alive)" firing Watchdog alerting-pipeline

  case $what in
    a)
      scenario_a; scenario_a_reset
      [[ $NO_RESOLVE == 1 ]] || wait_resolved HighErrorRate payment $ONCALL
      ;;
    b)
      scenario_b; scenario_b_reset
      [[ $NO_RESOLVE == 1 ]] || wait_resolved HighLatencyP95 user $TEAM
      ;;
    c)
      scenario_c; scenario_c_reset
      [[ $NO_RESOLVE == 1 ]] || wait_resolved ServiceDown payment $ONCALL
      ;;
    d)
      scenario_d; scenario_d_reset
      [[ $NO_RESOLVE == 1 ]] || wait_resolved PodNotReady order $TEAM
      ;;
    all)
      scenario_a
      scenario_c       # payment still has 30 % errors: HighErrorRate is active when ServiceDown fires
      scenario_c_reset # the new pod starts without faults, which also resets scenario a
      scenario_b
      scenario_b_reset
      scenario_d
      scenario_d_reset
      step "recovery: every alert resolves and a RESOLVED email follows"
      if [[ $NO_RESOLVE != 1 ]]; then
        wait_resolved ServiceDown payment $ONCALL
        wait_resolved PodNotReady order $TEAM
        wait_resolved HighLatencyP95 user $TEAM
        wait_resolved HighErrorRate payment $ONCALL
        for svc in "${SERVICES[@]}"; do wait_for 600 "status page: $svc UP" status_is "$svc" UP; done
      fi
      ;;
  esac
  show_status
  summary
}

main "$@"
