# PodNotReady

**Severity:** warning (team mailbox) · **Fires when:** a pod in `apps` has been not ready for more than 2 minutes
(`kube_pod_status_ready{condition="false"}`). It replaces kube-prometheus-stack's `KubePodNotReady` (15 minutes) for the
same pod.

## Impact

A not-ready pod is removed from the Service endpoints and receives no traffic; it is **not** restarted. If it is the only
pod of the service, the service is down and `ServiceDown` (critical) fires as well.

## Triage

```bash
kubectl -n apps get pods -l app.kubernetes.io/name=<service>
kubectl -n apps describe pod <pod>                    # Events: "Readiness probe failed: HTTP probe failed with statuscode: 503"
kubectl -n apps port-forward pod/<pod> 18080:8080 &
curl -s localhost:18080/readyz                         # {"status":"not_ready","reasons":[...]}
```

`/readyz` lists the reasons: `starting`, `draining` (SIGTERM received) or `fault_injected`. Readiness never checks
dependencies, so a downstream outage is not a cause.

## Remediation

- `fault_injected`: `curl -X DELETE localhost:18080/admin/faults`.
- Stuck `starting` or `draining`: delete the pod (`kubectl -n apps delete pod <pod>`); the Deployment replaces it.
- The alert resolves on the next evaluation after the pod is ready again.
