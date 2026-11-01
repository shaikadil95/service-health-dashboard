from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, model_validator

from shd_telemetry import (
    AuthSettings,
    ClientCredentialsAuth,
    ClientCredentialsSettings,
    FaultInjector,
    Principal,
    Telemetry,
    TokenError,
    authorize,
    create_service_app,
    current_principal,
    end_user_headers,
    instrument_httpx_client,
)

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
# Realm roles of Keycloak's customers realm: every customer has both; the load generator's
# service account too.
ORDERS_READ = "orders:read"
ORDERS_WRITE = "orders:write"


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=100)
    unit_price: Decimal = Field(gt=0, le=100_000, decimal_places=2)


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Restricted charset: the ID is interpolated into the User service URL path. Optional for a
    # signed-in customer, whose orders always belong to the token's subject.
    user_id: str | None = Field(None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
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
    auth: AuthSettings | None = None,
    jwks_transport=None,
    client_credentials: ClientCredentialsSettings | None = None,
    token_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or UpstreamSettings.from_env()
    credentials = client_credentials or ClientCredentialsSettings.from_env()
    metrics = OrderMetrics(telemetry)
    orders: dict[str, Order] = {}
    clients: dict[str, httpx.AsyncClient] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Calls to User and Payment carry Order's own client-credentials token (not the
        # customer's): they are authorized as "the order service", for the audit the customer's
        # subject travels in X-End-User-Sub.
        upstream_auth = (
            ClientCredentialsAuth(credentials, transport=token_transport) if credentials else None
        )
        if upstream_auth is not None:
            instrument_httpx_client(upstream_auth.client, telemetry)
        user_client, payment_client = build_clients(
            settings, user_transport, payment_transport, auth=upstream_auth
        )
        for client in (user_client, payment_client):
            instrument_httpx_client(client, telemetry)
        clients.update(user=user_client, payment=payment_client)
        try:
            yield
        finally:
            await user_client.aclose()
            await payment_client.aclose()
            if upstream_auth is not None:
                await upstream_auth.aclose()

    app = create_service_app(
        title="Order service",
        version=__version__,
        telemetry=telemetry,
        faults=faults,
        lifespan=lifespan,
        auth=auth,
        jwks_transport=jwks_transport,
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

    async def fetch_user(user_id: str, principal: Principal) -> dict:
        try:
            response = await clients["user"].get(
                f"/users/{user_id}", headers=end_user_headers(principal)
            )
        except httpx.TransportError as exc:
            raise map_transport_error("user", exc) from exc
        except TokenError as exc:
            raise UpstreamError("user", 503, "user service: no access token") from exc
        if response.status_code == 404:
            raise HTTPException(422, "Unknown user")
        if response.status_code != 200:
            raise unexpected_response("user", response)
        return response.json()

    async def charge(order: Order, principal: Principal) -> httpx.Response:
        try:
            response = await clients["payment"].post(
                "/payments",
                json={
                    "order_id": order.id,
                    "amount": str(order.total),
                    "currency": order.currency,
                },
                headers={"Idempotency-Key": f"order-{order.id}", **end_user_headers(principal)},
            )
        except httpx.TransportError as exc:
            raise map_transport_error("payment", exc) from exc
        except TokenError as exc:
            raise UpstreamError("payment", 503, "payment service: no access token") from exc
        if response.status_code not in (201, 402):
            raise unexpected_response("payment", response)
        return response

    def customer_of(principal: Principal) -> str | None:
        """The customer a signed-in user may act for (None: any customer, i.e. a service account
        such as the load generator, or authentication disabled)."""
        if principal.authenticated and not principal.is_service_account:
            return principal.subject
        return None

    @app.post("/orders", tags=["orders"], status_code=201, response_model=Order)
    async def create_order(
        request: OrderRequest,
        http_request: Request,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> JSONResponse:
        authorize(
            http_request, principal, principal.has_role(ORDERS_WRITE), "orders:write required"
        )
        customer = customer_of(principal)
        if customer is not None:
            if request.user_id not in (None, customer):
                authorize(http_request, principal, False, "customers can only order for themselves")
            user_id = customer
        elif request.user_id is None:
            raise HTTPException(422, "user_id is required")
        else:
            user_id = request.user_id

        user = await fetch_user(user_id, principal)
        if user.get("status") != "active":
            raise HTTPException(422, "User is not active")

        total = request.total
        order = Order(
            id=uuid.uuid4().hex[:12],
            user_id=user_id,
            items=request.items,
            total=total,
            currency=request.currency,
            status="payment_failed",
            created_at=datetime.now(UTC),
        )
        trace.get_current_span().set_attribute("app.order.id", order.id)
        try:
            response = await charge(order, principal)
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

    @app.get("/orders", tags=["orders"])
    async def list_orders(
        http_request: Request,
        principal: Annotated[Principal, Depends(current_principal)],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> list[Order]:
        """Newest first: a customer's own orders, or all orders for a service account."""
        authorize(http_request, principal, principal.has_role(ORDERS_READ), "orders:read required")
        customer = customer_of(principal)
        selected = [o for o in orders.values() if customer is None or o.user_id == customer]
        return sorted(selected, key=lambda o: o.created_at, reverse=True)[:limit]

    @app.get("/orders/{order_id}", tags=["orders"])
    async def get_order(
        order_id: str,
        http_request: Request,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Order:
        authorize(http_request, principal, principal.has_role(ORDERS_READ), "orders:read required")
        order = orders.get(order_id)
        customer = customer_of(principal)
        # Another customer's order is "not found", not "forbidden": its ID is not disclosed.
        if order is None or (customer is not None and order.user_id != customer):
            raise HTTPException(404, "Order not found")
        return order

    return app
