"""Test helpers: in-memory exporters wired into a ``Telemetry`` without touching globals."""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from .otel import Telemetry, configure_telemetry


@dataclass
class InMemoryTelemetry:
    telemetry: Telemetry
    spans: InMemorySpanExporter
    metrics: InMemoryMetricReader

    def metric_points(self, name: str) -> list:
        """All data points of the metric called ``name`` collected so far."""
        data = self.metrics.get_metrics_data()
        points = []
        for resource_metrics in data.resource_metrics if data else []:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    if metric.name == name:
                        points.extend(metric.data.data_points)
        return points

    def metric_names(self) -> set[str]:
        data = self.metrics.get_metrics_data()
        return {
            metric.name
            for resource_metrics in (data.resource_metrics if data else [])
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
        }


def in_memory_telemetry(service_name: str, service_version: str = "test") -> InMemoryTelemetry:
    spans = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    telemetry = configure_telemetry(
        service_name,
        service_version,
        set_global=False,
        span_processors=[SimpleSpanProcessor(spans)],
        metric_readers=[reader],
    )
    return InMemoryTelemetry(telemetry=telemetry, spans=spans, metrics=reader)
