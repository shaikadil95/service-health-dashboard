# PodCrashLooping

**Severity:** warning (team mailbox) · **Fires when:** a container in `apps` has been in `CrashLoopBackOff` during the
last 5 minutes, for 5 minutes. It replaces kube-prometheus-stack's `KubePodCrashLooping` for the same pod.

## Impact

The container keeps exiting and the kubelet restarts it with growing back-off. While it is down the pod is not ready,
so with one replica `ServiceDown` fires too.

## Triage

```bash
kubectl -n apps get pods -l app.kubernetes.io/name=<service>          # RESTARTS, STATUS CrashLoopBackOff
kubectl -n apps logs <pod> --previous --tail=100                      # output of the crashed container
kubectl -n apps describe pod <pod>                                    # Last State: exit code, OOMKilled, probe failures
```

```promql
increase(kube_pod_container_status_restarts_total{namespace="apps"}[30m])
kube_pod_container_status_last_terminated_reason{namespace="apps"}
```

## Common causes

| Evidence | Cause |
|---|---|
| `OOMKilled` | Memory limit too low or a leak |
| Exit code 1 and a Python traceback | Bad configuration (environment variable) or a bug in a new image |
| Killed after `Liveness probe failed` | The event loop hangs (liveness only checks the process itself) |

## Remediation

- Bad rollout: `kubectl -n apps rollout undo deploy/<service>`.
- OOMKilled: raise `resources.limits.memory` in `deploy/values/<service>.yaml` and `make deploy`.
