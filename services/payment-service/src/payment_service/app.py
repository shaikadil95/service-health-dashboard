from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from shd_telemetry import FaultInjector, Telemetry, create_service_app

from . import __version__
from .metrics import PaymentMetrics

logger = logging.getLogger("payment_service")

# Allow-list: currency is a metric attribute, so free-form codes would let clients create
# unbounded time series.
Currency = Literal["EUR", "USD", "GBP"]


class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(gt=0, le=1_000_000, decimal_places=2)
    currency: Currency


class Payment(BaseModel):
    id: str
    order_id: str
    amount: Decimal
    currency: str
    status: Literal["approved", "declined"]
    decline_reason: str | None = None
    created_at: datetime


def _fingerprint(request: PaymentRequest) -> str:
    return hashlib.sha256(request.model_dump_json().encode()).hexdigest()


def create_app(
    telemetry: Telemetry,
    faults: FaultInjector | None = None,
    approval_limit: Decimal | None = None,
) -> FastAPI:
    app = create_service_app(
        title="Payment service", version=__version__, telemetry=telemetry, faults=faults
    )
    limit = approval_limit or Decimal(os.environ.get("PAYMENT_APPROVAL_LIMIT", "5000"))
    metrics = PaymentMetrics(telemetry.meter_provider)
    # Idempotency-Key -> (request fingerprint, payment). In-memory: lost on restart.
    processed: dict[str, tuple[str, Payment]] = {}

    def _respond(payment: Payment, replayed: bool) -> JSONResponse:
        headers = {"Idempotent-Replayed": "true"} if replayed else {}
        return JSONResponse(
            payment.model_dump(mode="json"),
            status_code=201 if payment.status == "approved" else 402,
            headers=headers,
        )

    @app.post(
        "/payments",
        tags=["payments"],
        status_code=201,
        response_model=Payment,
        responses={402: {"model": Payment, "description": "Payment declined"}},
    )
    async def create_payment(
        request: PaymentRequest,
        idempotency_key: Annotated[str | None, Header(min_length=1, max_length=255)] = None,
    ) -> JSONResponse:
        if idempotency_key is None:
            # draft-ietf-httpapi-idempotency-key-header: missing required key -> 400.
            raise HTTPException(400, "Idempotency-Key header is required")
        fingerprint = _fingerprint(request)
        previous = processed.get(idempotency_key)
        if previous is not None:
            if previous[0] != fingerprint:
                # draft-ietf-httpapi-idempotency-key-header: key reused with another payload.
                raise HTTPException(422, "Idempotency-Key was already used for another request")
            logger.info("payment replayed", extra={"payment.id": previous[1].id})
            return _respond(previous[1], replayed=True)

        approved = request.amount <= limit
        payment = Payment(
            id=f"pay-{uuid.uuid4().hex[:12]}",
            order_id=request.order_id,
            amount=request.amount,
            currency=request.currency,
            status="approved" if approved else "declined",
            decline_reason=None if approved else "amount_limit_exceeded",
            created_at=datetime.now(UTC),
        )
        processed[idempotency_key] = (fingerprint, payment)
        metrics.record(request.amount, request.currency, payment.status)
        logger.info(
            "payment processed",
            extra={
                "payment.id": payment.id,
                "order.id": request.order_id,
                "payment.status": payment.status,
            },
        )
        return _respond(payment, replayed=False)

    return app
