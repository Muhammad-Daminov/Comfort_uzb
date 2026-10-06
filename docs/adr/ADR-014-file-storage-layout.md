# ADR-014 — Upload Directory Layout

**Status:** Accepted
**Owner:** security
**Domain:** File Storage
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-14, §11

## Context
File organization needs to support per-folder TTL/retention rules (ADR-13's TTL table), purge workers that operate by date, and strict ownership (a user must never be able to name or overwrite another user's file).

## Decision
```
/var/comfort/uploads/
├── products/{product_id}/{uuid}.webp
├── products/{product_id}/thumbs/{uuid}.webp
├── receipts/{yyyy}/{mm}/{uuid}.webp
├── sell-requests/{request_id}/{uuid}.webp
└── chat/{conversation_id}/{uuid}.webp
```
- Filenames are always server-generated `uuid4` — user-supplied names are never used, closing a path-traversal/collision class of bug outright.
- Receipts are bucketed by year/month specifically so `comfort-receipt-purge` can operate on whole date-bucketed directories.
- Ownership/permissions: `chown comfort:www-data`, `640` on files, `750` on directories.
- This directory is **not** an Nginx document root — it's only reachable through `/files/` with a valid ADR-13 signature.

## Consequences
- `security` owns this layout and the upload validation pipeline (§11.2: MIME allowlist, magic-byte check, 5MB/1MB size caps, executable rejection); any domain producing uploads (Catalog, Payments, Marketplace, Communication) writes into its assigned subtree and nowhere else.
- `devops` ensures the ownership/permission bits are set correctly at provisioning time and that Nginx's root is never pointed at `/var/comfort/uploads/` directly.
- REQ-TST-001 mandates a `.php`/executable upload rejection test.

## Amendment 2026-09-19 (post-audit)
Receipts are stored **flat** — `receipts/{uuid}.webp` — not date-bucketed as the tree above shows. Phase 03 shipped the flat layout and every later phase (purge worker, tests, seeded data) depends on it; the date buckets existed only to let `comfort-receipt-purge` remove whole directories, but the worker purges by `payment_receipts.retention_until` row by row (ADR-9), so the buckets bought nothing. The tree above is therefore corrected in practice to `receipts/{uuid}.webp`; product images keep `products/{product_id}/{uuid}.webp`. File modes are enforced by the application (0640 files, 0750 directories — `app/security/uploads.py`) and the group is `www-data` (`deploy/scripts/bootstrap.sh`), so Nginx can serve them.
