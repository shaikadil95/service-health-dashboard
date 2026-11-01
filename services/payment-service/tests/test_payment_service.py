from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from payment_service.app import create_app
from shd_telemetry import FaultConfig, FaultInjector
from shd_telemetry.testing import in_memory_telemetry


@pytest.fixture
def otel():
    return in_memory_telemetry("payment")


@pytest.fixture
def client(otel):
    app = create_app(
        otel.telemetry, faults=FaultInjector(FaultConfig()), approval_limit=Decimal("100")
    )
    with TestClient(app) as client:
        yield client


def _pay(client, amount="42.50", key="k-1", **overrides):
    body = {"order_id": "o-1", "amount": amount, "currency": "EUR", **overrides}
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/payments", json=body, headers=headers)


def _counts(otel) -> dict[str, int]:
    return {p.attributes["result"]: p.value for p in otel.metric_points("payments.processed")}


def test_payment_approved(client, otel):
    response = _pay(client)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "approved"
    assert body["amount"] == "42.50"
    assert body["id"].startswith("pay-")
    assert _counts(otel) == {"approved": 1}
    [amount] = otel.metric_points("payment.amount")
    assert amount.sum == 42.5
    assert dict(amount.attributes) == {"currency": "EUR", "result": "approved"}


def test_payment_declined_over_limit(client, otel):
    response = _pay(client, amount="100.01")
    assert response.status_code == 402
    assert response.json()["status"] == "declined"
    assert response.json()["decline_reason"] == "amount_limit_exceeded"
    assert _counts(otel) == {"declined": 1}


def test_idempotent_replay_returns_same_payment_once(client, otel):
    first = _pay(client, key="same")
    second = _pay(client, key="same")
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.headers["idempotent-replayed"] == "true"
    assert "idempotent-replayed" not in first.headers
    assert _counts(otel) == {"approved": 1}, "a replay must not be counted twice"


def test_idempotency_key_reuse_with_other_payload_is_rejected(client):
    _pay(client, key="same")
    response = _pay(client, key="same", amount="1.00")
    assert response.status_code == 422


def test_idempotency_key_is_required(client):
    response = _pay(client, key=None)
    assert response.status_code == 400
    assert response.json()["detail"] == "Idempotency-Key header is required"


@pytest.mark.parametrize(
    "override",
    [
        {"amount": "-1"},
        {"amount": "0"},
        {"amount": "1.001"},
        {"currency": "eur"},
        {"currency": "JPY"},
        {"extra": 1},
    ],
)
def test_invalid_payment_is_422(client, override):
    assert _pay(client, **override).status_code == 422


def test_metric_attributes_have_low_cardinality(client, otel):
    for i in range(5):
        _pay(client, key=f"k-{i}", order_id=f"o-{i}")
    for name in ("payments.processed", "payment.amount"):
        for point in otel.metric_points(name):
            assert set(point.attributes) <= {"result", "currency"}
    assert _counts(otel) == {"approved": 5}
