import pytest
from fastapi.testclient import TestClient

from shd_telemetry import create_service_app
from shd_telemetry.otel import build_resource, configure_telemetry
from shd_telemetry.testing import in_memory_telemetry


def test_resource_defaults(monkeypatch):
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    attributes = build_resource("order", "1.2.3").attributes
    assert attributes["service.name"] == "order"
    assert attributes["service.version"] == "1.2.3"
    assert attributes["deployment.environment.name"] == "local"
    assert len(attributes["service.instance.id"]) == 36
    assert attributes["telemetry.sdk.language"] == "python"


def test_resource_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "order-canary")
    monkeypatch.setenv(
        "OTEL_RESOURCE_ATTRIBUTES", "deployment.environment.name=kind,service.instance.id=pod-1"
    )
    attributes = build_resource("order", "1.2.3").attributes
    assert attributes["service.name"] == "order-canary"
    assert attributes["deployment.environment.name"] == "kind"
    assert attributes["service.instance.id"] == "pod-1"


def test_rejects_unknown_protocol(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/json")
    with pytest.raises(ValueError, match="OTEL_EXPORTER_OTLP_PROTOCOL"):
        configure_telemetry("svc", "1", set_global=False)


@pytest.mark.parametrize("protocol", ["grpc", "http/protobuf"])
def test_otlp_exporters_per_protocol(monkeypatch, protocol):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", protocol)
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "otlp")
    telemetry = configure_telemetry("svc", "1", set_global=False)
    processor = telemetry.tracer_provider._active_span_processor._span_processors[0]
    exporter_module = type(processor.span_exporter).__module__
    expected = "grpc" if protocol == "grpc" else "http"
    assert f".proto.{expected}." in exporter_module
    assert telemetry.logger_provider is not None
    telemetry.shutdown()


def test_exporters_can_be_disabled(monkeypatch):
    for signal in ("TRACES", "METRICS", "LOGS"):
        monkeypatch.setenv(f"OTEL_{signal}_EXPORTER", "none")
    telemetry = configure_telemetry("svc", "1", set_global=False)
    assert telemetry.tracer_provider._active_span_processor._span_processors == ()
    assert telemetry.logger_provider is None
    telemetry.shutdown()
    telemetry.shutdown()  # idempotent


def test_http_server_metrics_use_stable_semconv_and_skip_probes():
    otel = in_memory_telemetry("metrics-test")
    app = create_service_app(title="t", version="t", telemetry=otel.telemetry)

    @app.get("/items/{item_id}")
    async def item(item_id: str) -> dict:
        return {"id": item_id}

    with TestClient(app) as client:
        client.get("/items/1")
        client.get("/items/2")
        client.get("/livez")
        client.get("/readyz")

    names = otel.metric_names()
    assert "http.server.request.duration" in names
    assert "http.server.duration" not in names, "old semconv must not be emitted"
    points = otel.metric_points("http.server.request.duration")
    assert {p.attributes["http.route"] for p in points} == {"/items/{item_id}"}
    [point] = points
    assert point.count == 2
    assert point.attributes["http.request.method"] == "GET"
    assert point.attributes["http.response.status_code"] == 200
    span_names = {s.name for s in otel.spans.get_finished_spans()}
    assert span_names == {"GET /items/{item_id}"}, "no probe spans, no ASGI send/receive spans"
