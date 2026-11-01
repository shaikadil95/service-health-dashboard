from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response

from shd_telemetry import Telemetry, create_service_app, instrument_httpx_client
from shd_telemetry.auth import AuthSettings, Principal, current_principal

from . import __version__
from .config import Settings
from .models import AlertsResponse, Me, ServicesResponse, ServiceStatus
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

    @router.get("/me", responses={404: {"description": "No signed-in user"}})
    async def me(
        response: Response, principal: Annotated[Principal, Depends(current_principal)]
    ) -> Me:
        """The signed-in engineer, from the access token that the gateway forwards (validated again
        here: signature, ``iss``, ``aud``, ``exp``). The page shows the name and the groups."""
        cache_control(response)
        if not principal.authenticated:
            raise HTTPException(status_code=404, detail="No signed-in user")
        return Me(
            username=principal.username or principal.subject,
            name=principal.name,
            email=principal.email,
            groups=sorted(principal.groups),
        )

    return router


def create_app(
    telemetry: Telemetry,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    auth: AuthSettings | None = None,
    jwks_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """``transport`` and ``jwks_transport`` replace the network in tests (httpx.MockTransport);
    ``auth`` defaults to ``AuthSettings.from_env()`` (only ``/api/v1/me`` reads the token)."""

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
        title="Status API",
        version=__version__,
        telemetry=telemetry,
        lifespan=lifespan,
        auth=auth,
        jwks_transport=jwks_transport,
    )
    app.include_router(_router())
    return app
