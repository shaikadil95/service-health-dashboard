# ServiceDown

**Severity:** critical (pages on-call) · **Fires when:** the blackbox probe of `http://<service>.apps.svc.cluster.local/readyz`
has failed for more than 1 minute (`probe_success == 0`).

## Impact

No ready pod answers behind the service's Kubernetes Service. Every request to the service fails; for `payment` or `user`
this also breaks `POST /orders` (Order answers 503). Alertmanager mutes `HighErrorRate`, `HighLatencyP95` and
`ErrorBudgetBurn` for the same service while this alert fires: they are symptoms of the same problem.

## Triage

1. Is anything running?
   ```bash
   kubectl -n apps get deploy,pods -l app.kubernetes.io/name=<service> -o wide
   kubectl -n apps get endpointslice -l kubernetes.io/service-name=<service> -o jsonpath='{.items[*].endpoints[*].conditions}'
   ```
2. PromQL:
   ```promql
   probe_success{job="blackbox-readyz", service="<service>"}            # 0 = failing
   probe_http_status_code{job="blackbox-readyz", service="<service>"}   # 503 = not ready, 0 = no connection
   kube_deployment_spec_replicas{namespace="apps", deployment="<service>"}
   kube_deployment_status_replicas_ready{namespace="apps", deployment="<service>"}
   ```
3. Events and logs: `kubectl -n apps describe pod -l app.kubernetes.io/name=<service>`,
   `kubectl -n apps logs deploy/<service> --tail=50`, or Loki `{service_name="<service>"} | severity_text="ERROR"`.

## Common causes

| Evidence | Cause |
|---|---|
| `spec.replicas: 0` | Scaled to zero (by mistake, or the demo scenario) |
| Pods `Running` but `READY 0/1`, `probe_http_status_code` 503 | Readiness fails: fault injection `ready=false`, or the pod is draining |
| `CrashLoopBackOff`, `PodCrashLooping` firing | The process exits at start (configuration, image) |
| `Pending` | Not enough CPU/memory on the node, or an image that cannot be pulled |
| Probe fails, pods ready | The blackbox exporter cannot reach the pod: NetworkPolicy changed (ingress from `observability`) |

## Remediation

- Scaled down: `kubectl -n apps scale deploy/<service> --replicas=1`.
- Fault injection: reset it (`curl -X DELETE …/admin/faults`, see [Common tools](README.md#common-tools)).
- Bad rollout: `kubectl -n apps rollout undo deploy/<service>`.
- The alert resolves about 1 minute after the probe succeeds again; a "RESOLVED" email follows.
