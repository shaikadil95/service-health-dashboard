"""Structured JSON logs on stdout, correlated with the active trace.

Trace context comes from ``opentelemetry-instrumentation-logging`` (``inject_trace_context``),
which adds ``otelTraceID``/``otelSpanID``/``otelTraceSampled``/``otelServiceName`` to every
``LogRecord``. The formatter renders them as ``trace_id``/``span_id``/``service.name`` so the
Collector (filelog receiver) and Loki can link log lines to traces.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime

from opentelemetry.instrumentation.logging import LoggingInstrumentor

from .otel import Telemetry

_INVALID_ID = "0"

# Attributes present on every LogRecord; anything else came from ``extra=`` and is emitted.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None)).keys()
    | {"message", "asctime", "taskName"}
    | {"otelTraceID", "otelSpanID", "otelTraceSampled", "otelServiceName"}
    | {"color_message"}  # uvicorn's ANSI-coloured duplicate of the message
)


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str = "") -> None:
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service.name": getattr(record, "otelServiceName", "") or self._service_name,
        }
        trace_id = getattr(record, "otelTraceID", _INVALID_ID)
        if trace_id and trace_id != _INVALID_ID:
            payload["trace_id"] = trace_id
            payload["span_id"] = getattr(record, "otelSpanID", _INVALID_ID)
            payload["trace_sampled"] = bool(getattr(record, "otelTraceSampled", False))
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(telemetry: Telemetry, level: str | None = None) -> None:
    """Send all logs to stdout as JSON with trace context.

    When ``OTEL_LOGS_EXPORTER`` enabled a logger provider, records are also exported over OTLP
    by the handler that the logging instrumentation installs.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(JsonFormatter(telemetry.service_name))
    root.addHandler(stdout)
    root.setLevel((level or os.environ.get("LOG_LEVEL", "INFO")).upper())
    # httpx logs every request at INFO; client spans and metrics already cover that.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    instrumentor = LoggingInstrumentor()
    if instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.uninstrument()
    instrumentor.instrument(
        tracer_provider=telemetry.tracer_provider,
        inject_trace_context=True,
        enable_log_auto_instrumentation=telemetry.logger_provider is not None,
    )
