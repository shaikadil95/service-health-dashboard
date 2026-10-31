import random
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry import context as otel_context
from opentelemetry.trace import SpanKind, StatusCode

from order_service.app import create_app
from order_service.upstream import UpstreamSettings
from payment_service.app import create_app as create_payment_app
from shd_telemetry import FaultConfig, FaultInjector
from shd_telemetry.testing import InMemoryTelemetry, in_memory_telemetry
from user_service.app import create_app as create_user_app

SETTINGS = UpstreamSettings(
    user_url="http://user",
    payment_url="http://payment",
    user_timeout=1,
    payment_timeout=1,
    connect_timeout=1,
)
ORDER = {"user_id": "u-1001", "items": [{"sku": "book", "quantity": 2, "unit_price": "12.50"}]}


def _isolated(app):
    """Run a downstream app with an empty OTel context, like a separate process.

    Without this the in-process call would inherit Order's span through contextvars, and the
    test would not prove that the W3C ``traceparent`` header carries the context.
    """

    async def asgi(scope, receive, send):
        token = otel_context.attach(otel_context.Context())
        try:
            await app(scope, receive, send)
        finally:
            otel_context.detach(token)

    return asgi


def _faults() -> FaultInjector:
    return FaultInjector(FaultConfig(), rng=random.Random(1))


class System:
    """Order service wired in-process to real User and Payment apps over ASGI."""

    def __init__(self, payment_transport: httpx.AsyncBaseTransport | None = None):
        self.otel: dict[str, InMemoryTelemetry] = {
            name: in_memory_telemetry(name) for name in ("order", "user", "payment")
        }
        self.user_app = create_user_app(self.otel["user"].telemetry, faults=_faults())
        self.payment_app = create_payment_app(
            self.otel["payment"].telemetry, faults=_faults(), approval_limit=Decimal("1000")
        )
        self.order_app = create_app(
            self.otel["order"].telemetry,
            faults=_faults(),
            settings=SETTINGS,
            user_transport=httpx.ASGITransport(_isolated(self.user_app)),
            payment_transport=payment_transport or httpx.ASGITransport(_isolated(self.payment_app)),
        )

    def spans(self, service: str):
        return self.otel[service].spans.get_finished_spans()


@pytest.fixture
def system():
    return System()


@pytest.fixture
def client(system):
    with TestClient(system.order_app) as client:
        yield client


def _mock(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _client_with_payment(handler) -> tuple[System, TestClient]:
    system = System(payment_transport=_mock(handler))
    return system, TestClient(system.order_app)


def test_order_confirmed(client, system):
    response = client.post("/orders", json=ORDER)
    assert response.status_code == 201
    order = response.json()
    assert order["status"] == "confirmed"
    assert order["total"] == "25.00"
    assert order["payment_id"].startswith("pay-")
    assert response.headers["location"] == f"/orders/{order['id']}"
    assert client.get(f"/orders/{order['id']}").json() == order
    [created] = system.otel["order"].metric_points("orders.created")
    assert created.value == 1


def test_one_distributed_trace_across_three_services(client, system):
    assert client.post("/orders", json=ORDER).status_code == 201

    order_spans = system.spans("order")
    [server] = [s for s in order_spans if s.kind is SpanKind.SERVER]
    client_spans = {s.name: s for s in order_spans if s.kind is SpanKind.CLIENT}
    assert set(client_spans) == {"GET", "POST"}
    [user_server] = [s for s in system.spans("user") if s.kind is SpanKind.SERVER]
    [payment_server] = [s for s in system.spans("payment") if s.kind is SpanKind.SERVER]

    trace_id = server.context.trace_id
    for span in (*client_spans.values(), user_server, payment_server):
        assert span.context.trace_id == trace_id
    # W3C traceparent: each downstream server span is a child of Order's client span.
    assert user_server.parent.span_id == client_spans["GET"].context.span_id
    assert payment_server.parent.span_id == client_spans["POST"].context.span_id
    assert user_server.parent.is_remote
    assert payment_server.parent.is_remote
    assert user_server.name == "GET /users/{user_id}"
    assert payment_server.name == "POST /payments"
    assert user_server.resource.attributes["service.name"] == "user"
    assert "http.client.request.duration" in system.otel["order"].metric_names()


def test_payment_request_carries_idempotency_key_and_traceparent():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": "pay-1", "status": "approved"})

    _, client = _client_with_payment(handler)
    with client:
        order = client.post("/orders", json=ORDER).json()
    [request] = seen
    assert request.headers["idempotency-key"] == f"order-{order['id']}"
    version, trace_id, _span_id, flags = request.headers["traceparent"].split("-")
    assert version == "00"
    assert int(flags, 16) & 0x01, "sampled flag must be propagated"
    assert len(trace_id) == 32


@pytest.mark.parametrize(
    ("user_id", "detail"), [("u-9999", "Unknown user"), ("u-1004", "User is not active")]
)
def test_invalid_user_is_client_error_and_no_payment(client, system, user_id, detail):
    response = client.post("/orders", json={**ORDER, "user_id": user_id})
    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert system.spans("payment") == ()


def test_payment_declined_is_402(client, system):
    expensive = {**ORDER, "items": [{"sku": "car", "quantity": 1, "unit_price": "5000.00"}]}
    response = client.post("/orders", json=expensive)
    assert response.status_code == 402
    assert response.json()["status"] == "payment_declined"
    assert system.otel["order"].metric_points("orders.created") == []


def test_payment_fault_returns_502_with_error_spans(client, system):
    system.payment_app.state.runtime.faults.config = FaultConfig(error_rate=1.0)
    response = client.post("/orders", json=ORDER)
    assert response.status_code == 502
    order_id = response.json()["order_id"]
    assert response.json() == {
        "detail": "payment service returned HTTP 500",
        "upstream": "payment",
        "order_id": order_id,
    }
    assert response.headers["location"] == f"/orders/{order_id}"
    [payment_server] = system.spans("payment")
    assert payment_server.status.status_code is StatusCode.ERROR
    order_spans = system.spans("order")
    [server] = [s for s in order_spans if s.kind is SpanKind.SERVER]
    [post] = [s for s in order_spans if s.name == "POST"]
    assert server.status.status_code is StatusCode.ERROR
    assert server.attributes["http.response.status_code"] == 502
    assert post.status.status_code is StatusCode.ERROR
    assert server.attributes["app.order.id"] == order_id
    assert client.get(f"/orders/{order_id}").json()["status"] == "payment_unknown"


def test_user_service_fault_returns_502(client, system):
    system.user_app.state.runtime.faults.config = FaultConfig(error_rate=1.0)
    response = client.post("/orders", json=ORDER)
    assert response.status_code == 502
    assert response.json()["upstream"] == "user"


@pytest.mark.parametrize(
    ("exc", "status", "order_status"),
    [
        (httpx.ConnectError("refused"), 503, "payment_failed"),
        (httpx.ConnectTimeout("slow connect"), 503, "payment_failed"),
        (httpx.ReadTimeout("slow"), 504, "payment_unknown"),
        (httpx.RemoteProtocolError("reset"), 502, "payment_unknown"),
    ],
)
def test_payment_transport_failures(exc, status, order_status):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise exc

    _, client = _client_with_payment(handler)
    with client:
        response = client.post("/orders", json=ORDER)
        assert response.status_code == status
        assert response.json()["upstream"] == "payment"
        order_id = response.json()["order_id"]
        assert client.get(f"/orders/{order_id}").json()["status"] == order_status
    assert calls == 1, "the payment POST must not be retried"


@pytest.mark.parametrize(
    ("exc", "status"),
    [(httpx.ConnectError("refused"), 503), (httpx.ReadTimeout("slow"), 504)],
)
def test_user_transport_failures(exc, status):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    system = System()
    system.order_app = create_app(
        system.otel["order"].telemetry,
        faults=_faults(),
        settings=SETTINGS,
        user_transport=_mock(handler),
        payment_transport=httpx.ASGITransport(_isolated(system.payment_app)),
    )
    with TestClient(system.order_app) as client:
        response = client.post("/orders", json=ORDER)
    assert response.status_code == status
    assert response.json()["upstream"] == "user"
    assert "order_id" not in response.json(), "no order is stored before the user is validated"


def test_downstream_outage_does_not_affect_probes():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    _, client = _client_with_payment(handler)
    with client:
        assert client.post("/orders", json=ORDER).status_code == 503
        assert client.get("/readyz").status_code == 200
        assert client.get("/livez").status_code == 200


def test_unknown_order_is_404(client):
    assert client.get("/orders/nope").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {**ORDER, "items": []},
        {**ORDER, "items": [{"sku": "x", "quantity": 0, "unit_price": "1.00"}]},
        {**ORDER, "currency": "euro"},
        {**ORDER, "currency": "JPY"},
        {"items": ORDER["items"]},
        {**ORDER, "user_id": "../admin/faults"},
        {**ORDER, "items": [{"sku": "x", "quantity": 100, "unit_price": "10000.01"}]},
    ],
)
def test_invalid_order_is_422(client, system, body):
    assert client.post("/orders", json=body).status_code == 422
    assert system.spans("user") == ()
