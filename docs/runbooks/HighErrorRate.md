# HighErrorRate

**Severity:** critical (pages on-call) · **Fires when:** more than 5 % of the requests to a service returned a 5xx status
over the last 5 minutes, for 5 minutes (`service:http_server_errors:ratio_rate5m > 0.05`). The status page shows the
service `DOWN` at the same threshold. 4xx answers (including 401/403 from authentication) never count.

## Impact

Customers see failed requests. For `order`, orders are not placed; for `payment` or `user`, Order's `POST /orders`
fails too (502/503), so order's error rate usually follows.

## Triage

1. Which service is the origin? Compare the error ratios; the deepest service in the call chain
   (order → user, payment) that fails is usually the cause:
   ```promql
   service:http_server_errors:ratio_rate5m
   sum by (service_name, http_route, http_response_status_code) (rate(http_server_request_duration_seconds_count{k8s_namespace_name="apps", http_response_status_code=~"5.."}[5m]))
   ```
2. Open the Service Detail dashboard (link in the email): requests by status code, logs with errors.
3. Follow one failing request: in the logs panel pick an `ERROR` line → **View trace**. The trace shows which span failed
   (`error.type`, `event=fault.injected` for injected faults).
4. Order answering 502 with `"upstream": "payment"` means payment returned 5xx; 503 means payment was unreachable; 504 a timeout.

## Common causes

| Evidence | Cause |
|---|---|
| Spans with event `fault.injected`, log `injected fault` | Fault injection (`error_rate > 0`) |
| Order 502/503 with `upstream` set | A dependency (user, payment) fails |
| Errors began with a new ReplicaSet | A bad rollout |
| OOMKilled / restarts | Resource limits too low |

## Remediation

- Fault injection: `curl -X DELETE …/admin/faults` on the service (see [Common tools](README.md#common-tools)).
- Dependency: work on the failing upstream service first; the symptom on order then clears by itself.
- Bad rollout: `kubectl -n apps rollout undo deploy/<service>`.
- The 5-minute window means the alert resolves about 5 minutes after the errors stop.
