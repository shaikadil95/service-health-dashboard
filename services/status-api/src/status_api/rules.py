"""Status rules, kept free of I/O so that each rule is unit-tested on its own.

Checked together; the service gets the worst status that any rule produces:

* DOWN: the blackbox probe of /readyz fails, or a ``critical`` alert fires for the service.
* DEGRADED: a ``warning`` alert fires, or a threshold is breached: 5xx ratio or p95 latency over
  5 minutes above the alert thresholds, or fewer ready replicas than desired.
* UNKNOWN: the inputs are missing (Prometheus unreachable, or no probe result yet).
* UP: none of the above.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import SEVERITY_ORDER, Alert, Metrics, Status, worst


@dataclass(frozen=True)
class Thresholds:
    error_ratio: float
    latency_p95_ms: float


def _pct(ratio: float) -> str:
    return f"{ratio * 100:.1f}%"


def evaluate(
    metrics: Metrics | None,
    alerts: list[Alert],
    thresholds: Thresholds,
    *,
    prometheus_ok: bool,
    alertmanager_ok: bool,
) -> tuple[Status, list[str]]:
    """Returns the status and human-readable reasons (empty when UP)."""
    findings: list[tuple[Status, str]] = []

    for alert in alerts:
        if alert.severity == "critical":
            findings.append((Status.DOWN, f"critical alert {alert.name} is firing"))
        elif alert.severity == "warning":
            findings.append((Status.DEGRADED, f"warning alert {alert.name} is firing"))

    if not prometheus_ok:
        findings.append((Status.UNKNOWN, "Prometheus is unreachable; metrics may be stale"))
    elif metrics is not None:
        if metrics.probe_success is None:
            findings.append((Status.UNKNOWN, "no readiness probe result"))
        elif not metrics.probe_success:
            findings.append((Status.DOWN, "readiness probe failing (probe_success = 0)"))

        if metrics.error_ratio_5m is not None and metrics.error_ratio_5m > thresholds.error_ratio:
            findings.append(
                (
                    Status.DEGRADED,
                    f"5xx error ratio {_pct(metrics.error_ratio_5m)} > "
                    f"{_pct(thresholds.error_ratio)} (5m)",
                )
            )
        if (
            metrics.latency_p95_ms is not None
            and metrics.latency_p95_ms > thresholds.latency_p95_ms
        ):
            findings.append(
                (
                    Status.DEGRADED,
                    f"p95 latency {metrics.latency_p95_ms:.0f} ms > "
                    f"{thresholds.latency_p95_ms:.0f} ms (5m)",
                )
            )
        if (
            metrics.ready_replicas is not None
            and metrics.desired_replicas is not None
            and metrics.ready_replicas < metrics.desired_replicas
        ):
            findings.append(
                (
                    Status.DEGRADED,
                    f"{metrics.ready_replicas}/{metrics.desired_replicas} replicas ready",
                )
            )

    if not alertmanager_ok:
        # Not a status by itself: the metric rules above still apply.
        findings.append((Status.UP, "Alertmanager is unreachable; alerts not considered"))

    status = worst([s for s, _ in findings]) if findings else Status.UP
    # Worst reasons first.
    order = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    reasons = [reason for _, reason in sorted(findings, key=lambda f: order[f[0]])]
    return status, reasons
