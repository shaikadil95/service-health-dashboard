"""OAuth 2.0 / OIDC for the services: JWT access-token validation and client credentials.

Inbound (``Authenticator``): a FastAPI dependency validates the ``Authorization: Bearer`` token of
every business request against the identity provider's JSON Web Key Set (cached), and checks
``iss``, ``aud``, ``exp``/``nbf``/``iat`` with a small leeway. Endpoints then authorize on realm
roles (``realm_access.roles``) or client roles (``resource_access.<client>.roles``) of the
:class:`Principal`. Probes and ``/admin`` never require a token: they are not routed through the
gateway, and NetworkPolicies restrict who can reach them.

Outbound (``ClientCredentialsAuth``): an ``httpx.Auth`` that fetches and caches a token with the
client credentials grant (RFC 6749, section 4.4) for calls between services.

401 (no or invalid token) and 403 (valid token, missing permission) are client errors: they show
up as 4xx in ``http.server.request.duration`` and in ``auth.failures``, never as 5xx.

Configuration comes from the environment (``AuthSettings.from_env``,
``ClientCredentialsSettings.from_env``). With ``AUTH_ENABLED`` unset or false, every request is
handled as anonymous and authorization is skipped (Phase 1 compose stack, unit tests).
"""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, Request
from opentelemetry import trace

from .otel import Telemetry

logger = logging.getLogger("shd.auth")

ALGORITHMS = ("RS256", "ES256", "PS256")
# Keycloak names service-account users "service-account-<client id>".
SERVICE_ACCOUNT_PREFIX = "service-account-"
# Header that carries the end user's subject on calls between services, for audit logs only. It is
# trusted only together with a valid service token.
END_USER_HEADER = "X-End-User-Sub"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _ssl_context(ca_file: str | None) -> ssl.SSLContext | bool:
    """TLS verification for calls to the identity provider: a private CA file, or the defaults."""
    return ssl.create_default_context(cafile=ca_file) if ca_file else True


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool = False
    issuer: str = ""
    audiences: tuple[str, ...] = ()
    jwks_url: str = ""
    ca_file: str | None = None
    leeway_seconds: int = 30
    jwks_ttl_seconds: int = 300

    @classmethod
    def from_env(cls) -> AuthSettings:
        """``AUTH_ENABLED``, ``AUTH_ISSUER``, ``AUTH_AUDIENCES`` (comma-separated),
        ``AUTH_JWKS_URL`` (default: Keycloak's ``<issuer>/protocol/openid-connect/certs``) and
        ``AUTH_CA_FILE`` (CA bundle for the JWKS endpoint)."""
        enabled = _env_bool("AUTH_ENABLED")
        issuer = os.environ.get("AUTH_ISSUER", "").rstrip("/")
        audiences = tuple(
            a.strip() for a in os.environ.get("AUTH_AUDIENCES", "").split(",") if a.strip()
        )
        if enabled and (not issuer or not audiences):
            raise ValueError("AUTH_ENABLED=true requires AUTH_ISSUER and AUTH_AUDIENCES")
        return cls(
            enabled=enabled,
            issuer=issuer,
            audiences=audiences,
            jwks_url=os.environ.get("AUTH_JWKS_URL")
            or (f"{issuer}/protocol/openid-connect/certs" if issuer else ""),
            ca_file=os.environ.get("AUTH_CA_FILE") or None,
        )


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, from the validated access token."""

    subject: str
    username: str | None = None
    client_id: str | None = None
    audiences: frozenset[str] = frozenset()
    realm_roles: frozenset[str] = frozenset()
    client_roles: dict[str, frozenset[str]] = field(default_factory=dict)
    name: str | None = None
    email: str | None = None
    authenticated: bool = True

    @property
    def is_service_account(self) -> bool:
        return bool(self.username and self.username.startswith(SERVICE_ACCOUNT_PREFIX))

    def has_role(self, role: str) -> bool:
        return role in self.realm_roles

    def has_client_role(self, client: str, role: str) -> bool:
        return role in self.client_roles.get(client, frozenset())

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> Principal:
        aud = claims.get("aud", [])
        resource_access = claims.get("resource_access") or {}
        return cls(
            subject=str(claims["sub"]),
            username=claims.get("preferred_username"),
            client_id=claims.get("azp") or claims.get("client_id"),
            audiences=frozenset([aud] if isinstance(aud, str) else aud),
            realm_roles=frozenset((claims.get("realm_access") or {}).get("roles", [])),
            client_roles={
                client: frozenset(access.get("roles", []))
                for client, access in resource_access.items()
                if isinstance(access, dict)
            },
            name=claims.get("name"),
            email=claims.get("email"),
        )


ANONYMOUS = Principal(subject="anonymous", authenticated=False)


class AuthError(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class TokenError(Exception):
    """No access token could be obtained from the identity provider (client credentials)."""


class JwksCache:
    """The identity provider's signing keys by ``kid``.

    Keys are refetched after ``ttl`` seconds, and at once when a token names an unknown ``kid``
    (key rotation), but not more often than every ``min_refresh_seconds``, so that tokens with
    made-up key IDs cannot make the service hammer the identity provider.
    """

    def __init__(
        self,
        url: str,
        *,
        ttl: float = 300,
        min_refresh_seconds: float = 10,
        verify: ssl.SSLContext | bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 3,
    ) -> None:
        self.url = url
        self.ttl = ttl
        self.min_refresh_seconds = min_refresh_seconds
        self._client = httpx.AsyncClient(verify=verify, transport=transport, timeout=timeout)
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = float("-inf")
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        response = await self._client.get(self.url)
        response.raise_for_status()
        keys = {}
        for data in response.json().get("keys", []):
            if data.get("use", "sig") != "sig" or "kid" not in data:
                continue
            try:
                keys[data["kid"]] = jwt.PyJWK(data)
            except jwt.PyJWKError:
                continue  # e.g. an encryption key or an unsupported algorithm
        self._keys = keys
        self._fetched_at = time.monotonic()
        logger.info("jwks refreshed", extra={"jwks.url": self.url, "jwks.keys": len(keys)})

    async def get(self, kid: str) -> jwt.PyJWK:
        age = time.monotonic() - self._fetched_at
        if kid not in self._keys or age > self.ttl:
            async with self._lock:
                age = time.monotonic() - self._fetched_at
                stale = age > self.ttl
                if stale or (kid not in self._keys and age > self.min_refresh_seconds):
                    try:
                        await self._refresh()
                    except (httpx.HTTPError, ValueError) as exc:
                        if not self._keys:
                            raise AuthError("jwks_unavailable", "signing keys unavailable") from exc
                        logger.warning("jwks refresh failed, using cached keys", exc_info=True)
        key = self._keys.get(kid)
        if key is None:
            raise AuthError("invalid_token", "unknown signing key")
        return key

    async def aclose(self) -> None:
        await self._client.aclose()


class Authenticator:
    """Validates bearer tokens for one service; ``app.state.auth``."""

    def __init__(
        self,
        settings: AuthSettings,
        telemetry: Telemetry,
        *,
        jwks_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.jwks = (
            JwksCache(
                settings.jwks_url,
                ttl=settings.jwks_ttl_seconds,
                verify=_ssl_context(settings.ca_file),
                transport=jwks_transport,
            )
            if settings.enabled
            else None
        )
        meter = telemetry.meter_provider.get_meter("shd.auth")
        # Exposed by Prometheus' OTLP translation as `auth_failures_total{reason}`.
        self.failures = meter.create_counter(
            "auth.failures",
            unit="{request}",
            description="Requests rejected by authentication (401) or authorization (403).",
        )

    async def verify(self, token: str) -> Principal:
        if self.jwks is None:
            raise AuthError("disabled", "authentication is disabled")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise AuthError("invalid_token", "malformed token") from exc
        if header.get("alg") not in ALGORITHMS:
            raise AuthError("invalid_token", "unsupported signing algorithm")
        key = await self.jwks.get(str(header.get("kid", "")))
        try:
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=[header["alg"]],
                audience=list(self.settings.audiences),
                issuer=self.settings.issuer,
                leeway=self.settings.leeway_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("expired_token", "token expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthError("wrong_audience", "token not issued for this service") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthError("invalid_token", "invalid token") from exc
        return Principal.from_claims(claims)

    def reject(self, status: int, reason: str, detail: str) -> HTTPException:
        """401 or 403 with an RFC 6750 ``WWW-Authenticate`` header; counted in ``auth.failures``."""
        self.failures.add(1, {"reason": reason, "http.response.status_code": status})
        span = trace.get_current_span()
        span.set_attribute("auth.failure.reason", reason)
        logger.info("request rejected", extra={"auth.reason": reason, "status": status})
        error = "insufficient_scope" if status == 403 else "invalid_token"
        challenge = f'Bearer error="{error}", error_description="{detail}"'
        if reason == "missing_token":
            challenge = "Bearer"
        return HTTPException(status, detail, headers={"WWW-Authenticate": challenge})

    async def aclose(self) -> None:
        if self.jwks is not None:
            await self.jwks.aclose()


async def current_principal(request: Request) -> Principal:
    """FastAPI dependency: the caller of this request (``ANONYMOUS`` when auth is disabled)."""
    auth: Authenticator | None = getattr(request.app.state, "auth", None)
    if auth is None or not auth.settings.enabled:
        return ANONYMOUS
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise auth.reject(401, "missing_token", "bearer token required")
    try:
        principal = await auth.verify(token.strip())
    except AuthError as exc:
        raise auth.reject(401, exc.reason, exc.detail) from exc
    span = trace.get_current_span()
    # enduser.id is the token subject; for service accounts that is the client's account.
    span.set_attribute("enduser.id", principal.subject)
    if principal.client_id:
        span.set_attribute("oauth.client_id", principal.client_id)
    return principal


def authorize(request: Request, principal: Principal, allowed: bool, detail: str) -> None:
    """Raises 403 unless ``allowed`` (or authentication is disabled)."""
    if not principal.authenticated or allowed:
        return
    auth: Authenticator = request.app.state.auth
    raise auth.reject(403, "forbidden", detail)


@dataclass(frozen=True)
class ClientCredentialsSettings:
    token_url: str
    client_id: str
    client_secret: str
    ca_file: str | None = None
    scope: str | None = None

    @classmethod
    def from_env(cls) -> ClientCredentialsSettings | None:
        """``OAUTH_TOKEN_URL``, ``OAUTH_CLIENT_ID``, ``OAUTH_CLIENT_SECRET``, optional
        ``OAUTH_SCOPE`` and ``AUTH_CA_FILE``. ``None`` when no token URL is configured."""
        token_url = os.environ.get("OAUTH_TOKEN_URL", "").strip()
        if not token_url:
            return None
        return cls(
            token_url=token_url,
            client_id=os.environ["OAUTH_CLIENT_ID"],
            client_secret=os.environ["OAUTH_CLIENT_SECRET"],
            ca_file=os.environ.get("AUTH_CA_FILE") or None,
            scope=os.environ.get("OAUTH_SCOPE") or None,
        )


class ClientCredentialsAuth(httpx.Auth):
    """``httpx.Auth`` for calls between services: a cached client-credentials access token.

    The token is renewed ``refresh_margin`` seconds before it expires, and once more when the
    upstream answers 401 (e.g. after a key rotation). One instance can be shared by several clients.
    """

    def __init__(
        self,
        settings: ClientCredentialsSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        refresh_margin: float = 30,
        timeout: float = 3,
    ) -> None:
        self.settings = settings
        self.refresh_margin = refresh_margin
        self._client = httpx.AsyncClient(
            verify=_ssl_context(settings.ca_file), transport=transport, timeout=timeout
        )
        self._token = ""
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def client(self) -> httpx.AsyncClient:
        """The client used for the token endpoint (e.g. to instrument it)."""
        return self._client

    async def token(self, *, force: bool = False) -> str:
        async with self._lock:
            if force or not self._token or time.monotonic() >= self._expires_at:
                data = {"grant_type": "client_credentials"}
                if self.settings.scope:
                    data["scope"] = self.settings.scope
                try:
                    response = await self._client.post(
                        self.settings.token_url,
                        data=data,
                        auth=(self.settings.client_id, self.settings.client_secret),
                    )
                    response.raise_for_status()
                    body = response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    logger.error(
                        "token request failed",
                        extra={"oauth.client_id": self.settings.client_id, "error": str(exc)},
                    )
                    raise TokenError(f"no token for {self.settings.client_id}: {exc}") from exc
                self._token = body["access_token"]
                lifetime = float(body.get("expires_in", 60))
                self._expires_at = time.monotonic() + max(lifetime - self.refresh_margin, 1)
            return self._token

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        request.headers["Authorization"] = f"Bearer {await self.token()}"
        response = yield request
        if response.status_code == 401:
            request.headers["Authorization"] = f"Bearer {await self.token(force=True)}"
            yield request

    async def aclose(self) -> None:
        await self._client.aclose()


def end_user_headers(principal: Principal) -> dict[str, str]:
    """Header that tells downstream services on whose behalf a call is made (audit only)."""
    if principal.authenticated and not principal.is_service_account:
        return {END_USER_HEADER: principal.subject}
    return {}


def audit_user(request: Request, principal: Principal) -> str | None:
    """The end user of a call between services, for logs: the propagated header, trusted only
    from an authenticated service account."""
    if principal.authenticated and principal.is_service_account:
        return request.headers.get(END_USER_HEADER)
    return None
