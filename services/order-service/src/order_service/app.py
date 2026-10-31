from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, model_validator

from shd_telemetry import FaultInjector, Telemetry, create_service_app, instrument_httpx_client

from . import __version__
from .upstream import (
    UpstreamError,
    UpstreamSettings,
    build_clients,
    map_transport_error,
    unexpected_response,
)

logger = logging.getLogger("order_service")

Currency = Literal["EUR", "USD", "GBP"]  # same allow-list as the Payment API
# Same ceiling as the Payment API, so that oversize orders are a 422 here and not a 502 later.
MAX_ORDER_TOTAL = Decimal("1000000")
OrderStatus = Literal["confirmed", "payment_declined", "payment_failed", "payment_unknown"]


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=100)
    unit_price: Decimal = Field(gt=0, le=100_000, decimal_places=2)


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Restricted charset: the ID is interpolated into the User service URL path.
    user_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    items: list[OrderItem] = Field(min_length=1, max_length=50)
    currency: Currency = "EUR"

    @property
    def total(self) -> Decimal:
        return sum((item.unit_price * item.quantity for item in self.items), Decimal("0"))

    @model_validator(mode="after")
    def _check_total(self) -> OrderRequest:
        if self.total > MAX_ORDER_TOTAL:
            raise ValueError(f"order total must not exceed {MAX_ORDER_TOTAL}")
        return self


class Order(BaseModel):
    id: str
    user_id: str
    items: list[OrderItem]
    total: Decimal
    currency: str
    status: OrderStatus
    payment_id: str | None = None
    created_at: datetime


class OrderMetrics:
    def __init__(self, telemetry: Telemetry) -> None:
        meter = telemetry.meter_provider.get_meter("order_service", __version__)
        # Exposed by Prometheus' OTLP translation as `orders_created_total`.
        self.created = meter.create_counter(
            "orders.created", unit="{order}", description="Orders created (payment approved)."
        )


def create_app(
    telemetry: Telemetry,
    faults: FaultInjector | None = None,
    settings: UpstreamSettings | None = None,
    user_transport: httpx.AsyncBaseTransport | None = None,
    payment_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or UpstreamSettings.from_env()
    metrics = OrderMetrics(telemetry)
    orders: dict[str, Order] = {}
    clients: dict[str, httpx.AsyncClient] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        user_client, payment_client = build_clients(settings, user_transport, payment_transport)
        for client in (user_client, payment_client):
            instrument_httpx_client(client, telemetry)
        clients.update(user=user_client, payment=payment_client)
        try:
            yield
        finally:
            await user_client.aclose()
            await payment_client.aclose()

    app = create_service_app(
        title="Order service",
        version=__version__,
        telemetry=telemetry,
        faults=faults,
        lifespan=lifespan,
    )

    @app.exception_handler(UpstreamError)
    async def upstream_error_handler(_: Request, exc: UpstreamError) -> JSONResponse:
        logger.error(
            "upstream call failed",
            extra={"upstream": exc.upstream, "http.response.status_code": exc.status_code},
        )
        body = {"detail": exc.detail, "upstream": exc.upstream}
        headers = {}
        if exc.order_id is not None:
            # The order was stored (payment_failed/payment_unknown): let the client find it
            # instead of retrying blindly and creating a second order.
            body["order_id"] = exc.order_id
            headers["Location"] = f"/orders/{exc.order_id}"
        return JSONResponse(body, exc.status_code, headers=headers)

    async def fetch_user(user_id: str) -> dict:
        try:
            response = await clients["user"].get(f"/users/{user_id}")
        except httpx.TransportError as exc:
            raise map_transport_error("user", exc) from exc
        if response.status_code == 404:
            raise HTTPException(422, "Unknown user")
        if response.status_code != 200:
            raise unexpected_response("user", response)
        return response.json()

    async def charge(order: Order) -> httpx.Response:
        try:
            response = await clients["payment"].post(
                "/payments",
                json={
                    "order_id": order.id,
                    "amount": str(order.total),
                    "currency": order.currency,
                },
                headers={"Idempotency-Key": f"order-{order.id}"},
            )
        except httpx.TransportError as exc:
            raise map_transport_error("payment", exc) from exc
        if response.status_code not in (201, 402):
            raise unexpected_response("payment", response)
        return response

    @app.post("/orders", tags=["orders"], status_code=201, response_model=Order)
    async def create_order(request: OrderRequest) -> JSONResponse:
        user = await fetch_user(request.user_id)
        if user.get("status") != "active":
            raise HTTPException(422, "User is not active")

        total = request.total
        order = Order(
            id=uuid.uuid4().hex[:12],
            user_id=request.user_id,
            items=request.items,
            total=total,
            currency=request.currency,
            status="payment_failed",
            created_at=datetime.now(UTC),
        )
        trace.get_current_span().set_attribute("app.order.id", order.id)
        try:
            response = await charge(order)
        except UpstreamError as exc:
            order.status = "payment_unknown" if exc.outcome_unknown else "payment_failed"
            orders[order.id] = order
            exc.order_id = order.id
            logger.error("order payment failed", extra={"order.id": order.id})
            raise

        payment = response.json()
        order.payment_id = payment.get("id")
        if response.status_code == 201:
            order.status = "confirmed"
            metrics.created.add(1)
        else:
            order.status = "payment_declined"
        orders[order.id] = order
        logger.info("order processed", extra={"order.id": order.id, "order.status": order.status})
        return JSONResponse(
            order.model_dump(mode="json"),
            status_code=201 if order.status == "confirmed" else 402,
            headers={"Location": f"/orders/{order.id}"},
        )

    @app.get("/orders/{order_id}", tags=["orders"])
    async def get_order(order_id: str) -> Order:
        order = orders.get(order_id)
        if order is None:
            raise HTTPException(404, "Order not found")
        return order

    return app
