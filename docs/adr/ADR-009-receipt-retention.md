# ADR-009 — Receipt Retention: Metadata Forever, File 30 Days

**Status:** Accepted
**Owner:** security
**Domain:** Payments / Security
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-9

## Context
Disputes need to answer "was this receipt hidden before or after an admin reviewed it?" — a user hiding a receipt pre-review looks very different from hiding it post-approval. Disk budget (§11.4) also caps how long raw receipt images can be kept.

## Decision
The `payments` DB row is never deleted. Only the file is purged. `payment_receipts` tracks: `storage_path`, `visibility_status` (VISIBLE/HIDDEN_BY_USER/HIDDEN_BY_ADMIN), `hidden_at`, `hidden_by`, `retention_until` (upload + 30 days), `file_purged_at`, `reviewed_at`, `review_result` (APPROVED/REJECTED). The before/after-review question is answered purely by comparing timestamps:
- `hidden_at < reviewed_at` → hidden **before** review ⚠️
- `hidden_at > reviewed_at` → hidden **after** review ✅
- `reviewed_at IS NULL` → not yet reviewed

The OWNER panel surfaces the ⚠️ case as a visible warning flag. `comfort-receipt-purge` (daily 04:00) deletes files past `retention_until` from disk and stamps `file_purged_at`; metadata is permanent.

## Consequences
- `backend-commerce` (Payments) never hard-deletes a `payment_receipts` row under any circumstance — this is a REQ-BIZ-009 hard rule.
- `security` owns the purge worker's logic (retention policy is a security/compliance concern); `devops` owns its systemd scheduling.
- Any UI showing receipt history must render the ⚠️ warning when `hidden_at < reviewed_at`, not just show a generic "hidden" state.
