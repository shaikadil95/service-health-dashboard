"""Settings from environment variables (12-factor); defaults suit a local run."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

# Service names are interpolated into PromQL label matchers; keep them to a safe charset.
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    prometheus_url: str = "http://localhost:9090"
    alertmanager_url: str = "http://localhost:9093"
    # Services to report on (value of the service.name resource attribute and Deployment name).
    services: tuple[str, ...] = ("user", "order", "payment")
    # Kubernetes namespace of the services (label k8s_namespace_name / namespace).
    namespace: str = "apps"
    cache_ttl_seconds: float = 10.0
    query_timeout_seconds: float = 3.0
    # Same thresholds as the alert rules (docs/architecture.md, section 7).
    error_ratio_threshold: float = 0.05
    latency_p95_threshold_ms: float = 500.0
    # Sparklines: last 30 minutes, one point per minute.
    series_minutes: int = 30
    series_step_seconds: int = 60
    grafana_url: str = "http://grafana.localtest.me"

    def __post_init__(self) -> None:
        for name in (*self.services, self.namespace):
            if not _NAME.match(name):
                raise ValueError(f"invalid service or namespace name: {name!r}")
        if not self.services:
            raise ValueError("at least one service is required")

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        services = os.environ.get("STATUS_SERVICES", "")
        return cls(
            prometheus_url=os.environ.get("PROMETHEUS_URL", defaults.prometheus_url),
            alertmanager_url=os.environ.get("ALERTMANAGER_URL", defaults.alertmanager_url),
            services=tuple(s.strip() for s in services.split(",") if s.strip())
            or defaults.services,
            namespace=os.environ.get("STATUS_NAMESPACE", defaults.namespace),
            cache_ttl_seconds=_float("CACHE_TTL_SECONDS", defaults.cache_ttl_seconds),
            query_timeout_seconds=_float("QUERY_TIMEOUT_SECONDS", defaults.query_timeout_seconds),
            error_ratio_threshold=_float("ERROR_RATIO_THRESHOLD", defaults.error_ratio_threshold),
            latency_p95_threshold_ms=_float(
                "LATENCY_P95_THRESHOLD_MS", defaults.latency_p95_threshold_ms
            ),
            series_minutes=int(_float("SERIES_MINUTES", defaults.series_minutes)),
            series_step_seconds=int(_float("SERIES_STEP_SECONDS", defaults.series_step_seconds)),
            grafana_url=os.environ.get("GRAFANA_URL", defaults.grafana_url).rstrip("/"),
        )
