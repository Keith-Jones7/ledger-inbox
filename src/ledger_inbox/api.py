from __future__ import annotations

from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from .config import Settings
from .database import Database
from .image_store import ImageStore
from .ingestion import IngestionService
from .security import verify_webhook_signature


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    database = Database(config.db_path)
    database.initialize()
    ingestion = IngestionService(
        database, ImageStore(config.data_dir / "images"), config.max_image_bytes
    )

    app = FastAPI(
        title="Ledger Inbox",
        version="0.1.0",
        description="Multi-channel image ingestion for extensible bookkeeping automation.",
    )
    app.state.settings = config
    app.state.database = database
    app.state.ingestion = ingestion

    def tenant_from_key(
        x_ledger_inbox_key: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        if not x_ledger_inbox_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="missing API key"
            )
        tenant = database.tenant_for_api_key(x_ledger_inbox_key)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key"
            )
        return tenant

    @app.get("/healthz", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/v1/ingest/images", status_code=status.HTTP_202_ACCEPTED, tags=["ingestion"]
    )
    async def ingest_image(
        image: Annotated[
            UploadFile, File(description="PNG, JPEG, WebP, HEIC, or AVIF screenshot")
        ],
        tenant: dict[str, str] = Depends(tenant_from_key),  # noqa: B008 - FastAPI dependency injection
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        x_captured_at: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        body = await image.read(config.max_image_bytes + 1)
        try:
            result = ingestion.ingest_image(
                tenant_id=tenant["id"],
                image=body,
                filename=image.filename or "image",
                source_kind="https",
                source_event_id=idempotency_key,
                captured_at=x_captured_at,
                metadata={},
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return result.to_dict()

    @app.post(
        "/v1/inbound/email/rfc822",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["ingestion"],
    )
    async def ingest_rfc822(
        request: Request,
        x_ledger_inbox_recipient: Annotated[str | None, Header()] = None,
        x_ledger_inbox_timestamp: Annotated[str | None, Header()] = None,
        x_ledger_inbox_signature: Annotated[str | None, Header()] = None,
        x_ledger_inbox_message_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        if not config.webhook_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="email webhook is disabled",
            )
        if not all(
            (
                x_ledger_inbox_recipient,
                x_ledger_inbox_timestamp,
                x_ledger_inbox_signature,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing webhook authentication",
            )
        body = await request.body()
        if len(body) > config.max_image_bytes * 4:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="email is too large",
            )
        assert x_ledger_inbox_recipient is not None
        assert x_ledger_inbox_timestamp is not None
        assert x_ledger_inbox_signature is not None
        if not verify_webhook_signature(
            config.webhook_secret,
            x_ledger_inbox_timestamp,
            x_ledger_inbox_recipient,
            body,
            x_ledger_inbox_signature,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid webhook signature",
            )
        tenant = database.tenant_for_alias(x_ledger_inbox_recipient)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="unknown inbound alias"
            )
        try:
            results = ingestion.ingest_email(
                tenant_id=tenant["id"],
                raw_message=body,
                source_event_id=x_ledger_inbox_message_id,
                recipient=x_ledger_inbox_recipient,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return {"events": [item.to_dict() for item in results]}

    @app.get("/v1/events/{event_id}", tags=["events"])
    def get_event(
        event_id: str,
        tenant: dict[str, str] = Depends(tenant_from_key),  # noqa: B008 - FastAPI dependency injection
    ) -> dict[str, object]:
        event = database.get_event(event_id, tenant["id"])
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="event not found"
            )
        event.pop("image_path", None)
        event.pop("metadata", None)
        return event

    return app
