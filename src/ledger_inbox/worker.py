from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .adapters.ledgers import DefinitiveDeliveryError, UnknownDeliveryError
from .database import Database
from .domain import LedgerSink, RecognitionContext, Recognizer


class Worker:
    def __init__(
        self, database: Database, recognizer: Recognizer, ledger_sink: LedgerSink
    ) -> None:
        self.database = database
        self.recognizer = recognizer
        self.ledger_sink = ledger_sink

    def run_once(self) -> dict[str, Any] | None:
        event = self.database.claim_next_event()
        if event is None:
            return None
        context = RecognitionContext(
            event_id=event["id"],
            tenant_id=event["tenant_id"],
            image_path=event["image_path"],
            media_type=event["media_type"],
            filename=event["filename"],
            captured_at=event["captured_at"],
            metadata=event["metadata"],
        )
        if not Path(context.image_path).is_file():
            self.database.fail_recognition(event["id"], "stored image is missing")
            return {"event_id": event["id"], "status": "recognition_failed"}
        try:
            entry = self.recognizer.recognize(context).validated()
        except Exception as exc:  # noqa: BLE001 - adapters are an untrusted extension boundary
            self.database.fail_recognition(event["id"], f"{type(exc).__name__}: {exc}")
            return {"event_id": event["id"], "status": "recognition_failed"}

        self.database.save_recognition(
            event["id"], self.recognizer.name, entry.to_dict(), entry.needs_review
        )
        if entry.needs_review:
            return {"event_id": event["id"], "status": "needs_review"}

        operation_id = self.database.prepare_delivery(
            event["id"], self.ledger_sink.name
        )
        try:
            reference = self.ledger_sink.deliver(
                entry, event_id=event["id"], operation_id=operation_id
            )
        except UnknownDeliveryError as exc:
            self.database.finish_delivery(
                event["id"],
                operation_id,
                state="unknown",
                error=f"{type(exc).__name__}: {exc}",
            )
            return {"event_id": event["id"], "status": "delivery_unknown"}
        except DefinitiveDeliveryError as exc:
            self.database.finish_delivery(
                event["id"],
                operation_id,
                state="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            return {"event_id": event["id"], "status": "delivery_failed"}
        except Exception as exc:  # noqa: BLE001 - an unclassified sink failure is ambiguous
            self.database.finish_delivery(
                event["id"],
                operation_id,
                state="unknown",
                error=f"{type(exc).__name__}: {exc}",
            )
            return {"event_id": event["id"], "status": "delivery_unknown"}

        self.database.finish_delivery(
            event["id"], operation_id, state="confirmed", external_ref=reference
        )
        return {"event_id": event["id"], "status": "completed"}

    def run_forever(self, poll_seconds: float = 2.0) -> None:
        while True:
            result = self.run_once()
            if result is None:
                time.sleep(poll_seconds)
