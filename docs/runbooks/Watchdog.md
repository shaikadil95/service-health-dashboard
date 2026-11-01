# Watchdog

**Severity:** none · **Always firing.** It is the alerting pipeline's heartbeat (a dead man's switch).

Alertmanager routes it to the `heartbeat` receiver every minute. Locally that receiver does nothing; in production it
is a webhook to an external service (for example healthchecks.io or a PagerDuty heartbeat) that pages when the heartbeats
**stop**, because then Prometheus, its rule evaluation, the path to Alertmanager, or Alertmanager itself is broken, and no
other alert could be delivered either.

## If the heartbeat stops

1. Is `Watchdog` listed at https://alertmanager.localtest.me? If not: is Prometheus up and evaluating rules
   (`prometheus_rule_evaluation_failures_total`, `prometheus_notifications_dropped_total`)?
2. Prometheus → Alertmanager: `prometheus_notifications_alertmanagers_discovered`, Prometheus logs.
3. Alertmanager → receiver: `alertmanager_notifications_failed_total`, Alertmanager logs.

Never silence this alert.
