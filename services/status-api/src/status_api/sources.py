"""Thin clients for the Prometheus HTTP API and the Alertmanager v2 API.

* Prometheus: https://prometheus.io/docs/prometheus/latest/querying/api/
* Alertmanager: https://github.com/prometheus/alertmanager/blob/main/api/v2/openapi.yaml
"""

from __future__ import annotations

import math
from typing import Any

import httpx


class SourceError(Exception):
    """A backend could not be queried (network error, timeout, HTTP error, bad payload)."""


def _number(raw: str) -> float | None:
    value = float(raw)
    return None if math.isnan(value) or math.isinf(value) else value


class PrometheusClient:
    def __init__(self, client: httpx.AsyncClient, base_url: str, timeout: float) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def _get(self, path: str, params: dict[str, str]) -> Any:
        # Prometheus stops evaluating at its own timeout too, so a slow query is not left running.
        # The API accepts a duration or a float number of seconds ("3", "2.5"), not "3.0s".
        params = {**params, "timeout": f"{self._timeout:g}"}
        try:
            response = await self._client.get(
                f"{self._base}{path}", params=params, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise SourceError(f"prometheus: {type(exc).__name__}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise SourceError(f"prometheus: HTTP {response.status_code}") from exc
        if response.status_code != 200 or body.get("status") != "success":
            # Error responses carry {"status": "error", "errorType": ..., "error": ...}.
            if "errorType" not in body:
                raise SourceError(f"prometheus: HTTP {response.status_code}")
            raise SourceError(f"prometheus: {body.get('errorType', 'error')}")
        return body["data"]

    async def vector(self, query: str, by: str) -> dict[str, float | None]:
        """Instant query; returns {value of label ``by``: sample value}."""
        data = await self._get("/api/v1/query", {"query": query})
        if data.get("resultType") != "vector":
            raise SourceError(f"prometheus: expected a vector, got {data.get('resultType')}")
        return {
            sample["metric"].get(by, ""): _number(sample["value"][1]) for sample in data["result"]
        }

    async def matrix(
        self, query: str, by: str, start: float, end: float, step: int
    ) -> dict[str, list[tuple[int, float | None]]]:
        """Range query; returns {value of label ``by``: [(unix seconds, value), ...]}."""
        data = await self._get(
            "/api/v1/query_range",
            {"query": query, "start": f"{start:.0f}", "end": f"{end:.0f}", "step": f"{step}s"},
        )
        if data.get("resultType") != "matrix":
            raise SourceError(f"prometheus: expected a matrix, got {data.get('resultType')}")
        return {
            series["metric"].get(by, ""): [(int(t), _number(v)) for t, v in series["values"]]
            for series in data["result"]
        }


class AlertmanagerClient:
    def __init__(self, client: httpx.AsyncClient, base_url: str, timeout: float) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def active_alerts(self) -> list[dict[str, Any]]:
        """Firing alerts that are neither silenced nor inhibited (what on-call is paged for)."""
        try:
            response = await self._client.get(
                f"{self._base}/api/v2/alerts",
                params={"active": "true", "silenced": "false", "inhibited": "false"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise SourceError(f"alertmanager: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise SourceError(f"alertmanager: HTTP {response.status_code}")
        try:
            alerts = response.json()
        except ValueError as exc:
            raise SourceError("alertmanager: invalid JSON") from exc
        if not isinstance(alerts, list):
            raise SourceError("alertmanager: expected a list of alerts")
        return alerts
