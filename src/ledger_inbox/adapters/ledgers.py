from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from ..domain import LedgerEntry, LedgerSink


class DefinitiveDeliveryError(RuntimeError):
    """The sink returned a response that confirms this attempt did not succeed."""


class UnknownDeliveryError(RuntimeError):
    """The request may have reached the sink; callers must not replay automatically."""


class DirectoryLedgerSink:
    name = "directory"

    def __init__(self, root: Path) -> None:
        self.root = root

    def deliver(self, entry: LedgerEntry, *, event_id: str, operation_id: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / f"{operation_id}.json"
        payload = {
            "operation_id": operation_id,
            "event_id": event_id,
            "entry": entry.to_dict(),
        }
        body = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
        if destination.exists():
            if destination.read_bytes() != body:
                raise UnknownDeliveryError(
                    "operation file already exists with different content"
                )
            return str(destination)
        fd, temp_name = tempfile.mkstemp(prefix=".entry-", dir=self.root)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_path, destination)
        finally:
            temp_path.unlink(missing_ok=True)
        return str(destination)


class WebhookLedgerSink:
    name = "webhook"

    def __init__(self, url: str, secret: str | None = None) -> None:
        self.url = url
        self.secret = secret

    def deliver(
        self, entry: LedgerEntry, *, event_id: str, operation_id: str
    ) -> str | None:
        payload = {
            "operation_id": operation_id,
            "event_id": event_id,
            "entry": entry.to_dict(),
        }
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        headers = {"Content-Type": "application/json", "Idempotency-Key": operation_id}
        if self.secret:
            headers["X-Ledger-Inbox-Signature"] = (
                "sha256="
                + hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
            )
        try:
            response = httpx.post(self.url, content=body, headers=headers, timeout=30)
        except httpx.RequestError as exc:
            raise UnknownDeliveryError(str(exc)) from exc
        if not 200 <= response.status_code < 300:
            raise DefinitiveDeliveryError(
                f"ledger webhook returned HTTP {response.status_code}"
            )
        return response.headers.get("Location") or response.headers.get(
            "X-Ledger-Reference"
        )


def load_ledger_sink(spec: str, settings: Settings) -> LedgerSink:
    if spec == "directory":
        return DirectoryLedgerSink(settings.data_dir / "ledger-outbox")
    if spec == "webhook":
        if not settings.ledger_webhook_url:
            raise ValueError(
                "LEDGER_INBOX_LEDGER_WEBHOOK_URL is required for webhook sink"
            )
        return WebhookLedgerSink(
            settings.ledger_webhook_url, settings.ledger_webhook_secret
        )
    loaded = _load_object(spec)
    instance = loaded(settings) if isinstance(loaded, type) else loaded
    if not hasattr(instance, "deliver") or not hasattr(instance, "name"):
        raise TypeError(
            f"ledger sink {spec!r} must expose name and deliver(entry, ...)"
        )
    return instance


def _load_object(spec: str) -> Any:
    if ":" not in spec:
        raise ValueError("custom adapter must use module.path:object format")
    module_name, object_name = spec.split(":", 1)
    return getattr(importlib.import_module(module_name), object_name)
