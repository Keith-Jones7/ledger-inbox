from __future__ import annotations

from ledger_inbox.domain import LedgerEntry, RecognitionContext


class ExampleRecognizer:
    name = "example"

    def __init__(self, settings) -> None:
        self.settings = settings

    def recognize(self, context: RecognitionContext) -> LedgerEntry:
        # Replace with OCR/model calls. Uncertain values must stop at review.
        return LedgerEntry(
            transaction_type="unknown",
            amount_minor=None,
            currency="CNY",
            merchant=None,
            occurred_at=context.captured_at,
            category=None,
            needs_review=True,
            review_reasons=("example_adapter_has_no_model",),
        )


class ExampleLedgerSink:
    name = "example-ledger"

    def __init__(self, settings) -> None:
        self.settings = settings

    def deliver(self, entry: LedgerEntry, *, event_id: str, operation_id: str) -> str:
        # A real integration must persist operation_id at the destination.
        return f"example:{operation_id}"
