"""Status API tests. Prometheus and Alertmanager are replaced by an httpx.MockTransport."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from shd_telemetry.testing import in_memory_telemetry
from status_api.app import create_app
from status_api.config import Settings
from status_api.models import Alert, Metrics, Status
from status_api.rules import Thresholds, evaluate
from status_api.service import StatusService
from status_api.sources import AlertmanagerClient, PrometheusClient

PROM = "http://prometheus.test:9090"
AM = "http://alertmanager.test:9093"
SETTINGS = Settings(prometheus_url=PROM, alertmanager_url=AM, grafana_url="http://grafana.test")
NOW = 1_800_000_000


@dataclass
class Svc:
    probe: float = 1
    ready: float = 1
    desired: float = 1
    rps: float = 4.0
    error_ratio: float = 0.0
    p95_s: float = 0.02


@dataclass
class FakeBackends:
    """Answers the Status API's PromQL by recognising each query, plus Alertmanager's alerts."""

    services: dict[str, Svc] = field(
        default_factory=lambda: {name: Svc() for name in ("user", "order", "payment")}
    )
    alerts: list[dict[str, Any]] = field(default_factory=list)
    prometheus_error: Exception | int | None = None
    alertmanager_error: Exception | int | None = None
    prometheus_calls: int = 0
    queries: list[str] = field(default_factory=list)

    def _value(self, query: str, svc: Svc) -> tuple[str, float]:
        if "probe_success" in query:
            return "service", svc.probe
        if "kube_deployment_status_replicas_ready" in query:
            return "deployment", svc.ready
        if "kube_deployment_spec_replicas" in query:
            return "deployment", svc.desired
        if "histogram_quantile" in query:
            return "service_name", svc.p95_s
        if 'http_response_status_code=~"5.."' in query:
            return "service_name", svc.error_ratio
        return "service_name", svc.rps

    def _fail(self, error: Exception | int) -> httpx.Response:
        if isinstance(error, Exception):
            raise error
        return httpx.Response(error, text="unavailable")

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "alertmanager.test":
            assert request.url.path == "/api/v2/alerts"
            assert request.url.params["silenced"] == "false"
            if self.alertmanager_error is not None:
                return self._fail(self.alertmanager_error)
            return httpx.Response(200, json=self.alerts)

        self.prometheus_calls += 1
        if self.prometheus_error is not None:
            return self._fail(self.prometheus_error)
        query = request.url.params["query"]
        # Prometheus rejects "1.0s" with HTTP 400; a float number of seconds is valid.
        float(request.url.params["timeout"])
        self.queries.append(query)
        result = []
        for name, svc in self.services.items():
            label, value = self._value(query, svc)
            if request.url.path == "/api/v1/query":
                result.append({"metric": {label: name}, "value": [NOW, str(value)]})
            else:
                values = [[NOW - 60 * i, str(value)] for i in range(3, 0, -1)]
                result.append({"metric": {label: name}, "values": values})
        result_type = "vector" if request.url.path == "/api/v1/query" else "matrix"
        return httpx.Response(
            200, json={"status": "success", "data": {"resultType": result_type, "result": result}}
        )


def am_alert(name: str, severity: str, **labels: str) -> dict[str, Any]:
    return {
        "labels": {"alertname": name, "severity": severity, **labels},
        "annotations": {"summary": f"{name} summary", "runbook_url": "https://runbooks/x"},
        "startsAt": "2026-10-31T18:00:00Z",
        "status": {"state": "active"},
    }


@pytest.fixture
def backends() -> FakeBackends:
    return FakeBackends()


@pytest.fixture
def client(backends):
    telemetry = in_memory_telemetry("status-api").telemetry
    app = create_app(telemetry, SETTINGS, transport=httpx.MockTransport(backends.handler))
    with TestClient(app) as client:
        yield client


def by_name(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["name"]: s for s in body["services"]}


# --- API -------------------------------------------------------------------------------------


def test_all_up(client, backends):
    response = client.get("/api/v1/services")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == "UP"
    assert [s["name"] for s in body["services"]] == ["user", "order", "payment"]
    assert body["sources"]["prometheus"]["status"] == "ok"
    assert body["sources"]["alertmanager"]["status"] == "ok"
    assert body["thresholds"] == {"error_ratio": 0.05, "latency_p95_ms": 500.0}
    assert body["links"]["overview_dashboard"].startswith("http://grafana.test/d/shd-overview/")
    payment = by_name(body)["payment"]
    assert payment["status"] == "UP"
    assert payment["reasons"] == []
    assert payment["metrics"] == {
        "probe_success": True,
        "ready_replicas": 1,
        "desired_replicas": 1,
        "rps": 4.0,
        "error_ratio_5m": 0.0,
        "latency_p95_ms": 20.0,
    }
    assert payment["series"]["latency_p95_ms"][-1] == {"t": NOW - 60, "v": 20.0}
    assert len(payment["series"]["rps"]) == 3
    assert payment["links"]["dashboard"].endswith(
        "/d/shd-service-detail/service-detail?var-service=payment"
    )
    assert payment["updated_at"] is not None
    # Admin calls are excluded from the RED metrics; the selector is scoped to the namespace.
    rps_query = next(q for q in backends.queries if q.startswith("sum by (service_name)"))
    assert 'http_route!~"/admin/.*"' in rps_query
    assert 'k8s_namespace_name="apps"' in rps_query


def test_single_service_and_unknown(client):
    assert client.get("/api/v1/services/order").json()["name"] == "order"
    response = client.get("/api/v1/services/nope")
    assert response.status_code == 404


def test_probe_failure_is_down(client, backends):
    backends.services["payment"].probe = 0
    body = client.get("/api/v1/services").json()
    payment = by_name(body)["payment"]
    assert payment["status"] == "DOWN"
    assert payment["reasons"] == ["readiness probe failing (probe_success = 0)"]
    assert body["status"] == "DOWN"


def test_error_ratio_breach_is_degraded(client, backends):
    backends.services["payment"].error_ratio = 0.32
    backends.services["order"].error_ratio = 0.05  # equal to the threshold: not a breach
    services = by_name(client.get("/api/v1/services").json())
    assert services["payment"]["status"] == "DEGRADED"
    assert services["payment"]["reasons"] == ["5xx error ratio 32.0% > 5.0% (5m)"]
    assert services["order"]["status"] == "UP"


def test_latency_breach_is_degraded(client, backends):
    backends.services["user"].p95_s = 0.8
    user = by_name(client.get("/api/v1/services").json())["user"]
    assert user["status"] == "DEGRADED"
    assert user["reasons"] == ["p95 latency 800 ms > 500 ms (5m)"]


def test_alerts_drive_status_and_are_listed(client, backends):
    backends.alerts = [
        am_alert("HighErrorRate", "critical", service="payment"),
        am_alert("HighLatencyP95", "warning", service="user"),
        # Generic kube-prometheus-stack rule: matched by namespace + deployment.
        am_alert("KubeDeploymentReplicasMismatch", "warning", namespace="apps", deployment="order"),
        am_alert("Watchdog", "none"),
        am_alert("KubeletDown", "critical"),
    ]
    services = by_name(client.get("/api/v1/services").json())
    assert services["payment"]["status"] == "DOWN"
    assert services["payment"]["reasons"] == ["critical alert HighErrorRate is firing"]
    assert services["payment"]["alerts"][0]["runbook_url"] == "https://runbooks/x"
    assert services["user"]["status"] == "DEGRADED"
    assert services["order"]["status"] == "DEGRADED"

    alerts = client.get("/api/v1/alerts").json()
    names = [a["name"] for a in alerts["alerts"]]
    assert "Watchdog" not in names
    # Critical first; alerts that are not about our services are still listed.
    assert names[:2] == ["HighErrorRate", "KubeletDown"]
    assert {a["name"]: a["service"] for a in alerts["alerts"]}["KubeletDown"] is None
    assert alerts["alerts"][0]["starts_at"] == "2026-10-31T18:00:00Z"
    assert alerts["source"]["status"] == "ok"


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), 503],
    ids=["connect-error", "timeout", "http-503"],
)
def test_prometheus_unavailable_is_unknown_not_500(client, backends, error):
    backends.prometheus_error = error
    response = client.get("/api/v1/services")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UNKNOWN"
    assert body["sources"]["prometheus"]["status"] == "unavailable"
    assert body["sources"]["prometheus"]["last_success_at"] is None
    for service in body["services"]:
        assert service["status"] == "UNKNOWN"
        assert service["updated_at"] is None
        assert "Prometheus is unreachable" in service["reasons"][0]


def test_prometheus_error_payload_is_unavailable():
    def bad(request: httpx.Request) -> httpx.Response:
        if request.url.host == "alertmanager.test":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"status": "error", "errorType": "bad_data"})

    telemetry = in_memory_telemetry("status-api").telemetry
    app = create_app(telemetry, SETTINGS, transport=httpx.MockTransport(bad))
    with TestClient(app) as c:
        body = c.get("/api/v1/services").json()
    assert body["sources"]["prometheus"] == {
        "status": "unavailable",
        "error": "prometheus: bad_data",
        "last_success_at": None,
    }


def test_critical_alert_still_counts_while_prometheus_is_down(client, backends):
    backends.prometheus_error = httpx.ConnectError("refused")
    backends.alerts = [am_alert("ServiceDown", "critical", service="payment")]
    services = by_name(client.get("/api/v1/services").json())
    assert services["payment"]["status"] == "DOWN"
    assert services["user"]["status"] == "UNKNOWN"


def test_alertmanager_unavailable_uses_metrics(client, backends):
    backends.alertmanager_error = httpx.ConnectError("refused")
    backends.services["payment"].error_ratio = 0.5
    body = client.get("/api/v1/services").json()
    assert body["sources"]["alertmanager"]["status"] == "unavailable"
    services = by_name(body)
    assert services["user"]["status"] == "UP"
    assert services["user"]["reasons"] == ["Alertmanager is unreachable; alerts not considered"]
    assert services["payment"]["status"] == "DEGRADED"
    alerts = client.get("/api/v1/alerts")
    assert alerts.status_code == 200
    assert alerts.json()["alerts"] == []
    assert alerts.json()["source"]["status"] == "unavailable"


def test_probes_do_not_depend_on_backends(client, backends):
    backends.prometheus_error = httpx.ConnectError("refused")
    backends.alertmanager_error = httpx.ConnectError("refused")
    assert client.get("/livez").status_code == 200
    assert client.get("/readyz").status_code == 200


# --- Cache and staleness -----------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_service(
    backends: FakeBackends, clock: FakeClock
) -> tuple[StatusService, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(backends.handler))
    service = StatusService(
        settings=SETTINGS,
        prometheus=PrometheusClient(http, PROM, 1.0),
        alertmanager=AlertmanagerClient(http, AM, 1.0),
        clock=clock,
    )
    return service, http


def test_cache_ttl_and_single_flight(backends):
    async def scenario() -> None:
        clock = FakeClock()
        service, http = make_service(backends, clock)
        async with http:
            await asyncio.gather(*(service.snapshot() for _ in range(5)))
            per_refresh = backends.prometheus_calls
            assert per_refresh == 9  # 6 instant + 3 range queries, once for 5 callers
            clock.now += 9.9
            await service.snapshot()
            assert backends.prometheus_calls == per_refresh
            clock.now += 0.2
            await service.snapshot()
            assert backends.prometheus_calls == 2 * per_refresh

    asyncio.run(scenario())


def test_stale_metrics_are_kept_with_last_updated_at(backends):
    async def scenario() -> None:
        clock = FakeClock()
        service, http = make_service(backends, clock)
        async with http:
            first = (await service.snapshot()).services
            backends.prometheus_error = httpx.ConnectError("refused")
            clock.now += 11
            second = (await service.snapshot()).services
        user_before = first.services[0]
        user_after = second.services[0]
        assert user_after.status == Status.UNKNOWN
        assert user_after.updated_at == user_before.updated_at
        assert user_after.metrics == user_before.metrics
        assert second.sources.prometheus.last_success_at == user_before.updated_at

    asyncio.run(scenario())


# --- Rules -------------------------------------------------------------------------------------

THRESHOLDS = Thresholds(error_ratio=0.05, latency_p95_ms=500)
HEALTHY = Metrics(
    probe_success=True,
    ready_replicas=2,
    desired_replicas=2,
    rps=3,
    error_ratio_5m=0.01,
    latency_p95_ms=120,
)


def alert(severity: str) -> Alert:
    return Alert(name="X", service="user", severity=severity, starts_at="2026-10-31T18:00:00Z")


@pytest.mark.parametrize(
    ("metrics", "alerts", "expected"),
    [
        (HEALTHY, [], Status.UP),
        (HEALTHY.model_copy(update={"probe_success": False}), [], Status.DOWN),
        (HEALTHY, [alert("critical")], Status.DOWN),
        (HEALTHY, [alert("warning")], Status.DEGRADED),
        (HEALTHY.model_copy(update={"error_ratio_5m": 0.051}), [], Status.DEGRADED),
        (HEALTHY.model_copy(update={"latency_p95_ms": 501}), [], Status.DEGRADED),
        (HEALTHY.model_copy(update={"ready_replicas": 1}), [], Status.DEGRADED),
        (HEALTHY.model_copy(update={"probe_success": None}), [], Status.UNKNOWN),
        # No traffic: no ratio or latency, but the probe still decides.
        (Metrics(probe_success=True), [], Status.UP),
        # Worst wins: a failing probe beats a warning and a threshold breach.
        (
            HEALTHY.model_copy(update={"probe_success": False, "latency_p95_ms": 900}),
            [alert("warning")],
            Status.DOWN,
        ),
    ],
    ids=[
        "healthy",
        "probe-fails",
        "critical-alert",
        "warning-alert",
        "error-ratio",
        "latency",
        "replicas",
        "no-probe-data",
        "no-traffic",
        "worst-wins",
    ],
)
def test_rules(metrics, alerts, expected):
    status, reasons = evaluate(
        metrics, alerts, THRESHOLDS, prometheus_ok=True, alertmanager_ok=True
    )
    assert status == expected
    assert (reasons == []) == (expected == Status.UP)


def test_reasons_are_ordered_worst_first():
    metrics = HEALTHY.model_copy(update={"probe_success": False, "latency_p95_ms": 900})
    _, reasons = evaluate(metrics, [], THRESHOLDS, prometheus_ok=True, alertmanager_ok=True)
    assert reasons[0].startswith("readiness probe failing")
    assert reasons[1].startswith("p95 latency 900 ms")


# --- Settings ----------------------------------------------------------------------------------


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("STATUS_SERVICES", "user, order")
    monkeypatch.setenv("ERROR_RATIO_THRESHOLD", "0.1")
    monkeypatch.setenv("GRAFANA_URL", "http://g/")
    settings = Settings.from_env()
    assert settings.services == ("user", "order")
    assert settings.error_ratio_threshold == 0.1
    assert settings.grafana_url == "http://g"


@pytest.mark.parametrize("name", ['user"}', "a|b", "UPPER", ""])
def test_settings_reject_names_that_could_inject_promql(name):
    with pytest.raises(ValueError, match="invalid"):
        Settings(services=(name,))


def test_openapi_lists_the_v1_contract(client):
    paths = json.loads(client.get("/openapi.json").text)["paths"]
    assert {"/api/v1/services", "/api/v1/services/{name}", "/api/v1/alerts"} <= set(paths)
