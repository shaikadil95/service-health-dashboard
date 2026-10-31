"""Response models: the public v1 contract (documented in docs/architecture.md, section 8)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Status(StrEnum):
    UP = "UP"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    # The data needed to decide is missing (for example Prometheus is unreachable).
    UNKNOWN = "UNKNOWN"


# Worst first: an overall or per-service status is the worst of its parts.
SEVERITY_ORDER = (Status.DOWN, Status.DEGRADED, Status.UNKNOWN, Status.UP)


def worst(statuses: list[Status]) -> Status:
    for status in SEVERITY_ORDER:
        if status in statuses:
            return status
    return Status.UP


class Metrics(BaseModel):
    probe_success: bool | None = Field(None, description="Blackbox probe of /readyz")
    ready_replicas: int | None = None
    desired_replicas: int | None = None
    rps: float | None = Field(None, description="Requests per second, 5 m average")
    error_ratio_5m: float | None = Field(None, description="Share of 5xx responses (0-1), 5 m")
    latency_p95_ms: float | None = Field(None, description="p95 server latency, 5 m")


class Point(BaseModel):
    t: int = Field(description="Unix time in seconds")
    v: float | None


class Series(BaseModel):
    """Recent history for sparklines (1 m windows, one point per step)."""

    rps: list[Point] = []
    error_ratio: list[Point] = []
    latency_p95_ms: list[Point] = []


class Alert(BaseModel):
    name: str
    service: str | None
    severity: str
    summary: str | None = None
    description: str | None = None
    runbook_url: str | None = None
    starts_at: datetime


class Links(BaseModel):
    dashboard: str


class ServiceStatus(BaseModel):
    name: str
    status: Status
    reasons: list[str]
    metrics: Metrics
    series: Series
    alerts: list[Alert]
    links: Links
    updated_at: datetime | None = Field(
        description="When the metrics were read from Prometheus (kept while it is unreachable)"
    )


class Source(BaseModel):
    status: Literal["ok", "unavailable"]
    error: str | None = None
    last_success_at: datetime | None = None


class Sources(BaseModel):
    prometheus: Source
    alertmanager: Source


class Thresholds(BaseModel):
    error_ratio: float
    latency_p95_ms: float


class ServicesResponse(BaseModel):
    status: Status = Field(description="Worst status of all services")
    services: list[ServiceStatus]
    sources: Sources
    thresholds: Thresholds
    links: dict[str, str]
    generated_at: datetime


class AlertsResponse(BaseModel):
    alerts: list[Alert]
    source: Source
    generated_at: datetime
