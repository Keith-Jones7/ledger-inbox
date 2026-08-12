from __future__ import annotations

import imaplib
import ssl
import time
from dataclasses import dataclass

from .database import Database
from .ingestion import IngestionService, recipients_from_message


@dataclass(frozen=True)
class IMAPSettings:
    host: str
    username: str
    password: str
    mailbox: str = "INBOX"
    port: int = 993


class IMAPConnector:
    def __init__(
        self, config: IMAPSettings, database: Database, ingestion: IngestionService
    ) -> None:
        self.config = config
        self.database = database
        self.ingestion = ingestion

    def poll_once(self) -> dict[str, int]:
        accepted = 0
        skipped = 0
        with imaplib.IMAP4_SSL(
            self.config.host,
            self.config.port,
            ssl_context=ssl.create_default_context(),
        ) as client:
            client.login(self.config.username, self.config.password)
            status, _ = client.select(self.config.mailbox)
            if status != "OK":
                raise RuntimeError(f"could not select mailbox {self.config.mailbox}")
            status, payload = client.uid("search", None, "UNSEEN")
            if status != "OK":
                raise RuntimeError("IMAP UNSEEN search failed")
            uids = payload[0].split() if payload and payload[0] else []
            for uid in uids:
                status, fetched = client.uid("fetch", uid, "(BODY.PEEK[])")
                if status != "OK":
                    skipped += 1
                    continue
                raw_message = _extract_message(fetched)
                if raw_message is None:
                    skipped += 1
                    continue
                recipient, tenant = self._resolve_recipient(raw_message)
                if tenant is None or recipient is None:
                    skipped += 1
                    continue
                # Persist every attachment before advancing the mailbox flag.
                self.ingestion.ingest_email(
                    tenant_id=tenant["id"],
                    raw_message=raw_message,
                    source_event_id=f"imap:{self.config.host}:{self.config.mailbox}:{uid.decode()}",
                    recipient=recipient,
                )
                client.uid("store", uid, "+FLAGS", "(\\Seen)")
                accepted += 1
        return {"accepted_messages": accepted, "skipped_messages": skipped}

    def run_forever(self, poll_seconds: float = 30.0) -> None:
        while True:
            self.poll_once()
            time.sleep(poll_seconds)

    def _resolve_recipient(
        self, raw_message: bytes
    ) -> tuple[str | None, dict[str, str] | None]:
        for recipient in recipients_from_message(raw_message):
            tenant = self.database.tenant_for_alias(recipient)
            if tenant:
                return recipient, tenant
        return None, None


def _extract_message(response: list[object]) -> bytes | None:
    for item in response:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None
