from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .security import hash_api_key


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    api_key_hash TEXT NOT NULL UNIQUE,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inbound_aliases (
                    alias TEXT PRIMARY KEY COLLATE NOCASE,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ingest_events (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    source_kind TEXT NOT NULL,
                    source_event_id TEXT,
                    content_sha256 TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    captured_at TEXT,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (tenant_id, content_sha256),
                    UNIQUE (tenant_id, source_kind, source_event_id)
                );

                CREATE INDEX IF NOT EXISTS idx_ingest_events_status
                    ON ingest_events(status, created_at);

                CREATE TABLE IF NOT EXISTS recognition_results (
                    event_id TEXT PRIMARY KEY REFERENCES ingest_events(id) ON DELETE CASCADE,
                    recognizer TEXT NOT NULL,
                    entry_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS delivery_operations (
                    id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE REFERENCES ingest_events(id) ON DELETE CASCADE,
                    sink TEXT NOT NULL,
                    state TEXT NOT NULL,
                    external_ref TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def create_tenant(self, name: str, api_key: str) -> dict[str, str]:
        tenant_id = str(uuid.uuid4())
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (?, ?, ?, ?)",
                (tenant_id, name, hash_api_key(api_key), utc_now()),
            )
        return {"id": tenant_id, "name": name}

    def add_alias(self, tenant_id: str, alias: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO inbound_aliases (alias, tenant_id, created_at) VALUES (?, ?, ?)",
                (alias.lower(), tenant_id, utc_now()),
            )

    def tenant_for_api_key(self, api_key: str) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute(
                "SELECT id, name FROM tenants WHERE api_key_hash = ? AND active = 1",
                (hash_api_key(api_key),),
            ).fetchone()
        return dict(row) if row else None

    def tenant_for_alias(self, alias: str) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute(
                """
                SELECT tenants.id, tenants.name
                FROM inbound_aliases
                JOIN tenants ON tenants.id = inbound_aliases.tenant_id
                WHERE inbound_aliases.alias = ? AND inbound_aliases.active = 1 AND tenants.active = 1
                """,
                (alias.lower(),),
            ).fetchone()
        return dict(row) if row else None

    def create_event(
        self,
        *,
        tenant_id: str,
        source_kind: str,
        source_event_id: str | None,
        digest: str,
        filename: str,
        media_type: str,
        image_path: str,
        captured_at: str | None,
        metadata: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        event_id = str(uuid.uuid4())
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO ingest_events
                        (id, tenant_id, source_kind, source_event_id, content_sha256,
                         filename, media_type, image_path, captured_at, metadata_json,
                         status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (
                        event_id,
                        tenant_id,
                        source_kind,
                        source_event_id,
                        digest,
                        filename,
                        media_type,
                        image_path,
                        captured_at,
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM ingest_events
                    WHERE tenant_id = ? AND
                          (content_sha256 = ? OR (source_kind = ? AND source_event_id = ?))
                    ORDER BY created_at LIMIT 1
                    """,
                    (tenant_id, digest, source_kind, source_event_id),
                ).fetchone()
                if row is None:
                    raise
                return _event_dict(row), True
            row = connection.execute(
                "SELECT * FROM ingest_events WHERE id = ?", (event_id,)
            ).fetchone()
            assert row is not None
            return _event_dict(row), False

    def get_event(
        self, event_id: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        query = "SELECT * FROM ingest_events WHERE id = ?"
        params: tuple[Any, ...] = (event_id,)
        if tenant_id:
            query += " AND tenant_id = ?"
            params += (tenant_id,)
        with self.session() as connection:
            row = connection.execute(query, params).fetchone()
            if row is None:
                return None
            event = _event_dict(row)
            result = connection.execute(
                "SELECT recognizer, entry_json, status, created_at FROM recognition_results WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            delivery = connection.execute(
                "SELECT id, sink, state, external_ref, last_error, created_at, updated_at FROM delivery_operations WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if result:
            event["recognition"] = {
                "recognizer": result["recognizer"],
                "entry": json.loads(result["entry_json"]),
                "status": result["status"],
                "created_at": result["created_at"],
            }
        if delivery:
            event["delivery"] = dict(delivery)
        return event

    def claim_next_event(self) -> dict[str, Any] | None:
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM ingest_events WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            now = utc_now()
            updated = connection.execute(
                """
                UPDATE ingest_events
                SET status = 'processing', attempt_count = attempt_count + 1, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, row["id"]),
            )
            if updated.rowcount != 1:
                return None
            claimed = connection.execute(
                "SELECT * FROM ingest_events WHERE id = ?", (row["id"],)
            ).fetchone()
            assert claimed is not None
            return _event_dict(claimed)

    def fail_recognition(self, event_id: str, error: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE ingest_events SET status = 'recognition_failed', last_error = ?, updated_at = ? WHERE id = ?",
                (error[:2000], utc_now(), event_id),
            )

    def save_recognition(
        self, event_id: str, recognizer: str, entry: dict[str, Any], needs_review: bool
    ) -> None:
        status = "needs_review" if needs_review else "recognized"
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO recognition_results (event_id, recognizer, entry_json, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    recognizer,
                    json.dumps(entry, ensure_ascii=False, sort_keys=True),
                    status,
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE ingest_events SET status = ?, last_error = NULL, updated_at = ? WHERE id = ?",
                (status, utc_now(), event_id),
            )

    def prepare_delivery(self, event_id: str, sink: str) -> str:
        operation_id = str(uuid.uuid4())
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO delivery_operations (id, event_id, sink, state, created_at, updated_at)
                VALUES (?, ?, ?, 'inflight', ?, ?)
                """,
                (operation_id, event_id, sink, now, now),
            )
            connection.execute(
                "UPDATE ingest_events SET status = 'delivering', updated_at = ? WHERE id = ?",
                (now, event_id),
            )
        return operation_id

    def finish_delivery(
        self,
        event_id: str,
        operation_id: str,
        *,
        state: str,
        external_ref: str | None = None,
        error: str | None = None,
    ) -> None:
        event_status = {
            "confirmed": "completed",
            "unknown": "delivery_unknown",
            "failed": "delivery_failed",
        }[state]
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE delivery_operations
                SET state = ?, external_ref = ?, last_error = ?, updated_at = ?
                WHERE id = ? AND event_id = ? AND state = 'inflight'
                """,
                (
                    state,
                    external_ref,
                    error[:2000] if error else None,
                    utc_now(),
                    operation_id,
                    event_id,
                ),
            )
            connection.execute(
                "UPDATE ingest_events SET status = ?, last_error = ?, updated_at = ? WHERE id = ?",
                (event_status, error[:2000] if error else None, utc_now(), event_id),
            )


def _event_dict(row: sqlite3.Row) -> dict[str, Any]:
    event = dict(row)
    event["metadata"] = json.loads(event.pop("metadata_json"))
    return event
