from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence

import uvicorn

from .adapters.ledgers import load_ledger_sink
from .adapters.recognizers import load_recognizer
from .api import create_app
from .config import Settings
from .database import Database
from .email_connector import IMAPConnector, IMAPSettings
from .image_store import ImageStore
from .ingestion import IngestionService
from .security import new_api_key, new_inbound_alias
from .worker import Worker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ledger-inbox")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "init", help="initialize the SQLite schema and data directories"
    )

    tenant = subparsers.add_parser(
        "create-tenant", help="create a tenant and print its API key once"
    )
    tenant.add_argument("--name", required=True)

    alias = subparsers.add_parser("create-alias", help="add an email alias to a tenant")
    alias.add_argument("--tenant-id", required=True)
    alias.add_argument("--alias")
    alias.add_argument("--domain", default="inbound.invalid")

    serve = subparsers.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)

    worker = subparsers.add_parser("worker", help="process queued events")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--poll-seconds", type=float, default=2.0)

    imap = subparsers.add_parser(
        "imap", help="poll an IMAP mailbox for image attachments"
    )
    imap.add_argument("--once", action="store_true")
    imap.add_argument("--poll-seconds", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    database = Database(settings.db_path)
    database.initialize()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "init":
        print(
            json.dumps(
                {"database": str(settings.db_path), "data_dir": str(settings.data_dir)}
            )
        )
        return 0
    if args.command == "create-tenant":
        api_key = new_api_key()
        tenant = database.create_tenant(args.name, api_key)
        print(json.dumps({**tenant, "api_key": api_key}, ensure_ascii=False))
        return 0
    if args.command == "create-alias":
        alias = args.alias or new_inbound_alias(args.domain)
        database.add_alias(args.tenant_id, alias)
        print(json.dumps({"tenant_id": args.tenant_id, "alias": alias}))
        return 0
    if args.command == "serve":
        uvicorn.run(
            create_app(settings),
            host=args.host,
            port=args.port,
            proxy_headers=settings.trust_proxy_headers,
        )
        return 0
    if args.command == "worker":
        worker = Worker(
            database,
            load_recognizer(settings.recognizer, settings),
            load_ledger_sink(settings.ledger_sink, settings),
        )
        if args.once:
            print(json.dumps(worker.run_once()))
        else:
            worker.run_forever(args.poll_seconds)
        return 0
    if args.command == "imap":
        connector = _imap_connector(settings, database)
        if args.once:
            print(json.dumps(connector.poll_once()))
        else:
            connector.run_forever(args.poll_seconds)
        return 0
    raise AssertionError(f"unhandled command {args.command}")


def _imap_connector(settings: Settings, database: Database) -> IMAPConnector:
    required = {
        "host": os.getenv("LEDGER_INBOX_IMAP_HOST"),
        "username": os.getenv("LEDGER_INBOX_IMAP_USERNAME"),
        "password": os.getenv("LEDGER_INBOX_IMAP_PASSWORD"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit("missing IMAP settings: " + ", ".join(missing))
    ingestion = IngestionService(
        database, ImageStore(settings.data_dir / "images"), settings.max_image_bytes
    )
    return IMAPConnector(
        IMAPSettings(
            host=str(required["host"]),
            username=str(required["username"]),
            password=str(required["password"]),
            mailbox=os.getenv("LEDGER_INBOX_IMAP_MAILBOX", "INBOX"),
            port=int(os.getenv("LEDGER_INBOX_IMAP_PORT", "993")),
        ),
        database,
        ingestion,
    )


if __name__ == "__main__":
    raise SystemExit(main())
