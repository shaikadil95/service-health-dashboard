import asyncio
from typing import Annotated

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, Request
from fastapi.testclient import TestClient

from shd_telemetry import (
    ClientCredentialsAuth,
    ClientCredentialsSettings,
    Principal,
    TokenError,
    authorize,
    create_service_app,
    current_principal,
)
from shd_telemetry.auth import AuthSettings
from shd_telemetry.testing import TestIssuer, in_memory_telemetry


@pytest.fixture
def issuer():
    return TestIssuer()


@pytest.fixture
def otel():
    return in_memory_telemetry("svc")


def make_app(issuer: TestIssuer, otel, audience: str = "shop-api"):
    app = create_service_app(
        title="t",
        version="0",
        telemetry=otel.telemetry,
        auth=issuer.settings(audience),
        jwks_transport=issuer.jwks_transport,
    )

    @app.get("/whoami")
    async def whoami(
        request: Request, principal: Annotated[Principal, Depends(current_principal)]
    ) -> dict:
        authorize(request, principal, principal.has_role("orders:read"), "orders:read required")
        return {"sub": principal.subject, "service_account": principal.is_service_account}

    return app


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_valid_token_is_accepted(issuer, otel):
    with TestClient(make_app(issuer, otel)) as client:
        r = client.get("/whoami", headers=bearer(issuer.customer(sub="c-42")))
    assert r.status_code == 200
    assert r.json() == {"sub": "c-42", "service_account": False}


@pytest.mark.parametrize(
    ("headers", "reason"),
    [
        ({}, "missing_token"),
        ({"Authorization": "Basic Zm9vOmJhcg=="}, "missing_token"),
        ({"Authorization": "Bearer not-a-jwt"}, "invalid_token"),
    ],
)
def test_missing_or_malformed_token_is_401(issuer, otel, headers, reason):
    with TestClient(make_app(issuer, otel)) as client:
        r = client.get("/whoami", headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")
    points = otel.metric_points("auth.failures")
    assert [dict(p.attributes)["reason"] for p in points] == [reason]


def test_token_checks(issuer, otel):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cases = {
        "expired": issuer.customer(expires_in=-120),
        "wrong audience": issuer.customer(aud=["ops-gateway"]),
        "wrong issuer": issuer.token(iss="https://evil.test/realms/customers", aud="shop-api"),
        "forged signature": issuer.customer(key=other_key),
        "unknown kid": issuer.customer(kid="nope"),
    }
    with TestClient(make_app(issuer, otel)) as client:
        for name, token in cases.items():
            r = client.get("/whoami", headers=bearer(token))
            assert r.status_code == 401, name
            assert 'error="invalid_token"' in r.headers["www-authenticate"], name


def test_valid_token_without_role_is_403(issuer, otel):
    with TestClient(make_app(issuer, otel)) as client:
        r = client.get("/whoami", headers=bearer(issuer.customer(roles=["offline_access"])))
    assert r.status_code == 403
    assert 'error="insufficient_scope"' in r.headers["www-authenticate"]


def test_probes_and_admin_never_need_a_token(issuer, otel):
    with TestClient(make_app(issuer, otel)) as client:
        assert client.get("/livez").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert client.get("/admin/faults").status_code == 200


def test_jwks_is_cached(issuer, otel):
    with TestClient(make_app(issuer, otel)) as client:
        for _ in range(5):
            assert client.get("/whoami", headers=bearer(issuer.customer())).status_code == 200
    assert issuer.jwks_requests == 1


def test_auth_disabled_means_anonymous(otel):
    app = create_service_app(
        title="t", version="0", telemetry=otel.telemetry, auth=AuthSettings(enabled=False)
    )

    @app.get("/whoami")
    async def whoami(principal: Annotated[Principal, Depends(current_principal)]) -> dict:
        return {"authenticated": principal.authenticated}

    with TestClient(app) as client:
        assert client.get("/whoami").json() == {"authenticated": False}


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_ISSUER", "https://sso.localtest.me/realms/customers/")
    monkeypatch.setenv("AUTH_AUDIENCES", "user-service, shop-api")
    s = AuthSettings.from_env()
    assert s.issuer == "https://sso.localtest.me/realms/customers"
    assert s.audiences == ("user-service", "shop-api")
    assert s.jwks_url == "https://sso.localtest.me/realms/customers/protocol/openid-connect/certs"
    monkeypatch.delenv("AUTH_AUDIENCES")
    with pytest.raises(ValueError, match="AUTH_AUDIENCES"):
        AuthSettings.from_env()


def test_client_credentials_token_is_cached_and_renewed_on_401(issuer):
    issuer.clients["order-service"] = ("s3cret", {"aud": ["user-service"]})
    auth = ClientCredentialsAuth(
        ClientCredentialsSettings(issuer.token_url, "order-service", "s3cret"),
        transport=issuer.token_transport,
    )
    seen: list[str] = []
    status = iter([200, 200, 401, 200])

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(next(status))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(upstream), auth=auth, base_url="http://user"
        ) as client:
            assert (await client.get("/a")).status_code == 200
            assert (await client.get("/b")).status_code == 200
            # 401 from the upstream: one retry with a fresh token.
            assert (await client.get("/c")).status_code == 200
        await auth.aclose()

    asyncio.run(run())
    assert all(h.startswith("Bearer ") for h in seen)
    assert issuer.token_requests == 2
    assert len(seen) == 4


def test_client_credentials_bad_secret_raises(issuer):
    issuer.clients["order-service"] = ("s3cret", {})
    auth = ClientCredentialsAuth(
        ClientCredentialsSettings(issuer.token_url, "order-service", "wrong"),
        transport=issuer.token_transport,
    )

    async def run():
        with pytest.raises(TokenError):
            await auth.token()
        await auth.aclose()

    asyncio.run(run())
