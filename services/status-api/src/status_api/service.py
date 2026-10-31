"""Collects Prometheus and Alertmanager data, applies the status rules and caches the result."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .models import (
    Alert,
    AlertsResponse,
    Links,
    Metrics,
    Point,
    Series,
    ServicesResponse,
    ServiceStatus,
    Source,
    Sources,
    worst,
)
from .models import Thresholds as ThresholdsOut
from .queries import build_queries
from .rules import Thresholds, evaluate
from .sources import AlertmanagerClient, PrometheusClient, SourceError

logger = logging.getLogger("status_api")

OVERVIEW_DASHBOARD = "/d/shd-overview/service-health-overview"
DETAIL_DASHBOARD = "/d/shd-service-detail/service-detail"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _PrometheusData:
    metrics: dict[str, Metrics]
    series: dict[str, Series]


@dataclass
class _SourceState:
    error: str | None = None
    last_success_at: datetime | None = None

    def ok(self) -> None:
        self.error = None
        self.last_success_at = _now()

    def failed(self, error: str) -> None:
        self.error = error

    def out(self) -> Source:
        return Source(
            status="unavailable" if self.error else "ok",
            error=self.error,
            last_success_at=self.last_success_at,
        )


def _service_for(labels: dict[str, str], settings: Settings) -> str | None:
    """Which of our services an alert is about.

    Project rules (Phase 5) set ``service``. Generic rules, such as kube-prometheus-stack's
    KubePodNotReady or KubeDeploymentReplicasMismatch, are matched by namespace plus deployment
    or container name.
    """
    for key in ("service", "service_name"):
        if labels.get(key) in settings.services:
            return labels[key]
    if labels.get("namespace") == settings.namespace:
        for key in ("deployment", "container"):
            if labels.get(key) in settings.services:
                return labels[key]
    return None


def _alert(raw: dict[str, Any], settings: Settings) -> Alert | None:
    labels: dict[str, str] = raw.get("labels") or {}
    annotations: dict[str, str] = raw.get("annotations") or {}
    severity = labels.get("severity", "none")
    # Watchdog (dead man's switch) and InfoInhibitor are plumbing, not problems.
    if severity in ("none", "info"):
        return None
    return Alert(
        name=labels.get("alertname", "unknown"),
        service=_service_for(labels, settings),
        severity=severity,
        summary=annotations.get("summary"),
        description=annotations.get("description"),
        runbook_url=annotations.get("runbook_url"),
        starts_at=raw.get("startsAt") or _now(),
    )


@dataclass
class _Snapshot:
    services: ServicesResponse
    alerts: AlertsResponse
    taken_at: float


@dataclass
class StatusService:
    settings: Settings
    prometheus: PrometheusClient
    alertmanager: AlertmanagerClient
    clock: Callable[[], float] = time.monotonic
    _snapshot: _Snapshot | None = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _prom: _SourceState = field(default_factory=_SourceState, init=False)
    _am: _SourceState = field(default_factory=_SourceState, init=False)
    _last_prom_data: _PrometheusData | None = field(default=None, init=False)

    async def snapshot(self) -> _Snapshot:
        """Cached for ``cache_ttl_seconds``; concurrent callers share one refresh."""
        if self._fresh():
            return self._snapshot  # type: ignore[return-value]
        async with self._lock:
            if not self._fresh():
                self._snapshot = await self._refresh()
        return self._snapshot  # type: ignore[return-value]

    def _fresh(self) -> bool:
        return (
            self._snapshot is not None
            and self.clock() - self._snapshot.taken_at < self.settings.cache_ttl_seconds
        )

    async def _refresh(self) -> _Snapshot:
        prom_result, am_result = await asyncio.gather(
            self._query_prometheus(), self.alertmanager.active_alerts(), return_exceptions=True
        )
        if isinstance(prom_result, _PrometheusData):
            self._prom.ok()
            self._last_prom_data = prom_result
        else:
            self._source_failed(self._prom, prom_result)
        raw_alerts: list[dict[str, Any]] = []
        if isinstance(am_result, list):
            self._am.ok()
            raw_alerts = am_result
        else:
            self._source_failed(self._am, am_result)

        alerts = [a for a in (_alert(raw, self.settings) for raw in raw_alerts) if a is not None]
        alerts.sort(key=lambda a: (a.severity != "critical", a.starts_at))
        generated_at = _now()
        return _Snapshot(
            services=self._services_response(alerts, generated_at),
            alerts=AlertsResponse(alerts=alerts, source=self._am.out(), generated_at=generated_at),
            taken_at=self.clock(),
        )

    @staticmethod
    def _source_failed(state: _SourceState, exc: BaseException) -> None:
        if not isinstance(exc, SourceError):
            # Programming errors must not be hidden as "unavailable".
            raise exc
        state.failed(str(exc))
        logger.warning("status source unavailable", extra={"error": str(exc)})

    async def _query_prometheus(self) -> _PrometheusData:
        q = build_queries(self.settings)
        p = self.prometheus
        end = time.time()
        start = end - self.settings.series_minutes * 60
        step = self.settings.series_step_seconds
        (
            probe,
            ready,
            desired,
            rps,
            errors,
            p95,
            rps_s,
            err_s,
            p95_s,
        ) = await asyncio.gather(
            p.vector(q.probe_success, by="service"),
            p.vector(q.ready_replicas, by="deployment"),
            p.vector(q.desired_replicas, by="deployment"),
            p.vector(q.rps, by="service_name"),
            p.vector(q.error_ratio, by="service_name"),
            p.vector(q.latency_p95, by="service_name"),
            p.matrix(q.rps_series, "service_name", start, end, step),
            p.matrix(q.error_ratio_series, "service_name", start, end, step),
            p.matrix(q.latency_p95_series, "service_name", start, end, step),
        )

        def ms(value: float | None) -> float | None:
            return None if value is None else round(value * 1000, 1)

        def count(value: float | None) -> int | None:
            return None if value is None else int(value)

        metrics: dict[str, Metrics] = {}
        series: dict[str, Series] = {}
        for name in self.settings.services:
            probe_value = probe.get(name)
            metrics[name] = Metrics(
                probe_success=None if probe_value is None else probe_value >= 1,
                ready_replicas=count(ready.get(name)),
                desired_replicas=count(desired.get(name)),
                rps=None if name not in rps else round(rps[name] or 0.0, 3),
                error_ratio_5m=None if errors.get(name) is None else round(errors[name], 4),
                latency_p95_ms=ms(p95.get(name)),
            )
            series[name] = Series(
                rps=[Point(t=t, v=v) for t, v in rps_s.get(name, [])],
                error_ratio=[Point(t=t, v=v) for t, v in err_s.get(name, [])],
                latency_p95_ms=[Point(t=t, v=ms(v)) for t, v in p95_s.get(name, [])],
            )
        return _PrometheusData(metrics=metrics, series=series)

    def _services_response(self, alerts: list[Alert], generated_at: datetime) -> ServicesResponse:
        settings = self.settings
        thresholds = Thresholds(
            error_ratio=settings.error_ratio_threshold,
            latency_p95_ms=settings.latency_p95_threshold_ms,
        )
        data = self._last_prom_data
        services = []
        for name in settings.services:
            service_alerts = [a for a in alerts if a.service == name]
            metrics = data.metrics[name] if data else None
            status, reasons = evaluate(
                metrics,
                service_alerts,
                thresholds,
                prometheus_ok=self._prom.error is None,
                alertmanager_ok=self._am.error is None,
            )
            services.append(
                ServiceStatus(
                    name=name,
                    status=status,
                    reasons=reasons,
                    metrics=metrics or Metrics(),
                    series=data.series[name] if data else Series(),
                    alerts=service_alerts,
                    links=Links(
                        dashboard=f"{settings.grafana_url}{DETAIL_DASHBOARD}?var-service={name}"
                    ),
                    updated_at=self._prom.last_success_at,
                )
            )
        return ServicesResponse(
            status=worst([s.status for s in services]),
            services=services,
            sources=Sources(prometheus=self._prom.out(), alertmanager=self._am.out()),
            thresholds=ThresholdsOut(
                error_ratio=thresholds.error_ratio, latency_p95_ms=thresholds.latency_p95_ms
            ),
            links={
                "grafana": settings.grafana_url,
                "overview_dashboard": f"{settings.grafana_url}{OVERVIEW_DASHBOARD}",
            },
            generated_at=generated_at,
        )
