"""`comfort-receipt-purge` business logic (ADR-9, §11 retention policy).
Callable directly — no systemd/timer dependency — so it's unit-testable on
its own; `devops` wires this into a daily systemd timer in Phase-09, same
split as `reservation_expiry.py`.

ADR-9: the `payments`/`payment_receipts` DB rows are never deleted — only
the uploaded file is purged, once `retention_until` (upload + 30 days) has
passed. `file_purged_at` is stamped so a row is never reprocessed.
"""
from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

from app.domains.payments import repository as payments_repository

logger = logging.getLogger("comfort.worker")


async def run_once(conn: asyncpg.Connection, *, uploads_root: str, batch_size: int = 100) -> int:
    """Purges up to `batch_size` receipt files past their retention date in
    one call. Returns the number of files actually purged (0 if none were
    due, or if a concurrent run already purged them all — always safe to
    re-invoke, per the guarded-update no-op contract). A missing file on
    disk is not an error — the DB row is still marked purged, since the
    end state (no file present) already holds."""
    root = Path(uploads_root).resolve()
    due = await payments_repository.get_receipts_due_for_purge(conn, limit=batch_size)
    purged_count = 0

    for receipt in due:
        candidate = (root / receipt["storage_path"]).resolve()
        if candidate == root or root not in candidate.parents:
            # storage_path is always server-generated (app/security/uploads.py),
            # never client input, but this guard is kept as a hard backstop
            # against ever unlinking a path outside the managed upload root —
            # including the root directory itself (an empty/"." path).
            logger.warning("receipt %s has an out-of-root storage_path — skipped", receipt["id"])
            continue

        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            # One undeletable file (permissions, a directory where a file
            # was expected) must not abort the rest of the batch.
            logger.exception("receipt %s file could not be removed — skipped", receipt["id"])
            continue

        marked = await payments_repository.mark_receipt_purged(conn, receipt_id=receipt["id"])
        if marked:
            purged_count += 1

    return purged_count


async def _work(conn: asyncpg.Connection, settings) -> int:
    return await run_once(conn, uploads_root=settings.uploads_root)


def main() -> None:
    """`python -m app.workers.receipt_purge` — the command
    `comfort-receipt-purge.service` runs, daily (ADR-9 retention)."""
    from app.workers._entrypoint import LOCK_KEY_RECEIPT_PURGE, main as _main

    _main("comfort-receipt-purge", LOCK_KEY_RECEIPT_PURGE, _work)


if __name__ == "__main__":
    main()
