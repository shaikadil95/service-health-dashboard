from __future__ import annotations

from decimal import Decimal

from opentelemetry.metrics import MeterProvider

from . import __version__

# OTel instrument names follow the semantic-convention naming rules (no `_total`, no unit in the
# name). Prometheus' OTLP translation exposes them as `payments_processed_total` and
# `payment_amount_bucket/_sum/_count`.
AMOUNT_BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


class PaymentMetrics:
    def __init__(self, meter_provider: MeterProvider) -> None:
        meter = meter_provider.get_meter("payment_service", __version__)
        self.processed = meter.create_counter(
            "payments.processed",
            unit="{payment}",
            description="Payments processed, by result (approved or declined).",
        )
        self.amount = meter.create_histogram(
            "payment.amount",
            unit="{currency_unit}",
            description="Amount of processed payments in the payment currency.",
            explicit_bucket_boundaries_advisory=AMOUNT_BUCKETS,
        )

    def record(self, amount: Decimal, currency: str, result: str) -> None:
        # Only low-cardinality attributes: never user, order or payment IDs.
        self.processed.add(1, {"result": result})
        self.amount.record(float(amount), {"currency": currency, "result": result})
