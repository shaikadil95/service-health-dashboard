# Runbooks

One runbook per alert. Every alert links here through its `runbook_url` annotation, and every email from
Alertmanager contains that link (rules: [`deploy/charts/alerting/rules`](../../deploy/charts/alerting/rules)).

| Alert | Severity | Goes to | Runbook |
|---|---|---|---|
| `ServiceDown` | critical | on-call | [ServiceDown](ServiceDown.md) |
| `HighErrorRate` | critical | on-call | [HighErrorRate](HighErrorRate.md) |
| `ErrorBudgetBurn` | critical | on-call | [ErrorBudgetBurn](ErrorBudgetBurn.md) |
| `HighLatencyP95` | warning (critical for payment above 1 s) | team (on-call) | [HighLatencyP95](HighLatencyP95.md) |
| `PodNotReady` | warning | team | [PodNotReady](PodNotReady.md) |
| `PodCrashLooping` | warning | team | [PodCrashLooping](PodCrashLooping.md) |
| `TelemetryPipelineDown` | warning | team | [TelemetryPipelineDown](TelemetryPipelineDown.md) |
| `KeycloakDown` | critical | on-call | [KeycloakDown](KeycloakDown.md) |
| `LoginFailureSpike` | warning | team | [LoginFailureSpike](LoginFailureSpike.md) |
| `TokenLatencyHigh` | warning | team | [TokenLatencyHigh](TokenLatencyHigh.md) |
| `Watchdog` | none | heartbeat | [Watchdog](Watchdog.md) |

## Common tools

All commands assume the kind context (`kubectl config use-context kind-shd`, or `--context kind-shd`).

| What | Where |
|---|---|
| Status of each service | https://status.localtest.me |
| Service Detail dashboard | `https://grafana.localtest.me/d/shd-service-detail/service-detail?var-service=<service>` |
| Firing alerts, silences | https://alertmanager.localtest.me |
| PromQL | https://prometheus.localtest.me |
| Alert emails | https://mail.localtest.me |
| Logs and traces | Grafana Explore: Loki `{service_name="<service>"}`, Tempo `{resource.service.name="<service>"}` |

**Fault injection.** The demo services have an internal fault-injection API (`/admin/faults`, never routed through the
gateway). Many demo incidents are injected faults, so check it early and reset it as part of remediation:

```bash
kubectl -n apps port-forward deploy/<service> 18080:8080 &
curl -s localhost:18080/admin/faults                 # current error_rate, latency_ms, ready
curl -s -X DELETE localhost:18080/admin/faults       # back to the defaults
kill %1
```

`scripts/demo.sh reset` resets all three services.

**Silencing.** When you work on an incident, silence the alert in Alertmanager (or use the "Silence this group" link in the
email) with your name and a comment, rather than ignoring repeats.
