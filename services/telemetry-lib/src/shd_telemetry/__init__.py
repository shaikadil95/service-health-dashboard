"""Shared OpenTelemetry, logging, probe, fault-injection and auth setup for the demo services."""

from .auth import (
    ANONYMOUS,
    Authenticator,
    AuthSettings,
    ClientCredentialsAuth,
    ClientCredentialsSettings,
    Principal,
    TokenError,
    audit_user,
    authorize,
    current_principal,
    end_user_headers,
)
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
    "ANONYMOUS",
    "AuthSettings",
    "Authenticator",
    "ClientCredentialsAuth",
    "ClientCredentialsSettings",
    "DrainingServer",
    "FaultConfig",
    "FaultInjector",
    "FaultUpdate",
    "JsonFormatter",
    "Lifecycle",
    "Principal",
    "ServiceRuntime",
    "Telemetry",
    "TokenError",
    "audit_user",
    "authorize",
    "configure_logging",
    "configure_telemetry",
    "create_service_app",
    "current_principal",
    "end_user_headers",
    "instrument_fastapi",
    "instrument_httpx_client",
    "serve",
]
