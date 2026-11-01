"""Health probes, fault injection and the common FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import ASGIApp, Receive, Scope, Send

from .auth import Authenticator, AuthSettings
from .otel import Telemetry, instrument_fastapi

logger = logging.getLogger("shd.runtime")

PROBE_PATHS = frozenset({"/livez", "/readyz"})
ADMIN_PREFIX = "/admin"
MAX_LATENCY_MS = 30_000


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return default if raw is None or raw.strip() == "" else float(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name}={raw!r} is not a boolean")


class FaultConfig(BaseModel):
    """Current fault-injection settings."""

    model_config = ConfigDict(extra="forbid")

    error_rate: float = Field(0.0, ge=0.0, le=1.0, description="Share of requests that fail")
    latency_ms: int = Field(0, ge=0, le=MAX_LATENCY_MS, description="Delay added to requests")
    ready: bool = Field(True, description="False makes /readyz fail")

    @classmethod
    def from_env(cls) -> FaultConfig:
        return cls(
            error_rate=_env_float("FAULT_ERROR_RATE", 0.0),
            latency_ms=int(_env_float("FAULT_LATENCY_MS", 0)),
            ready=_env_bool("FAULT_READY", True),
        )


class FaultUpdate(BaseModel):
    """Partial update for ``PUT /admin/faults``; omitted fields keep their value."""

    model_config = ConfigDict(extra="forbid")

    error_rate: float | None = Field(None, ge=0.0, le=1.0)
    latency_ms: int | None = Field(None, ge=0, le=MAX_LATENCY_MS)
    ready: bool | None = None


class FaultInjector:
    def __init__(self, defaults: FaultConfig | None = None, rng: random.Random | None = None):
        self.defaults = defaults if defaults is not None else FaultConfig.from_env()
        self.config = self.defaults.model_copy()
        self._rng = rng or random.Random()

    def update(self, change: FaultUpdate) -> FaultConfig:
        self.config = self.config.model_copy(update=change.model_dump(exclude_none=True))
        return self.config

    def reset(self) -> FaultConfig:
        self.config = self.defaults.model_copy()
        return self.config

    def should_fail(self) -> bool:
        rate = self.config.error_rate
        return rate > 0 and self._rng.random() < rate


@dataclass
class Lifecycle:
    """Instance-local state behind ``/readyz``."""

    started: bool = False
    draining: bool = False

    def not_ready_reasons(self, faults: FaultInjector) -> list[str]:
        reasons = []
        if not self.started:
            reasons.append("starting")
        if self.draining:
            reasons.append("draining")
        if not faults.config.ready:
            reasons.append("fault_injected")
        return reasons


def health_router(lifecycle: Lifecycle, faults: FaultInjector) -> APIRouter:
    router = APIRouter(tags=["probes"])
    no_store = {"Cache-Control": "no-store"}

    @router.get("/livez")
    async def livez() -> JSONResponse:
        # Only proves the event loop answers. Never checks dependencies: a shared outage would
        # otherwise restart every replica at once.
        return JSONResponse({"status": "alive"}, headers=no_store)

    @router.get("/readyz")
    async def readyz() -> JSONResponse:
        # Instance-local only. Downstream outages degrade responses but must not remove every
        # replica from the Service endpoints.
        reasons = lifecycle.not_ready_reasons(faults)
        if reasons:
            return JSONResponse(
                {"status": "not_ready", "reasons": reasons}, status_code=503, headers=no_store
            )
        return JSONResponse({"status": "ready"}, headers=no_store)

    return router


def admin_router(faults: FaultInjector) -> APIRouter:
    """Fault-injection API. Internal only: never route ``/admin`` through the gateway."""
    router = APIRouter(prefix=ADMIN_PREFIX, tags=["admin"])

    @router.get("/faults")
    async def get_faults() -> FaultConfig:
        return faults.config

    @router.put("/faults")
    async def put_faults(change: FaultUpdate) -> FaultConfig:
        config = faults.update(change)
        logger.warning("fault injection updated", extra={"faults": config.model_dump()})
        return config

    @router.delete("/faults")
    async def reset_faults() -> FaultConfig:
        config = faults.reset()
        logger.warning("fault injection reset", extra={"faults": config.model_dump()})
        return config

    return router


def _is_business_path(path: str) -> bool:
    return path not in PROBE_PATHS and not path.startswith(ADMIN_PREFIX)


class FaultInjectionMiddleware:
    """Adds latency and/or fails a share of business requests with HTTP 500.

    Runs inside the OpenTelemetry server span, so injected latency shows up in
    ``http.server.request.duration`` and injected errors mark the span as failed.
    """

    def __init__(self, app: ASGIApp, faults: FaultInjector) -> None:
        self.app = app
        self.faults = faults

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_business_path(scope["path"]):
            await self.app(scope, receive, send)
            return
        config = self.faults.config
        if config.latency_ms > 0:
            await asyncio.sleep(config.latency_ms / 1000)
        if self.faults.should_fail():
            span = trace.get_current_span()
            span.add_event(
                "fault.injected", {"fault.type": "error", "fault.rate": config.error_rate}
            )
            logger.error(
                "injected fault",
                extra={"http.request.method": scope["method"], "url.path": scope["path"]},
            )
            response = JSONResponse({"detail": "Injected fault"}, status_code=500)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class AccessLogMiddleware:
    """One JSON log line per business request, emitted inside the server span."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in PROBE_PATHS:
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            logger.log(
                logging.ERROR if status >= 500 else logging.INFO,
                "request completed",
                extra={
                    "http.request.method": scope["method"],
                    "http.route": getattr(route, "path", None),
                    "url.path": scope["path"],
                    "http.response.status_code": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )


Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


@dataclass
class ServiceRuntime:
    """Per-app state shared by the probes, fault injection and the server."""

    telemetry: Telemetry
    lifecycle: Lifecycle
    faults: FaultInjector


def create_service_app(
    *,
    title: str,
    version: str,
    telemetry: Telemetry,
    faults: FaultInjector | None = None,
    lifespan: Lifespan | None = None,
    auth: AuthSettings | None = None,
    jwks_transport=None,
) -> FastAPI:
    """FastAPI app with probes, fault injection, access logs and OpenTelemetry instrumentation.

    The runtime is available as ``app.state.runtime`` and the token validation as
    ``app.state.auth`` (``AuthSettings.from_env()`` unless ``auth`` is given; disabled by default).
    ``lifespan`` runs the service's own startup/shutdown; readiness only turns green after it has
    started.
    """
    runtime = ServiceRuntime(
        telemetry=telemetry, lifecycle=Lifecycle(), faults=faults or FaultInjector()
    )

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        if lifespan is None:
            runtime.lifecycle.started = True
            logger.info("service started")
            yield
        else:
            async with lifespan(app):
                runtime.lifecycle.started = True
                logger.info("service started")
                yield
        runtime.lifecycle.started = False
        await authenticator.aclose()
        logger.info("service stopped")

    authenticator = Authenticator(
        auth if auth is not None else AuthSettings.from_env(),
        telemetry,
        jwks_transport=jwks_transport,
    )

    app = FastAPI(title=title, version=version, lifespan=_lifespan)
    app.state.runtime = runtime
    app.state.auth = authenticator
    app.include_router(health_router(runtime.lifecycle, runtime.faults))
    app.include_router(admin_router(runtime.faults))
    # Starlette runs the last added middleware first: access log wraps fault injection.
    app.add_middleware(FaultInjectionMiddleware, faults=runtime.faults)
    app.add_middleware(AccessLogMiddleware)
    instrument_fastapi(app, telemetry)
    return app
