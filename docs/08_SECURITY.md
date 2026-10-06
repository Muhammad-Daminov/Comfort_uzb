# 08 — Security

**Purpose:** Splits Master TZ §12 ("Xavfsizlik") out into its own document, as `docs/00_INDEX.md` names as owed by this phase. Documents what is actually implemented and how it was verified — not a policy aspiration.
**Owner:** security
**Last updated:** 2026-08-18
**Dependencies:** [00_MASTER_TZ.md](00_MASTER_TZ.md) §12, [tasks/Phase-08-Security.md](tasks/Phase-08-Security.md), [06_OPEN_DECISIONS.md](06_OPEN_DECISIONS.md) (OPEN-2)

Every claim below is labeled with how it was established:
- **Verified by automated test** — a test exists, was run, and passed as part of this phase's work.
- **Verified by code review** — read and reasoned about directly; no automated test exercises it (either because it is a property of the code shape, not a runtime behavior, or because it requires an environment this repository doesn't build, e.g. a deployed Nginx).
- **Verified manually** — exercised by hand once, not repeatable via `pytest`.
- **Not tested** — named for completeness; no verification was performed.

No claim of penetration testing, production load testing, browser/device testing, or a completed production deployment is made anywhere in this document.

## Authentication

**Mechanism**: Telegram `initData` HMAC-SHA256 verification (`app/security/telegram_auth.py`), per Telegram's own documented WebApp validation scheme — `secret_key = HMAC_SHA256("WebAppData", bot_token)`, then the request's own hash is checked against `HMAC_SHA256(secret_key, data_check_string)`. A verified `initData` exchanges for an app-issued session token (`POST /auth/session`) — an HMAC-signed opaque token (`app/security/session.py`), not a JWT, carrying only a user id, not a role or permission claim.

**Session/token behavior**: every authenticated request re-reads `role`/`status` from `users` on every call (`get_current_user`, `app/security/permissions.py`) — the token proves *which user*, never *what they're allowed to do right now*. This is deliberate: a role change or deactivation takes effect on the very next request, not at next-token-issue.

**Deactivated-account behavior**: `get_current_user` raises 403 (not 401) when `status != 'ACTIVE'`, even though the token itself is still cryptographically valid — Verified by automated test (`tests/integration/test_security_suite.py::test_deactivated_user_token_is_rejected`, `tests/integration/test_owner_admin_management.py`).

**Authentication failure behavior**: malformed/expired/tampered `initData` → 401 via `InvalidInitData`; malformed/forged session token → 401 via `InvalidSession`; missing `Authorization` header → 401. No case falls through to a 500. Verified by automated test (`test_security_suite.py::test_broken_init_data_is_401`, `::test_malformed_bearer_token_is_401`, `tests/unit/test_telegram_auth.py`).

## Authorization

Role/permission data lives in `roles`/`permissions`/`role_permissions` (REQ-IDT-004 — data, not hardcoded, so a future role like `SENIOR_ADMIN` needs no code change to the check path itself, only a new `role_permissions` row). `require_permission(key)` (`app/security/permissions.py`) is the single enforcement point, used by every non-public endpoint.

### Actual permission matrix (seeded by migration `0001_identity`)

| Permission key | OWNER | ADMIN | USER |
|---|---|---|---|
| `catalog.view` | ✓ | ✓ | ✓ |
| `products.create` / `products.update` / `products.archive` | ✓ | ✓ | – |
| `inventory.manage` | ✓ | ✓ | – |
| `orders.view.all` | ✓ | ✓ | – |
| `orders.view.own` | ✓ | ✓ | ✓ |
| `orders.confirm` / `orders.cancel` | ✓ | ✓ | – |
| `payments.review` | ✓ | ✓ | – |
| `receipts.view` | ✓ | ✓ | ✓ (own only, app-enforced, see IDOR below) |
| `sell_requests.review` / `chat.reply` / `broadcast.send` | ✓ | ✓ | – (P1/P2/P3 — permissions seeded now, endpoints not yet built, out of Phase 08's scope) |
| `finance.view` | ✓ | – | – |
| `analytics.view` | ✓ | – | – |
| `admins.manage` | ✓ | – | – |
| `audit.view` | ✓ | – | – |
| `settings.manage` | ✓ | – | – |

OWNER holds every permission (`role_permissions` seeds ADMIN's list explicitly, USER's list explicitly, and gives OWNER *all* rows — see `0001_identity.py`). The five OWNER-only rows in the bottom half of the table are the hard financial/administrative boundary named in this phase's brief; ADMIN cannot reach any of them — Verified by automated test (`test_security_suite.py::test_admin_hitting_finance_view_gets_403`, `::test_admin_cannot_manage_admins`; `tests/integration/test_owner_authorization_matrix.py`, the pre-existing Phase 07 matrix suite).

There is exactly one OWNER row at all times, enforced by a partial unique index (ADR-11) — `role_permissions` gives that one row every permission, it is not a separate "superadmin" code path.

USER hitting an OWNER/ADMIN-only endpoint → 403 — Verified by automated test (`test_security_suite.py::test_user_hitting_owner_endpoint_gets_403`).

## IDOR

| Resource | Protection | How verified |
|---|---|---|
| Orders | `order.user_id == current_user.id` or `orders.view.all`, checked in the Router | Automated test — `tests/integration/test_idor_regression.py` (added Phase 08; the check itself predates this phase, Phase 03, but had no dedicated regression test until now) |
| Cart | `cart_id` is always derived server-side from `current_user.id` (`get_or_create_cart`) — never accepted from the client in any form — structurally impossible to reference another user's cart | Automated test — `tests/integration/test_cart_soft_delete.py::test_removing_another_users_item_is_a_safe_noop_not_idor` |
| Products / images / compatibility | Public read (catalog is not user-scoped); writes gated by `products.update`/`.create`/`.archive`, not by any per-row ownership (there is none — products belong to the store, not a user) | Code review — ownership model doesn't apply here by design |
| Payments / receipts | Upload endpoint checks `order.user_id == current_user.id` before accepting a receipt for that payment | Automated test — `test_security_suite.py::test_user_cannot_view_another_users_payment_receipt_path` (new this phase — no prior test exercised this path) |
| Inventory | Gated by `inventory.manage` only (no per-admin ownership concept for stock) | Code review |
| Admin management | Gated by `admins.manage` (OWNER-only); `owner_service.create_admin` has no `role` parameter at all — an ADMIN cannot be handed OWNER even by a caller bug, because the function signature doesn't accept one | Automated test — `test_security_suite.py::test_admin_creating_another_admin_cannot_grant_owner` (signature inspection + direct call) |

Client-supplied `role` fields anywhere in a request body are ignored — role is derived exclusively from the `users` row matched by session token, never from request payload. Verified by automated test (`test_security_suite.py::test_client_supplied_role_field_is_ignored_at_session_creation` — a tampered `initData.user.role` claim is silently discarded, the created session is `USER`).

## SQL injection

All application SQL is parameterized `asyncpg` (`$1`, `$2`, ...) — ADR-015 (raw asyncpg, no ORM, no string-built SQL). Verified by code review: every `conn.fetch`/`fetchrow`/`execute` call across `app/domains/**/repository.py` was written with placeholder parameters; the only string-*interpolated* SQL fragments are internally-generated column names/operators chosen from a fixed allowlist (e.g. `_SORT_COLUMNS` in `catalog/repository.py`, condition fragments built by each repository's own `add()` helper appending `${n}` placeholders, never raw user input) — never a value coming directly from request input. No `.format()`/f-string/`%`-interpolation of a *value* into a query body exists anywhere in `app/`.

## File upload security

(`app/security/uploads.py`, covers both product images and payment receipts — one pipeline, parametrized by folder.)

- **MIME validation**: magic-byte sniffing only (`_sniff_mime`) — JPEG/PNG/WebP signatures checked against the first bytes of the actual file content. The declared `Content-Type` header and filename extension are never trusted or even read by the validation path.
- **Decodability**: Pillow (`Image.open(...).load()`) must successfully decode the bytes as a real image, or the upload is rejected — a file that merely starts with the right magic bytes but isn't a valid image also fails.
- **Size limits**: 5MB raw input cap, 1MB processed-output cap (`MAX_UPLOAD_BYTES`, `MAX_PROCESSED_BYTES`).
- **Filenames**: always server-generated (`uuid.uuid4()`), never derived from client input in any way — the function doesn't even accept a client filename parameter, so there is no code path for one to influence the stored path.
- **Directories**: always a fixed literal (`products`, `receipts`) plus, for products, a FastAPI-path-validated integer `entity_id` — no free-form path segment from a client ever reaches `Path(uploads_root) / relative_path`.
- **EXIF/metadata**: stripped implicitly — the pipeline re-encodes to WebP from decoded pixel data rather than copying the original bytes/metadata forward, so GPS/camera metadata never survives.
- **Executable/`.php` upload**: rejected — has no image magic-byte signature, fails `_sniff_mime`, raises `InvalidUpload` → 422, regardless of what extension or MIME type the client claims.

Verified by automated test — `tests/integration/test_security_suite.py`: `test_executable_disguised_as_image_is_rejected`, `test_php_with_fake_extension_still_sniffed_and_rejected`, `test_oversized_upload_is_rejected`, `test_empty_upload_is_rejected`, `test_generated_filename_never_derived_from_input`. **This is genuinely new coverage** — `app/security/uploads.py` had zero tests of any kind before Phase 08-FINAL.

## Database security

- `comfort_app` (the role the application connects as in production): `SELECT, INSERT, UPDATE` on all tables, **zero `DELETE` grant, blanket, no exceptions** (§12.2). Confirmed by an exhaustive `grep -rn "DELETE FROM"` across `app/` and `bot/` (excluding migrations, which run as `comfort_migrate`, and test code): the only production-path occurrence was the cart-item removal bug fixed in the Phase 08 hardening pass (migration `0016_cart_items_soft_delete`) — none remain.
- Soft-delete-everywhere: every table that needs row removal uses `deleted_at TIMESTAMPTZ` + a partial unique index (`WHERE deleted_at IS NULL`) instead of `DELETE` — `products`, `product_variants`, `product_images`, `brands`, `colors`, `product_compatibilities`, `cart_items`. `store_settings` uses upsert-only (no removal concept at all).
- `comfort_migrate`: full DDL, used only by Alembic, never by the running application.
- `comfort_backup`: `SELECT`-only, used only by the backup process (Phase-09).
- `audit_logs` is additionally append-only at the trigger level (`prevent_audit_mutation()`, migration `0011_security`) — even a role with UPDATE/DELETE grant on it (e.g. a superuser during a manual investigation) is blocked by the trigger, not just by role privilege. Verified by automated test — `tests/db/test_schema.py::TestAuditAppendOnly` (must be run as a role that actually holds UPDATE/DELETE grants, e.g. the migration/dev role, for the trigger itself to be the thing under test — running it as `comfort_app`, which lacks the grant entirely, only proves the role check, not the trigger, and is not the intended configuration for this specific test file).
- Migration-role bootstrap (`provision_roles.sql` → `alembic upgrade head` as `comfort_migrate`) verified end-to-end against a disposable database — Verified by automated test (`tests/db/test_migration_role_e2e.py`).
- "External `psql -h <server_ip>` doesn't connect" (§12.6) is a `pg_hba.conf`/firewall property of the deployed server, not application code — **Not tested** in this repository; it is Phase-09's responsibility.

## Secrets

Repository-wide audit for hardcoded credentials, API keys, JWT/session secrets, database passwords, Telegram bot tokens, and private keys: `Settings.from_env()` (`app/config.py`) requires every security-sensitive value (`DATABASE_URL`, `BOT_TOKEN`, `SESSION_SECRET`, `SIGNING_SECRET`) from the environment and fails loudly at startup if any is missing — there is no hardcoded fallback for any of them. Test files use literal placeholder strings (e.g. `"idor-test-bot-token"`, `"sec-suite-session-secret"`) — these are not real secrets, exist only to make deterministic HMAC signatures inside tests, and are never used outside test process environment variables. **No real secret was found committed anywhere in the repository.** `.env` handling (`chmod 600`, ownership) is a Phase-09 deployment-runbook item, not application code.

## Error exposure

- Every router maps expected failure modes (`ValueError`, `LookupError`, domain-specific exceptions like `InvalidUpload`/`InsufficientStock`) to a specific 4xx/409 with a safe, human-written `detail` string — never a raw exception message or Postgres error text.
- **New this phase**: a global exception handler (`app/observability.py::install_exception_handling`) now catches every *unexpected* exception (anything not already mapped by a router) and returns a fixed `{"detail": "internal server error", "request_id": "..."}` body with status 500 — never the exception's own message, type name, or traceback. The full exception (with traceback) is logged server-side only, tagged with the same `request_id` so a user-reported problem can be matched to its server-side log line. Verified by automated test — `test_security_suite.py::test_unhandled_exception_returns_generic_body_not_a_stack_trace` (forces a real unhandled `RuntimeError` containing a fake secret string mid-message and asserts the string never appears in the response).
- Expected 4xx responses are logged at WARNING (or not logged as failures at all), never at the same severity as a genuine unhandled exception — an expected "order not found" is not treated as an application crash. Verified by automated test — `test_security_suite.py::test_expected_404_is_not_treated_as_a_server_error`.
- Before this phase, an unexpected exception would still 500 safely (Starlette's own default behavior does not leak a traceback to the client when `debug=False`, which was already the case), but **was invisible — nothing logged it anywhere.** This was the concrete gap OPEN-2 names. See "Observability" below.

## Observability (OPEN-2 resolution)

`docs/06_OPEN_DECISIONS.md` OPEN-2 offered two options without deciding: Sentry, or ERROR-log → Telegram. This phase implements the **log-based mechanism** (`app/observability.py`) — no new external dependency, no new third-party account to secure, matching the open-decision's own stated recommendation (b).

**What exists now**: structured JSON logging (`configure_logging()`), a per-request correlation id (`X-Request-ID` header, generated per request, included in every log line and in every error response body), and a global exception handler that guarantees an unhandled exception is always logged with its full traceback and never silently lost. Configurable via `LOG_LEVEL` (defaults to `INFO`); the application functions identically with no configuration at all — there is no "monitoring unavailable" failure mode, because there is no external service to be unavailable.

**Updated in Phase 09**: `deploy/systemd/comfort-api.service` sets `StandardOutput=journal`/`StandardError=journal`, so every structured log line — including every unhandled-exception log — has a concrete destination (`journalctl -u comfort-api`) that survives process restarts and rotates via journald/logrotate (§17.6: 14 days). Separately, `deploy/systemd/comfort-health.{service,timer}` implements the disk-usage-to-Telegram alert §17.6 names, as a standalone ops script with zero application-code coupling (a plain `curl` call to the Bot API, not aiogram). **Not verified**: neither the journald destination nor the health-check's Telegram-send path has been exercised against a real systemd instance (no systemd service manager available in this development environment; see `docs/09_DEPLOYMENT.md`). **OPEN-2 is resolved at the mechanism-choice level (log-based, not Sentry), the application-code level (every exception is observable), and now has a documented, reviewed — but not live-verified — production destination.**

## Rate limiting

**Implemented in Phase 09** at the Nginx layer, not in application code: `deploy/nginx/comfort.conf.template`'s `limit_req_zone` directives match the Master TZ §12.4 table exactly (general 60/min, `/orders`/`/payments` 5/min, upload-bearing routes 10/min, `/catalog/search` 30/min, admin confirm/cancel/review 60/min). No in-app rate-limiting framework was added — Nginx was judged the simpler, more appropriate layer (also where the TZ's own table says a second enforcement layer belongs), avoiding new application middleware/dependencies. **Not load-tested** — no Nginx instance is available in this development environment to exercise the zones against real concurrent traffic; see `docs/09_DEPLOYMENT.md`.

## Signed URLs (ADR-13)

Generation (`app/security/signing.py`) and, **new in Phase 09**, verification (`deploy/nginx/comfort.conf.template`'s `secure_link`/`secure_link_md5` block, matching the exact string format the signer hashes) both exist now. The §12.6 cases "unsigned request → 403", "expired signature → 410", "wrong-owner receipt signature → 403" have a real verifying layer to run against for the first time — but the config has not been syntax-checked (`nginx -t`) or exercised against live traffic (no Nginx binary in this development environment), so these three cases remain **Not tested** in practice, distinct from Phase 08's "not testable at all." See `docs/09_DEPLOYMENT.md` "Nginx / HTTPS".

## Server security (§12.5)

SSH hardening, `ufw`, `fail2ban`, `unattended-upgrades`, non-root process user, HTTPS/Certbot, Nginx `server_tokens off`/HSTS, log rotation — configuration for these exists as of Phase 09 (`deploy/nginx/comfort.conf.template` for `server_tokens off`/HSTS; `deploy/systemd/comfort-api.service` for non-root execution) but SSH/`ufw`/`fail2ban`/`unattended-upgrades`/Certbot itself all remain properties of a real deployed server this project does not have. **Not applicable / not verified** — no VPS exists; see `docs/09_DEPLOYMENT.md` "Deferred items".

## CORS

**Implemented in Phase 09** (`app/cors.py`): `ALLOWED_ORIGINS` env var, comma-separated, empty by default — `CORSMiddleware` is not even installed unless at least one origin is configured. The primary deployment model (Nginx serves the Mini App build and proxies the API from the same domain) needs no CORS grant at all, since same-origin requests are never subject to CORS — this env var exists for the genuinely cross-origin cases (a separately-hosted frontend, local dev against a deployed backend). `*` is never used; `allow_credentials=False` (bearer tokens, not cookies).

## AI admin assistant (v2 rebuild, 2026-09-29)

Verified against the codebase as it stands, not a new audit — every point below cites the actual enforcing code.

- **No arbitrary SQL / no direct DB mutation from AI output.** Every AI command is one of a fixed, enumerated set (`app/ai/commands.py::COMMAND_SPECS`), each with a strict pydantic payload model. There is no code path from AI-provider output to a raw SQL string or an unvalidated dict reaching a repository function — `app/ai/executor.py`'s dispatch table calls the exact same domain-service functions (`catalog_service.*`, `inventory_repository.adjust_stock`, ...) the manual admin HTTP endpoints call.
- **AI-generated IDs are never trusted.** The AI may only name things in free text (`product_query`/`brand_query`); `app/ai/resolver.py` resolves these to real ids via a DB lookup, raising `ProductNotFound`/`AmbiguousReference` instead of guessing when the lookup isn't exact. `CREATE_PRODUCT`'s `brand_id` is required by the schema and never inferred — a command missing it fails validation rather than picking a brand.
- **Permission enforcement is identical to the manual endpoints, by construction.** Each `COMMAND_SPECS` entry names the exact `permissions` key its manual equivalent requires (`GET_REVENUE`/`GET_PROFIT`/`GET_COST_PRICE` → `finance.view`; stock/price/archive → `inventory.manage`/`products.update`/`products.archive`), checked via the same `has_permission()` function — the AI cannot grant itself a permission the caller's role doesn't already hold. `ai.assistant.use` gates the assistant itself; the Telegram bot's `_admin_or_owner` filter additionally means a non-admin sender's message is never even routed to the AI handler (it silently falls through to the ordinary USER bot flow — no "forbidden" reply exists to confirm to a prober whether an account has elevated access).
- **Confirmation is bound to admin + draft + frozen payload + entity + permission + expiry, and is one-time.** `app/ai/drafts/service.py::confirm()` re-checks the caller is the draft's own creator, the token matches, the draft is still `PENDING` and unexpired, the permission still holds (a role change between draft and confirm is caught), and re-validates the *stored* payload — never new values from the confirm call. A second confirm attempt gets `DraftNotPending`. `test_concurrent_duplicate_confirm_only_one_succeeds` (`tests/integration/test_ai_drafts_workflow.py`) proves this under a genuine race, not just sequentially.
- **Cost price is protected end to end.** `GET/PATCH /admin/variants/{id}/cost-price` and the AI's `GET_COST_PRICE`/`CREATE_PRODUCT.cost_price` are all gated by `finance.view`, which ADMIN does not hold (`products.update` ≠ `finance.view` — verified by `tests/integration/test_admin_permissions_boundary.py::test_only_owner_can_set_cost_price`). `GET /catalog/products`, `GET /catalog/products/{id}`, and every other USER-facing response never select `cost_price` (`catalog/repository.py::get_variants_for_product`). The Mini App's admin product editor only renders/fetches the cost-price row when `isOwnerRole()` is true.
- **Telegram file_ids are never treated as authorization.** A photo's `file_id` is used only to download image bytes at AI-draft confirm time; the IMAGE+VOICE correlation window (`app/ai/pending_media.py`) is scoped and claimed by `(admin_id, chat_id)` derived from the authenticated Telegram sender on each message, never by anything in the file reference itself — a second admin, or the same admin in a different chat, cannot claim another admin's pending photo (`tests/integration/test_ai_pending_media.py::test_wrong_admin_cannot_claim_another_admins_photo`/`test_wrong_chat_does_not_correlate`).
- **Secrets stay server-side.** `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`HAMYON_*` are read only via `app/config.py::Settings.from_env()`, never hardcoded, never sent to the Mini App or logged; provider failure messages (`ProviderNotConfigured`) describe *what* failed (timeout, HTTP status, malformed response), never the key value.
- **Payment webhook surface is unchanged.** No new webhook endpoint was added by this pass — `HamyonPaymentProvider.verify_callback()` is an unreachable stub (raises `ProviderNotConfigured`) since `PAYMENT_PROVIDER=hamyon` is not the active provider and no Hamyon docs exist to validate a real callback against (`13_V2_REBUILD_AUDIT.md` §2). The existing Telegram bot webhook's `X-Telegram-Bot-Api-Secret-Token` HMAC check (`bot/main.py`) is untouched.
