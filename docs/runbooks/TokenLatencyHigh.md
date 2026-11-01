# TokenLatencyHigh

**Severity:** warning (team mailbox) · **Fires when:** the 95th percentile duration of Keycloak's token endpoint
(`/realms/{realm}/protocol/{protocol}/token`) is above 500 ms over 5 minutes, for 5 minutes.

## Impact

Slow logins and slow token refreshes. Services fetch client-credentials tokens rarely (they are cached), so business
requests are only affected when caches expire; browser logins are directly slower.

## Triage

```promql
histogram_quantile(0.95, sum by (le) (rate(http_server_requests_seconds_bucket{namespace="identity", uri=~".*/token"}[5m])))
sum by (uri) (rate(http_server_requests_seconds_count{namespace="identity"}[5m]))     # load per endpoint
rate(container_cpu_cfs_throttled_periods_total{namespace="identity"}[5m])
jvm_gc_pause_seconds_max{namespace="identity"}
```

Traces of Keycloak (Tempo, `{resource.service.name="keycloak"}`) show whether the time is spent in the database (JDBC
spans) or in password hashing.

## Common causes

| Evidence | Cause |
|---|---|
| CPU throttling | Password hashing is CPU-bound; the CPU limit is too low for the login rate |
| Long JDBC spans | PostgreSQL slow (disk, connections) |
| Long GC pauses | Heap too small |

## Remediation

Raise Keycloak's CPU or memory (`deploy/charts/identity/values.yaml`), or reduce the login rate (load generator). The
alert resolves about 5 minutes after latency is normal again.
