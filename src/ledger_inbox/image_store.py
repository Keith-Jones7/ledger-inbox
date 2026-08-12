from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

SUPPORTED_TYPES = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "heic": "image/heic",
    "avif": "image/avif",
}


def detect_image_type(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", SUPPORTED_TYPES["png"]
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", SUPPORTED_TYPES["jpeg"]
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", SUPPORTED_TYPES["webp"]
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}:
            return "heic", SUPPORTED_TYPES["heic"]
        if brand in {b"avif", b"avis"}:
            return "avif", SUPPORTED_TYPES["avif"]
    return None


class ImageStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, tenant_id: str, data: bytes) -> tuple[str, str, str]:
        detected = detect_image_type(data)
        if detected is None:
            raise ValueError(
                "attachment is not a supported PNG, JPEG, WebP, HEIC, or AVIF image"
            )
        extension, media_type = detected
        digest = hashlib.sha256(data).hexdigest()
        destination = self.root / tenant_id / digest[:2] / f"{digest}.{extension}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise RuntimeError("stored image hash mismatch")
            return digest, media_type, str(destination)
        fd, temp_name = tempfile.mkstemp(prefix=".incoming-", dir=destination.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, destination)
            directory_fd = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temp_path.unlink(missing_ok=True)
        return digest, media_type, str(destination)
