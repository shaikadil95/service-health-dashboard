# LoginFailureSpike

**Severity:** warning (team mailbox) · **Fires when:** more than 30 % of login attempts in a realm failed over the last
5 minutes, with at least a handful of attempts, for 5 minutes (Keycloak user event metrics
`keycloak_user_events_total{event="login"}`).

## Impact

Users cannot log in, or someone is guessing passwords (credential stuffing). Keycloak's brute-force detection locks
accounts temporarily, which can also lock out legitimate users.

## Triage

```promql
sum by (realm, error) (rate(keycloak_user_events_total{event="login", error!=""}[5m]))
sum by (realm) (rate(keycloak_user_events_total{event="login"}[5m]))
```

- `error="invalid_user_credentials"` spread over many users: password guessing; over one user: a forgotten password.
- `error="user_not_found"` in bulk: enumeration attempts.
- Keycloak admin console (`https://sso.localtest.me/admin`), realm → *Events* (if event storage is enabled) and *Sessions*.

## Remediation

- Attack: block the source at the edge (Envoy Gateway `SecurityPolicy` IP allow/deny or rate limiting); keep brute-force
  detection on.
- Misconfiguration (e.g. a client secret rotated without updating the gateway's Secret): fix the Secret; check the
  gateway logs for `invalid_client`.
