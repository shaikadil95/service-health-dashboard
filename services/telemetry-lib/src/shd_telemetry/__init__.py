"""Shared OpenTelemetry, logging, probe and fault-injection setup for the demo services."""

from .logs import JsonFormatter, configure_logging
from .otel import Telemetry, configure_telemetry, instrument_fastapi, instrument_httpx_client
from .runtime import (
    FaultConfig,
    FaultInjector,
    FaultUpdate,
    Lifecycle,
    ServiceRuntime,
    create_service_app,
)
from .server import DrainingServer, serve

__all__ = [
    "DrainingServer",
    "FaultConfig",
    "FaultInjector",
    "FaultUpdate",
    "JsonFormatter",
    "Lifecycle",
    "ServiceRuntime",
    "Telemetry",
    "configure_logging",
    "configure_telemetry",
    "create_service_app",
    "instrument_fastapi",
    "instrument_httpx_client",
    "serve",
]
