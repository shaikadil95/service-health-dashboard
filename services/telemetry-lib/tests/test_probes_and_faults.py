import random
import time

import pytest
from fastapi.testclient import TestClient
from opentelemetry.trace import StatusCode

from shd_telemetry import FaultConfig, FaultInjector, create_service_app
from shd_telemetry.runtime import _env_bool
from shd_telemetry.testing import in_memory_telemetry


@pytest.fixture
def otel():
    return in_memory_telemetry("probe-test")


@pytest.fixture
def app(otel):
    app = create_service_app(
        title="probe-test",
        version="test",
        telemetry=otel.telemetry,
        faults=FaultInjector(FaultConfig(), rng=random.Random(42)),
    )

    @app.get("/work")
    async def work() -> dict:
        return {"ok": True}

    return app


def test_readyz_fails_until_startup_completed(app):
    client = TestClient(app)  # lifespan not started
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "reasons": ["starting"]}
    assert client.get("/livez").status_code == 200


def test_probes_when_started(app):
    with TestClient(app) as client:
        assert client.get("/livez").json() == {"status": "alive"}
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.headers["cache-control"] == "no-store"


def test_readyz_fails_while_draining_but_livez_and_traffic_continue(app):
    with TestClient(app) as client:
        app.state.runtime.lifecycle.draining = True
        assert client.get("/readyz").json() == {"status": "not_ready", "reasons": ["draining"]}
        assert client.get("/livez").status_code == 200
        assert client.get("/work").status_code == 200


def test_fault_injected_not_ready(app):
    with TestClient(app) as client:
        assert client.put("/admin/faults", json={"ready": False}).json()["ready"] is False
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["reasons"] == ["fault_injected"]
        assert client.get("/livez").status_code == 200, "liveness must not follow readiness"
        assert client.get("/work").status_code == 200


def test_put_faults_is_partial_and_validated(app):
    with TestClient(app) as client:
        assert client.put("/admin/faults", json={"latency_ms": 5}).json() == {
            "error_rate": 0.0,
            "latency_ms": 5,
            "ready": True,
        }
        assert client.put("/admin/faults", json={"error_rate": 1.5}).status_code == 422
        assert client.put("/admin/faults", json={"latency_ms": -1}).status_code == 422
        assert client.put("/admin/faults", json={"unknown": 1}).status_code == 422
        assert client.get("/admin/faults").json()["latency_ms"] == 5
        assert client.delete("/admin/faults").json() == FaultConfig().model_dump()


def test_error_rate_one_fails_business_requests_only(app, otel):
    with TestClient(app) as client:
        client.put("/admin/faults", json={"error_rate": 1.0})
        response = client.get("/work")
        assert response.status_code == 500
        assert response.json() == {"detail": "Injected fault"}
        assert client.get("/readyz").status_code == 200
        assert client.get("/livez").status_code == 200
        assert client.get("/admin/faults").status_code == 200

    work_spans = [s for s in otel.spans.get_finished_spans() if s.name == "GET /work"]
    assert len(work_spans) == 1
    span = work_spans[0]
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes["http.response.status_code"] == 500
    assert [e.name for e in span.events] == ["fault.injected"]


def test_error_rate_is_probabilistic(otel):
    faults = FaultInjector(FaultConfig(error_rate=0.3), rng=random.Random(7))
    failures = sum(faults.should_fail() for _ in range(10_000))
    assert 2_700 < failures < 3_300
    assert not FaultInjector(FaultConfig(), rng=random.Random(7)).should_fail()


def test_latency_is_injected_and_measured(app, otel):
    with TestClient(app) as client:
        client.put("/admin/faults", json={"latency_ms": 120})
        start = time.perf_counter()
        assert client.get("/work").status_code == 200
        assert time.perf_counter() - start >= 0.12
        start = time.perf_counter()
        client.get("/readyz")
        assert time.perf_counter() - start < 0.12, "probes must not be delayed"

    [point] = [
        p
        for p in otel.metric_points("http.server.request.duration")
        if p.attributes.get("http.route") == "/work"
    ]
    assert point.sum >= 0.12  # seconds, stable semantic conventions


def test_fault_defaults_from_env(monkeypatch):
    monkeypatch.setenv("FAULT_ERROR_RATE", "0.25")
    monkeypatch.setenv("FAULT_LATENCY_MS", "300")
    monkeypatch.setenv("FAULT_READY", "false")
    assert FaultConfig.from_env() == FaultConfig(error_rate=0.25, latency_ms=300, ready=False)
    monkeypatch.setenv("FAULT_ERROR_RATE", "2")
    with pytest.raises(ValueError, match="less than or equal to 1"):
        FaultConfig.from_env()


def test_env_bool_rejects_garbage(monkeypatch):
    monkeypatch.setenv("X_FLAG", "maybe")
    with pytest.raises(ValueError, match="not a boolean"):
        _env_bool("X_FLAG", True)
