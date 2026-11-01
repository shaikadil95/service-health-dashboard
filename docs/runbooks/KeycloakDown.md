# KeycloakDown

**Severity:** critical (pages on-call) · **Fires when:** Prometheus cannot scrape Keycloak's management endpoint, or no
Keycloak pod is ready, for 2 minutes.

## Impact

Nobody can log in: customers cannot sign in to the shop, engineers cannot open the monitoring UIs behind single sign-on
(existing sessions keep working until their tokens expire). New tokens for the k6 load generator and for
service-to-service calls (Order → User/Payment) cannot be issued, so `POST /orders` fails once cached tokens expire.
Grafana's break-glass admin login still works. `LoginFailureSpike` and `TokenLatencyHigh` are muted while this fires.

## Triage

```bash
kubectl -n identity get keycloak,pods,statefulset
kubectl -n identity get keycloak keycloak -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.message}{"\n"}{end}'
kubectl -n identity logs statefulset/keycloak --tail=100
kubectl -n identity logs statefulset/postgres --tail=50
```

```promql
up{namespace="identity"}
kube_statefulset_status_replicas_ready{namespace="identity"}
```

## Common causes

| Evidence | Cause |
|---|---|
| `replicas: 0` / `spec.instances: 0` | Scaled down |
| Keycloak logs `Connection refused` / `FATAL: password authentication failed` | PostgreSQL down or credentials changed |
| `OOMKilled` | Memory limit too low for the JVM |
| Pod ready, target down | NetworkPolicy in `identity` (management port 9000 from Prometheus) |

## Remediation

- Scaled down: `kubectl -n identity patch keycloak keycloak --type merge -p '{"spec":{"instances":1}}'`.
- Database: check the `postgres` StatefulSet and its PVC, then restart Keycloak (`kubectl -n identity delete pod keycloak-0`).
- Keycloak takes 1–2 minutes to start; the alert resolves after the next successful scrape.
