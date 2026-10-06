"""Upload validation + processing pipeline (§11.2, §11.3). Originally built
in Phase 03 for payment receipts only; generalized in Phase 06 to also
serve product images, per this module's own original docstring promise
("reusable, not reinvented, when Phase-06 needs the same pipeline") — same
validation/processing rules, just parametrized by target folder + entity id
instead of hardcoded to `receipts/`.
"""
from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PROCESSED_BYTES = 1 * 1024 * 1024
MAX_LONG_SIDE = 1600
WEBP_QUALITY = 85

# Magic-byte signatures — §11.2 "kengaytmaga ishonilmaydi" (extension is not
# trusted, the file is sniffed).
_MAGIC_BYTES: dict[str, bytes] = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}
# WebP's signature is RIFF....WEBP — check separately (12-byte pattern).


class InvalidUpload(Exception):
    """Rejected upload — oversized, wrong type, or fails magic-byte sniff.
    Callers map this to HTTP 422."""


async def read_upload_limited(file, *, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Reads an `UploadFile` but stops as soon as it exceeds the limit —
    `await file.read()` with no bound pulled an arbitrarily large body into
    memory before the size check ever ran (Nginx's client_max_body_size is
    the outer guard, but the application must not depend on it)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise InvalidUpload(f"upload exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _sniff_mime(file_bytes: bytes) -> str | None:
    for mime, magic in _MAGIC_BYTES.items():
        if file_bytes.startswith(magic):
            return mime
    if len(file_bytes) >= 12 and file_bytes[0:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(frozen=True)
class ProcessedUpload:
    storage_path: str
    width: int
    height: int
    bytes_size: int


def validate_and_process_image(
    file_bytes: bytes, uploads_root: str, *, folder: str, entity_id: int | None = None
) -> ProcessedUpload:
    """Validates, strips EXIF, converts to WebP, caps dimensions, saves
    under `<uploads_root>/<folder>/[<entity_id>/]<uuid4>.webp`, returns
    metadata for the caller's own table. Raises InvalidUpload on any
    validation failure — nothing partially-invalid is ever written to disk.

    `entity_id` nests the file under a per-entity subdirectory (ADR-14's
    documented layout, `products/{product_id}/{uuid}.webp`) — omitted for
    receipts, which Phase 03 already shipped flat (`receipts/{uuid}.webp`,
    a pre-existing deviation from ADR-14's date-bucketed receipts layout,
    left as-is here since it's already in production use, not this
    change's concern to retroactively fix)."""
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise InvalidUpload(f"upload exceeds {MAX_UPLOAD_BYTES} bytes")
    if len(file_bytes) == 0:
        raise InvalidUpload("empty upload")

    mime = _sniff_mime(file_bytes)
    if mime is None:
        raise InvalidUpload("unrecognized or disallowed file type")

    try:
        image = Image.open(io.BytesIO(file_bytes))
        image.load()
    except Exception as exc:  # Pillow raises various exceptions for corrupt/non-image data
        raise InvalidUpload("file is not a valid, decodable image") from exc

    # §11.3: EXIF stripped by never copying it — building a fresh image from
    # pixel data and re-encoding, rather than saving with exif=... kwarg,
    # ensures no metadata (including GPS) survives.
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    long_side = max(image.size)
    if long_side > MAX_LONG_SIDE:
        scale = MAX_LONG_SIDE / long_side
        new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(new_size, Image.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=WEBP_QUALITY)
    processed_bytes = buffer.getvalue()

    if len(processed_bytes) > MAX_PROCESSED_BYTES:
        raise InvalidUpload(f"processed image still exceeds {MAX_PROCESSED_BYTES} bytes")

    filename = f"{uuid.uuid4()}.webp"
    relative_path = f"{folder}/{entity_id}/{filename}" if entity_id is not None else f"{folder}/{filename}"
    destination = Path(uploads_root) / relative_path
    # ADR-14: files 0640, directories 0750 — the app user owns them and the
    # `www-data` group (Nginx, which serves /files/) may read them; nobody
    # else. Explicit, so the process umask cannot leave receipts world-
    # readable or, the other way round, unreadable to Nginx.
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    destination.write_bytes(processed_bytes)
    try:
        destination.chmod(0o640)
    except OSError:
        pass  # non-POSIX or foreign-owned root: leave the umask result

    return ProcessedUpload(
        storage_path=relative_path,
        width=image.width,
        height=image.height,
        bytes_size=len(processed_bytes),
    )


def validate_and_process_receipt(file_bytes: bytes, uploads_root: str) -> ProcessedUpload:
    """Unchanged call shape for `payments/service.py` — thin wrapper over
    the generalized function above, `entity_id=None` preserves the exact
    flat `receipts/<uuid>.webp` layout Phase 03 already shipped."""
    return validate_and_process_image(file_bytes, uploads_root, folder="receipts")
