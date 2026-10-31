# TelemetryPipelineDown

**Severity:** warning (team mailbox) · **Fires when** (label `reason`):

| `reason` | Condition |
|---|---|
| `target-down` | Prometheus cannot scrape the Collector agent, Loki, Tempo or the blackbox exporter, for 5 minutes |
| `no-collector` | No Collector agent is up at all, for 5 minutes |
| `export-failures` | A Collector exporter keeps failing to send data (after retries), for 10 minutes |

## Impact

Telemetry is missing: application metrics (and with them `HighErrorRate`/`HighLatencyP95` and the status page metrics),
logs, traces, or probe results (`ServiceDown`). The system can look healthier than it is. Treat it as urgent during an
incident.

## Triage

```bash
kubectl -n observability get pods
kubectl -n observability logs ds/otel-collector-agent --tail=50     # exporter errors name the failing backend
```

```promql
up{namespace="observability"} == 0
sum by (exporter) (rate({__name__=~"otelcol_exporter_send_failed_.*"}[5m]))
sum by (receiver) (rate(otelcol_receiver_refused_spans[5m]))           # memory_limiter refusing data
```

## Common causes

| Evidence | Cause |
|---|---|
| A backend pod not ready / restarting | Loki, Tempo or Prometheus down (OOM, full volume) |
| Exporter errors `connection refused` / `context deadline exceeded` | Backend unreachable: NetworkPolicy in `observability`, Service renamed |
| `refused` counters rising | The Collector hits its memory limit (`memory_limiter`) |

## Remediation

- Restart or fix the failing backend; check its PVC (`kubectl -n observability get pvc`).
- Collector memory: raise `resources.limits.memory` in `deploy/values/otel-collector.yaml`.
- After a NetworkPolicy change: compare with `deploy/charts/namespace-baseline` and `charts/observability-config`.
