import io
import json
import logging

import pytest
from opentelemetry.instrumentation.logging import LoggingInstrumentor

from shd_telemetry import JsonFormatter, configure_logging, configure_telemetry
from shd_telemetry.testing import in_memory_telemetry


@pytest.fixture
def json_logs():
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    otel = in_memory_telemetry("log-test")
    configure_logging(otel.telemetry, level="INFO")
    buffer = io.StringIO()
    [handler] = [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]
    handler.setStream(buffer)
    yield otel, buffer
    LoggingInstrumentor().uninstrument()
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


def _lines(buffer: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line]


def test_logs_are_json_with_trace_context(json_logs):
    otel, buffer = json_logs
    tracer = otel.telemetry.tracer_provider.get_tracer("test")
    with tracer.start_as_current_span("work") as span:
        logging.getLogger("app").info("inside", extra={"order.id": "o-1"})
    logging.getLogger("app").warning("outside")

    inside, outside = _lines(buffer)
    context = span.get_span_context()
    assert inside["message"] == "inside"
    assert inside["level"] == "INFO"
    assert inside["service.name"] == "log-test"
    assert inside["trace_id"] == format(context.trace_id, "032x")
    assert inside["span_id"] == format(context.span_id, "016x")
    assert inside["trace_sampled"] is True
    assert inside["order.id"] == "o-1"
    assert "trace_id" not in outside
    assert outside["service.name"] == "log-test"


def test_exceptions_are_serialised(json_logs):
    _, buffer = json_logs
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("app").exception("failed")
    [line] = _lines(buffer)
    assert line["level"] == "ERROR"
    assert "RuntimeError: boom" in line["exception"]


def test_logging_after_shutdown_is_safe(monkeypatch, capsys):
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "console")
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "none")
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    telemetry = configure_telemetry("late-log", "1", set_global=False)
    try:
        configure_logging(telemetry, level="INFO")
        otlp = [h for h in root.handlers if type(h).__name__ == "LoggingHandler"]
        assert otlp, "OTLP log handler is installed when OTEL_LOGS_EXPORTER is set"
        telemetry.shutdown()
        assert not [h for h in root.handlers if type(h).__name__ == "LoggingHandler"]
        logging.getLogger("app").info("after shutdown")
        assert "recursive logging" not in capsys.readouterr().err
    finally:
        LoggingInstrumentor().uninstrument()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
