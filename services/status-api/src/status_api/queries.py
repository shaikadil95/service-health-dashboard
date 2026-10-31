"""PromQL used by the Status API.

Metric names are the Prometheus OTLP translations (``http.server.request.duration`` becomes
``http_server_request_duration_seconds_*``, the resource attribute ``service.name`` is promoted to
the label ``service_name``), see deploy/values/kube-prometheus-stack.yaml. The Grafana dashboards
use the same expressions.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings

HTTP = "http_server_request_duration_seconds"


@dataclass(frozen=True)
class Queries:
    probe_success: str
    ready_replicas: str
    desired_replicas: str
    rps: str
    error_ratio: str
    latency_p95: str
    rps_series: str
    error_ratio_series: str
    latency_p95_series: str


def _rps(selector: str, window: str) -> str:
    return f"sum by (service_name) (rate({HTTP}_count{{{selector}}}[{window}]))"


def _error_ratio(selector: str, window: str) -> str:
    server_errors = f'{selector}, http_response_status_code=~"5.."'
    errors = _rps(server_errors, window)
    total = _rps(selector, window)
    # "or ... * 0" yields 0 instead of no result when a service has traffic but no 5xx.
    return f"({errors} or {total} * 0) / {total}"


def _p95(selector: str, window: str) -> str:
    return (
        "histogram_quantile(0.95, sum by (service_name, le) "
        f"(rate({HTTP}_bucket{{{selector}}}[{window}])))"
    )


def build_queries(settings: Settings) -> Queries:
    services = "|".join(settings.services)
    ns = settings.namespace
    # /admin/faults calls (demo tooling) are not user traffic.
    http = f'k8s_namespace_name="{ns}", service_name=~"{services}", http_route!~"/admin/.*"'
    deploy = f'namespace="{ns}", deployment=~"{services}"'
    probe = f'namespace="{ns}", service=~"{services}"'
    return Queries(
        # min: one failing probe is enough.
        probe_success=f"min by (service) (probe_success{{{probe}}})",
        ready_replicas=f"max by (deployment) (kube_deployment_status_replicas_ready{{{deploy}}})",
        desired_replicas=f"max by (deployment) (kube_deployment_spec_replicas{{{deploy}}})",
        rps=_rps(http, "5m"),
        error_ratio=_error_ratio(http, "5m"),
        latency_p95=_p95(http, "5m"),
        rps_series=_rps(http, "1m"),
        error_ratio_series=_error_ratio(http, "1m"),
        latency_p95_series=_p95(http, "1m"),
    )
