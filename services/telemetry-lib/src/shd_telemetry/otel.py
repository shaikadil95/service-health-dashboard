"""OpenTelemetry SDK setup: resource, providers, exporters and instrumentation.

Configuration follows the standard OpenTelemetry environment variables
(https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/):

* ``OTEL_SERVICE_NAME`` / ``OTEL_RESOURCE_ATTRIBUTES`` override the resource defaults.
* ``OTEL_EXPORTER_OTLP_ENDPOINT`` and ``OTEL_EXPORTER_OTLP_PROTOCOL`` (``grpc`` or
  ``http/protobuf``, also per signal) select where and how data is sent.
* ``OTEL_TRACES_EXPORTER`` / ``OTEL_METRICS_EXPORTER`` / ``OTEL_LOGS_EXPORTER`` accept
  ``otlp``, ``console`` or ``none``.
* ``OTEL_METRIC_EXPORT_INTERVAL``, ``OTEL_TRACES_SAMPLER`` and ``OTEL_PROPAGATORS`` are read
  by the SDK itself.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
    SpanProcessor,
)

# Stable HTTP semantic conventions (`http.server.request.duration` in seconds) are still
# opt-in in opentelemetry-python-contrib 0.66b2; the default emits the old
# `http.server.duration` (ms). See
# https://opentelemetry.io/docs/specs/semconv/non-normative/http-migration/
SEMCONV_OPT_IN_ENV = "OTEL_SEMCONV_STABILITY_OPT_IN"

# Probes are high-frequency and carry no user traffic: keep them out of traces and RED metrics.
DEFAULT_EXCLUDED_URLS = "/livez,/readyz"

_PROTOCOLS = ("grpc", "http/protobuf")
_EXPORTERS = ("otlp", "console", "none")


@dataclass
class Telemetry:
    """Providers created for one service process."""

    resource: Resource
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider | None = None
    _shut_down: bool = field(default=False, repr=False)

    @property
    def service_name(self) -> str:
        return str(self.resource.attributes.get("service.name", ""))

    def shutdown(self) -> None:
        """Flush and close all providers (idempotent)."""
        if self._shut_down:
            return
        self._shut_down = True
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        if self.logger_provider is not None:
            # Detach the OTLP log handler first: records logged after the provider is closed
            # would otherwise trigger SDK warnings that are themselves logged (recursion).
            root = logging.getLogger()
            for handler in [h for h in root.handlers if isinstance(h, LoggingHandler)]:
                root.removeHandler(handler)
            self.logger_provider.shutdown()


def build_resource(service_name: str, service_version: str) -> Resource:
    """Resource with sensible defaults; ``OTEL_SERVICE_NAME``/``OTEL_RESOURCE_ATTRIBUTES`` win."""
    defaults = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            # Unique per process, as recommended by the semantic conventions. Kubernetes
            # deployments can override it (for example with the pod UID) through
            # OTEL_RESOURCE_ATTRIBUTES.
            "service.instance.id": str(uuid.uuid4()),
            "deployment.environment.name": "local",
        }
    )
    # Resource.create() lets explicit attributes win over the environment; re-applying the
    # environment detector (OTEL_RESOURCE_ATTRIBUTES, OTEL_SERVICE_NAME) restores the
    # precedence operators expect.
    return defaults.merge(OTELResourceDetector().detect())


def _choice(env: str, default: str, allowed: Sequence[str]) -> str:
    value = os.environ.get(env, default).strip().lower() or default
    if value not in allowed:
        raise ValueError(f"{env}={value!r} is not supported; use one of {', '.join(allowed)}")
    return value


def _protocol(signal: str) -> str:
    generic = _choice("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc", _PROTOCOLS)
    return _choice(f"OTEL_EXPORTER_OTLP_{signal.upper()}_PROTOCOL", generic, _PROTOCOLS)


def _otlp_span_exporter() -> SpanExporter:
    if _protocol("traces") == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter()
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter()


def _otlp_metric_exporter():
    if _protocol("metrics") == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

        return OTLPMetricExporter()
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

    return OTLPMetricExporter()


def _otlp_log_exporter():
    if _protocol("logs") == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

        return OTLPLogExporter()
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

    return OTLPLogExporter()


def configure_telemetry(
    service_name: str,
    service_version: str,
    *,
    set_global: bool = True,
    span_processors: Sequence[SpanProcessor] | None = None,
    metric_readers: Sequence[MetricReader] | None = None,
) -> Telemetry:
    """Create tracer, meter and (optionally) logger providers for a service.

    ``span_processors``/``metric_readers`` replace the environment-selected exporters; tests use
    them to plug in in-memory exporters.
    """
    os.environ.setdefault(SEMCONV_OPT_IN_ENV, "http")
    resource = build_resource(service_name, service_version)

    tracer_provider = TracerProvider(resource=resource)
    if span_processors is None:
        traces_exporter = _choice("OTEL_TRACES_EXPORTER", "otlp", _EXPORTERS)
        span_processors = []
        if traces_exporter == "otlp":
            span_processors = [BatchSpanProcessor(_otlp_span_exporter())]
        elif traces_exporter == "console":
            span_processors = [BatchSpanProcessor(ConsoleSpanExporter())]
    for processor in span_processors:
        tracer_provider.add_span_processor(processor)

    if metric_readers is None:
        metrics_exporter = _choice("OTEL_METRICS_EXPORTER", "otlp", _EXPORTERS)
        metric_readers = []
        if metrics_exporter == "otlp":
            metric_readers = [PeriodicExportingMetricReader(_otlp_metric_exporter())]
        elif metrics_exporter == "console":
            metric_readers = [PeriodicExportingMetricReader(ConsoleMetricExporter())]
    meter_provider = MeterProvider(resource=resource, metric_readers=list(metric_readers))

    # Logs go to stdout as JSON by default and are collected by the Collector's filelog
    # receiver (ADR 0001/0002), so OTLP log export is opt-in to avoid duplicates.
    logger_provider = None
    logs_exporter = _choice("OTEL_LOGS_EXPORTER", "none", _EXPORTERS)
    if logs_exporter != "none":
        logger_provider = LoggerProvider(resource=resource)
        exporter = _otlp_log_exporter() if logs_exporter == "otlp" else ConsoleLogRecordExporter()
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

    if set_global:
        trace.set_tracer_provider(tracer_provider)
        metrics.set_meter_provider(meter_provider)
        if logger_provider is not None:
            set_logger_provider(logger_provider)

    return Telemetry(
        resource=resource,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
    )


def instrument_fastapi(
    app: FastAPI, telemetry: Telemetry, excluded_urls: str | None = None
) -> None:
    """Server spans + ``http.server.request.duration`` for every route except the probes."""
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=telemetry.tracer_provider,
        meter_provider=telemetry.meter_provider,
        excluded_urls=excluded_urls if excluded_urls is not None else DEFAULT_EXCLUDED_URLS,
        # Per-ASGI-message "http send/receive" child spans add noise without information.
        exclude_spans=["receive", "send"],
    )


def instrument_httpx_client(client, telemetry: Telemetry) -> None:
    """Client spans, ``http.client.request.duration`` and W3C ``traceparent`` injection."""
    HTTPXClientInstrumentor.instrument_client(
        client,
        tracer_provider=telemetry.tracer_provider,
        meter_provider=telemetry.meter_provider,
    )
