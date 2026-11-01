import pytest
from fastapi.testclient import TestClient

from shd_telemetry import FaultConfig, FaultInjector
from shd_telemetry.testing import in_memory_telemetry
from user_service.app import SEED_USERS, create_app


@pytest.fixture
def client():
    app = create_app(in_memory_telemetry("user").telemetry, faults=FaultInjector(FaultConfig()))
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("user", SEED_USERS, ids=lambda u: u.id)
def test_get_seeded_user(client, user):
    response = client.get(f"/users/{user.id}")
    assert response.status_code == 200
    assert response.json() == user.model_dump()


def test_unknown_user_is_404(client):
    response = client.get("/users/u-9999")
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_probes(client):
    assert client.get("/livez").status_code == 200
    assert client.get("/readyz").status_code == 200
