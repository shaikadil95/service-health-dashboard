from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response

from shd_telemetry import Telemetry, create_service_app, instrument_httpx_client

from . import __version__
from .config import Settings
from .models import AlertsResponse, ServicesResponse, ServiceStatus
from .service import StatusService
from .sources import AlertmanagerClient, PrometheusClient

# The server already caches for cache_ttl_seconds; a browser cache on top would only add staleness.
NO_STORE = {"Cache-Control": "no-store"}


def _router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["status"])

    def status_service(request: Request) -> StatusService:
        return request.app.state.status_service

    def cache_control(response: Response) -> None:
        response.headers.update(NO_STORE)

    @router.get("/services")
    async def list_services(request: Request, response: Response) -> ServicesResponse:
        """All services with status, reasons, metrics, sparkline series and alerts."""
        cache_control(response)
        return (await status_service(request).snapshot()).services

    @router.get("/services/{name}", responses={404: {"description": "Unknown service"}})
    async def get_service(name: str, request: Request, response: Response) -> ServiceStatus:
        cache_control(response)
        snapshot = await status_service(request).snapshot()
        for service in snapshot.services.services:
            if service.name == name:
                return service
        raise HTTPException(status_code=404, detail="Unknown service")

    @router.get("/alerts")
    async def list_alerts(request: Request, response: Response) -> AlertsResponse:
        """Active (not silenced, not inhibited) alerts with a reduced set of fields."""
        cache_control(response)
        return (await status_service(request).snapshot()).alerts

    return router


def create_app(
    telemetry: Telemetry,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """``transport`` replaces the network in tests (httpx.MockTransport)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = httpx.AsyncClient(
            transport=transport,
            timeout=settings.query_timeout_seconds,
            headers={"User-Agent": f"status-api/{__version__}"},
        )
        instrument_httpx_client(client, telemetry)
        app.state.status_service = StatusService(
            settings=settings,
            prometheus=PrometheusClient(
                client, settings.prometheus_url, settings.query_timeout_seconds
            ),
            alertmanager=AlertmanagerClient(
                client, settings.alertmanager_url, settings.query_timeout_seconds
            ),
        )
        try:
            yield
        finally:
            await client.aclose()

    # /readyz only reflects this process (started, not draining): the API keeps answering with
    # UNKNOWN when Prometheus or Alertmanager is down, so it must stay in the Service endpoints.
    app = create_service_app(
        title="Status API", version=__version__, telemetry=telemetry, lifespan=lifespan
    )
    app.include_router(_router())
    return app
