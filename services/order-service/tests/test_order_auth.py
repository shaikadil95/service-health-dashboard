"""Order, User and Payment with authentication on, wired in-process like in test_order_service:
a customer token for Order, Order's own client-credentials token for User and Payment."""

import random
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from order_service.app import create_app
from order_service.upstream import UpstreamSettings
from payment_service.app import create_app as create_payment_app
from shd_telemetry import ClientCredentialsSettings, FaultConfig, FaultInjector
from shd_telemetry.testing import TestIssuer, in_memory_telemetry
from user_service.app import create_app as create_user_app

SETTINGS = UpstreamSettings("http://user", "http://payment", 1, 1, 1)
ITEMS = [{"sku": "book", "quantity": 1, "unit_price": "10.00"}]


def _faults():
    return FaultInjector(FaultConfig(), rng=random.Random(1))


class AuthSystem:
    def __init__(self, order_secret: str = "order-secret"):
        self.issuer = TestIssuer()
        i = self.issuer
        # Keycloak: order-service's service account holds users:read and payments:write.
        i.clients["order-service"] = (
            "order-secret",
            {
                "aud": ["user-service", "payment-service"],
                "resource_access": {
                    "user-service": {"roles": ["users:read"]},
                    "payment-service": {"roles": ["payments:write"]},
                },
            },
        )
        otel = {n: in_memory_telemetry(n) for n in ("order", "user", "payment")}
        self.user_app = create_user_app(
            otel["user"].telemetry,
            faults=_faults(),
            auth=i.settings("user-service", "shop-api"),
            jwks_transport=i.jwks_transport,
        )
        self.payment_app = create_payment_app(
            otel["payment"].telemetry,
            faults=_faults(),
            approval_limit=Decimal("1000"),
            auth=i.settings("payment-service"),
            jwks_transport=i.jwks_transport,
        )
        self.order_app = create_app(
            otel["order"].telemetry,
            faults=_faults(),
            settings=SETTINGS,
            user_transport=httpx.ASGITransport(self.user_app),
            payment_transport=httpx.ASGITransport(self.payment_app),
            auth=i.settings("shop-api"),
            jwks_transport=i.jwks_transport,
            client_credentials=ClientCredentialsSettings(
                i.token_url, "order-service", order_secret
            ),
            token_transport=i.token_transport,
        )


@pytest.fixture
def system():
    s = AuthSystem()
    with TestClient(s.user_app), TestClient(s.payment_app):
        yield s


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_no_token_is_401(system):
    with TestClient(system.order_app) as client:
        r = client.post("/orders", json={"items": ITEMS})
    assert r.status_code == 401


def test_customer_orders_for_themselves(system):
    i = system.issuer
    with TestClient(system.user_app) as users:
        # The shop loads the profile first (/api/me), which provisions the customer.
        me = users.get("/users/me", headers=bearer(i.customer(sub="c-1", name="Ada Customer")))
        assert me.status_code == 200
        assert me.json()["name"] == "Ada Customer"
    with TestClient(system.order_app) as client:
        token = i.customer(sub="c-1")
        created = client.post("/orders", json={"items": ITEMS}, headers=bearer(token))
        assert created.status_code == 201, created.text
        assert created.json()["user_id"] == "c-1"
        # Ordering for someone else is forbidden.
        other = client.post(
            "/orders", json={"user_id": "u-1001", "items": ITEMS}, headers=bearer(token)
        )
        assert other.status_code == 403
        # Listing shows only the caller's orders; another customer does not see them.
        mine = client.get("/orders", headers=bearer(token)).json()
        assert [o["id"] for o in mine] == [created.json()["id"]]
        stranger = i.customer(sub="c-2")
        assert client.get("/orders", headers=bearer(stranger)).json() == []
        assert (
            client.get(f"/orders/{created.json()['id']}", headers=bearer(stranger)).status_code
            == 404
        )


def test_customer_without_orders_write_is_403(system):
    with TestClient(system.order_app) as client:
        token = system.issuer.customer(roles=["orders:read"])
        assert (
            client.post("/orders", json={"items": ITEMS}, headers=bearer(token)).status_code == 403
        )
        assert client.get("/orders", headers=bearer(token)).status_code == 200


def test_service_account_orders_for_a_named_user(system):
    i = system.issuer
    loadgen = i.token(
        sub="sa-loadgen",
        preferred_username="service-account-loadgen",
        azp="loadgen",
        aud=["shop-api"],
        realm_access={"roles": ["orders:read", "orders:write"]},
    )
    with TestClient(system.order_app) as client:
        assert (
            client.post("/orders", json={"items": ITEMS}, headers=bearer(loadgen)).status_code
            == 422
        )
        r = client.post(
            "/orders", json={"user_id": "u-1001", "items": ITEMS}, headers=bearer(loadgen)
        )
        assert r.status_code == 201, r.text
        assert r.json()["user_id"] == "u-1001"
    # One client-credentials token for both upstream calls.
    assert i.token_requests == 1


def test_upstreams_reject_order_without_its_service_token():
    s = AuthSystem(order_secret="wrong")
    with TestClient(s.user_app), TestClient(s.payment_app), TestClient(s.order_app) as client:
        r = client.post(
            "/orders",
            json={"user_id": "u-1001", "items": ITEMS},
            headers=bearer(
                s.issuer.token(
                    preferred_username="service-account-loadgen",
                    aud=["shop-api"],
                    realm_access={"roles": ["orders:write"]},
                )
            ),
        )
    # Order could not get a token for User: an upstream failure (503), not the client's fault.
    assert r.status_code == 503
    assert r.json() == {"detail": "user service: no access token", "upstream": "user"}


def test_user_and_payment_authorization(system):
    i = system.issuer
    customer = i.customer(sub="c-9")
    with TestClient(system.user_app) as users:
        assert users.get("/users/u-1001").status_code == 401
        assert users.get("/users/u-1001", headers=bearer(customer)).status_code == 403
        service = i.token(
            preferred_username="service-account-order-service",
            aud=["user-service"],
            resource_access={"user-service": {"roles": ["users:read"]}},
        )
        assert users.get("/users/u-1001", headers=bearer(service)).status_code == 200
        # Service accounts have no profile of their own.
        assert users.get("/users/me", headers=bearer(service)).status_code == 403
    with TestClient(system.payment_app) as payments:
        body = {"order_id": "o-1", "amount": "1.00", "currency": "EUR"}
        headers = {"Idempotency-Key": "k1"}
        # A customer token is not even for this audience.
        assert (
            payments.post(
                "/payments", json=body, headers={**headers, **bearer(customer)}
            ).status_code
            == 401
        )
        wrong_role = i.token(
            preferred_username="service-account-x",
            aud=["payment-service"],
            resource_access={"payment-service": {"roles": []}},
        )
        assert (
            payments.post(
                "/payments", json=body, headers={**headers, **bearer(wrong_role)}
            ).status_code
            == 403
        )
