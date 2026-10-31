"""HTTP clients for User and Payment, and the mapping of upstream failures to HTTP status codes.

| Upstream outcome                                | Our response              |
|-------------------------------------------------|---------------------------|
| connect error / connect or pool timeout          | 503 Service Unavailable   |
| read/write timeout (request may have been sent)  | 504 Gateway Timeout       |
| other transport error, 5xx, unexpected status    | 502 Bad Gateway           |
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


class UpstreamError(Exception):
    def __init__(self, upstream: str, status_code: int, detail: str) -> None:
        super().__init__(f"{upstream}: {detail}")
        self.upstream = upstream
        self.status_code = status_code
        self.detail = detail
        # True when the request may have reached the upstream (outcome unknown).
        self.outcome_unknown = status_code in (502, 504)
        # Set once the order has been stored, so the error response can reference it.
        self.order_id: str | None = None


def map_transport_error(upstream: str, exc: httpx.TransportError) -> UpstreamError:
    if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout | httpx.PoolTimeout):
        return UpstreamError(upstream, 503, f"{upstream} service unavailable")
    if isinstance(exc, httpx.TimeoutException):
        return UpstreamError(upstream, 504, f"{upstream} service timed out")
    return UpstreamError(upstream, 502, f"{upstream} service connection failed")


def unexpected_response(upstream: str, response: httpx.Response) -> UpstreamError:
    error = UpstreamError(upstream, 502, f"{upstream} service returned HTTP {response.status_code}")
    # A 4xx means the upstream rejected the request, so it was not processed.
    error.outcome_unknown = response.status_code >= 500
    return error


@dataclass(frozen=True)
class UpstreamSettings:
    user_url: str
    payment_url: str
    user_timeout: float
    payment_timeout: float
    connect_timeout: float

    @classmethod
    def from_env(cls) -> UpstreamSettings:
        return cls(
            user_url=os.environ.get("USER_SERVICE_URL", "http://localhost:8081"),
            payment_url=os.environ.get("PAYMENT_SERVICE_URL", "http://localhost:8083"),
            user_timeout=float(os.environ.get("USER_SERVICE_TIMEOUT_SECONDS", "2")),
            payment_timeout=float(os.environ.get("PAYMENT_SERVICE_TIMEOUT_SECONDS", "3")),
            connect_timeout=float(os.environ.get("UPSTREAM_CONNECT_TIMEOUT_SECONDS", "1")),
        )


def build_clients(
    settings: UpstreamSettings,
    user_transport: httpx.AsyncBaseTransport | None = None,
    payment_transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[httpx.AsyncClient, httpx.AsyncClient]:
    user_client = httpx.AsyncClient(
        base_url=settings.user_url,
        timeout=httpx.Timeout(settings.user_timeout, connect=settings.connect_timeout),
        # GET is idempotent: one retry, and httpx only retries failed connection attempts.
        transport=user_transport or httpx.AsyncHTTPTransport(retries=1),
    )
    payment_client = httpx.AsyncClient(
        base_url=settings.payment_url,
        timeout=httpx.Timeout(settings.payment_timeout, connect=settings.connect_timeout),
        # No automatic retries for the non-idempotent POST; an Idempotency-Key is sent instead
        # so that a later reconciliation can retry safely.
        transport=payment_transport or httpx.AsyncHTTPTransport(retries=0),
    )
    return user_client, payment_client
