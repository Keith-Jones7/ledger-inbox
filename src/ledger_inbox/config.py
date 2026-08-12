from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    database_path: Path | None = None
    max_image_bytes: int = 12 * 1024 * 1024
    webhook_secret: str | None = None
    recognizer: str = "mock"
    ledger_sink: str = "directory"
    model_base_url: str = "http://127.0.0.1:11434/v1"
    model_api_key: str = "local"
    model_name: str = "qwen3-vl:4b"
    model_timeout_seconds: float = 90.0
    ledger_webhook_url: str | None = None
    ledger_webhook_secret: str | None = None
    trust_proxy_headers: bool = False

    @property
    def db_path(self) -> Path:
        return self.database_path or self.data_dir / "ledger-inbox.sqlite3"

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.getenv("LEDGER_INBOX_DATA_DIR", "data")).expanduser()
        raw_db = os.getenv("LEDGER_INBOX_DATABASE_PATH")
        return cls(
            data_dir=data_dir,
            database_path=Path(raw_db).expanduser() if raw_db else None,
            max_image_bytes=int(
                os.getenv("LEDGER_INBOX_MAX_IMAGE_BYTES", str(12 * 1024 * 1024))
            ),
            webhook_secret=os.getenv("LEDGER_INBOX_EMAIL_WEBHOOK_SECRET"),
            recognizer=os.getenv("LEDGER_INBOX_RECOGNIZER", "mock"),
            ledger_sink=os.getenv("LEDGER_INBOX_LEDGER_SINK", "directory"),
            model_base_url=os.getenv(
                "LEDGER_INBOX_MODEL_BASE_URL", "http://127.0.0.1:11434/v1"
            ).rstrip("/"),
            model_api_key=os.getenv("LEDGER_INBOX_MODEL_API_KEY", "local"),
            model_name=os.getenv("LEDGER_INBOX_MODEL_NAME", "qwen3-vl:4b"),
            model_timeout_seconds=float(
                os.getenv("LEDGER_INBOX_MODEL_TIMEOUT_SECONDS", "90")
            ),
            ledger_webhook_url=os.getenv("LEDGER_INBOX_LEDGER_WEBHOOK_URL"),
            ledger_webhook_secret=os.getenv("LEDGER_INBOX_LEDGER_WEBHOOK_SECRET"),
            trust_proxy_headers=_env_bool("LEDGER_INBOX_TRUST_PROXY_HEADERS", False),
        )
