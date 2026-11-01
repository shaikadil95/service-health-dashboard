#!/bin/sh
# Alertmanager configuration tests, run by `make rules-test` inside the alertmanager image (amtool).
# Expects the configuration directory mounted at /etc/alertmanager/config, as in the pod.
set -eu

CONFIG=/etc/alertmanager/config/alertmanager.yaml
failed=0

amtool check-config "$CONFIG" >/dev/null
echo "  PASS  amtool check-config"

# expect <receiver> <label=value>... : the routing tree sends an alert with these labels to <receiver>.
expect() {
  want=$1
  shift
  got=$(amtool config routes test --config.file="$CONFIG" "$@" | tr -d '\n')
  if [ "$got" = "$want" ]; then
    echo "  PASS  route $* -> $got"
  else
    echo "  FAIL  route $* -> $got (want $want)"
    failed=1
  fi
}

expect oncall-email alertname=ServiceDown severity=critical service=payment
expect oncall-email alertname=HighErrorRate severity=critical service=payment
expect oncall-email alertname=HighLatencyP95 severity=critical service=payment
expect oncall-email alertname=KeycloakDown severity=critical service=keycloak
expect team-email alertname=HighLatencyP95 severity=warning service=user
expect team-email alertname=PodNotReady severity=warning service=user
expect team-email alertname=TelemetryPipelineDown severity=warning service=telemetry-pipeline
expect heartbeat alertname=Watchdog severity=none service=alerting-pipeline
expect null alertname=CPUThrottlingHigh severity=info
# No severity at all: still reaches the team instead of being dropped.
expect team-email alertname=SomethingNew

# The email templates render with amtool's example data (one firing and one resolved alert) and
# contain the per-alert sections and the Alertmanager and silence links.
out=$(amtool template render --template.glob='/etc/alertmanager/config/*.tmpl' \
  --template.text='{{ template "shd.email.subject" . }}|{{ template "shd.email.html" . }}|{{ template "shd.email.text" . }}')
case $out in
  *'[FIRING]'*'[RESOLVED]'*'Open in Alertmanager'*'Silence this group'*'Alertmanager: '*'Silence: '*) echo "  PASS  email templates render" ;;
  *) echo "  FAIL  email templates render: $out"; failed=1 ;;
esac

exit $failed
