"""Test helpers: in-memory exporters wired into a ``Telemetry`` without touching globals."""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from .otel import Telemetry, configure_telemetry


@dataclass
class InMemoryTelemetry:
    telemetry: Telemetry
    spans: InMemorySpanExporter
    metrics: InMemoryMetricReader

    def metric_points(self, name: str) -> list:
        """All data points of the metric called ``name`` collected so far."""
        data = self.metrics.get_metrics_data()
        points = []
        for resource_metrics in data.resource_metrics if data else []:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    if metric.name == name:
                        points.extend(metric.data.data_points)
        return points

    def metric_names(self) -> set[str]:
        data = self.metrics.get_metrics_data()
        return {
            metric.name
            for resource_metrics in (data.resource_metrics if data else [])
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
        }


def in_memory_telemetry(service_name: str, service_version: str = "test") -> InMemoryTelemetry:
    spans = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    telemetry = configure_telemetry(
        service_name,
        service_version,
        set_global=False,
        span_processors=[SimpleSpanProcessor(spans)],
        metric_readers=[reader],
    )
    return InMemoryTelemetry(telemetry=telemetry, spans=spans, metrics=reader)


class TestIssuer:
    """A fake OIDC provider for tests: an RSA signing key, its JWKS endpoint and a client
    credentials token endpoint, both served by ``httpx.MockTransport`` (no network)."""

    __test__ = False  # not a pytest test class

    def __init__(self, issuer: str = "https://sso.test/realms/customers", kid: str = "k1") -> None:
        import httpx
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa

        self.issuer = issuer
        self.kid = kid
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key(), as_dict=True)
        jwk.update(kid=kid, use="sig", alg="RS256")
        self.jwks = {"keys": [jwk]}
        self.jwks_requests = 0
        self.token_requests = 0
        # client id -> (secret, claims of its tokens)
        self.clients: dict[str, tuple[str, dict]] = {}

        def jwks_handler(request: httpx.Request) -> httpx.Response:
            self.jwks_requests += 1
            return httpx.Response(200, json=self.jwks)

        def token_handler(request: httpx.Request) -> httpx.Response:
            import base64
            from urllib.parse import parse_qs

            self.token_requests += 1
            form = parse_qs(request.content.decode())
            scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
            client_id, _, secret = base64.b64decode(credentials).decode().partition(":")
            known = self.clients.get(client_id)
            if (
                scheme != "Basic"
                or known is None
                or known[0] != secret
                or form.get("grant_type") != ["client_credentials"]
            ):
                return httpx.Response(401, json={"error": "invalid_client"})
            token = self.token(
                sub=f"sa-{client_id}",
                preferred_username=f"service-account-{client_id}",
                azp=client_id,
                **known[1],
            )
            return httpx.Response(200, json={"access_token": token, "expires_in": 300})

        self.jwks_transport = httpx.MockTransport(jwks_handler)
        self.token_transport = httpx.MockTransport(token_handler)

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/certs"

    @property
    def token_url(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/token"

    def settings(self, *audiences: str):
        from .auth import AuthSettings

        return AuthSettings(
            enabled=True, issuer=self.issuer, audiences=audiences, jwks_url=self.jwks_url
        )

    def token(self, *, expires_in: int = 300, key=None, kid: str | None = None, **claims) -> str:
        import time

        import jwt

        now = int(time.time())
        payload = {"iss": self.issuer, "iat": now, "exp": now + expires_in, **claims}
        payload.setdefault("sub", "user-1")
        return jwt.encode(
            payload, key or self._key, algorithm="RS256", headers={"kid": kid or self.kid}
        )

    def customer(self, sub: str = "c-1", roles=("orders:read", "orders:write"), **claims) -> str:
        """A customer's access token as Keycloak issues it for the shop (audience shop-api)."""
        return self.token(
            sub=sub,
            preferred_username=claims.pop("preferred_username", "ada"),
            azp="shop-gateway",
            aud=claims.pop("aud", ["shop-api", "account"]),
            realm_access={"roles": list(roles)},
            **claims,
        )
