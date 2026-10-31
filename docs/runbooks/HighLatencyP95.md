# HighLatencyP95

**Severity:** warning (team mailbox); critical (on-call) for `payment` above 1 s · **Fires when:** the 95th percentile
response time of a service over 5 minutes is above 500 ms (payment: 1 s), for 5 minutes. The status page shows the
service `DEGRADED` (warning) or `DOWN` (critical) at the same thresholds.

## Impact

Slow pages and API calls. Order waits for user and payment, so a slow dependency makes order slow as well.

## Triage

1. Which service is slow, and which route?
   ```promql
   service:http_server_request_duration_seconds:p95_rate5m
   histogram_quantile(0.95, sum by (service_name, http_route, le) (rate(http_server_request_duration_seconds_bucket{k8s_namespace_name="apps"}[5m])))
   ```
2. In the Service Detail dashboard, click an exemplar dot on the p95 panel: it opens a slow trace. The longest span is the
   bottleneck (for order: its client span to user or payment).
3. Check saturation: CPU throttling and memory of the pods
   (`rate(container_cpu_cfs_throttled_periods_total{namespace="apps"}[5m])`).

## Common causes

| Evidence | Cause |
|---|---|
| Fault injection `latency_ms > 0` (`curl …/admin/faults`) | Injected latency |
| Only order slow, its client span to user/payment long | A slow dependency |
| CPU throttling, high request rate | Under-provisioned (limits), load spike |

## Remediation

- Fault injection: `curl -X DELETE …/admin/faults` (see [Common tools](README.md#common-tools)).
- Load or resources: raise CPU limits or replicas (`kubectl -n apps scale deploy/<service> --replicas=2`).
- The alert resolves about 5 minutes after latency is back to normal (5-minute window).
