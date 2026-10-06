# 09 — Deployment

**Purpose:** Splits Master TZ §16–§17 (server config + deployment) out into its own document, as `docs/00_INDEX.md` names as owed by this phase. Documents the actual deployment architecture, procedure, and — critically — what has and has not actually been verified.
**Owner:** devops
**Last updated:** 2026-08-18
**Dependencies:** [00_MASTER_TZ.md](00_MASTER_TZ.md) §16–§17, [08_SECURITY.md](08_SECURITY.md), [adr/ADR-001-unified-backend.md](adr/ADR-001-unified-backend.md), [adr/ADR-013-signed-urls-nginx.md](adr/ADR-013-signed-urls-nginx.md)

**No VPS, domain, or DNS exists for this project yet.** Everything in this document below "Architecture" is either (a) code that runs and was verified locally, or (b) configuration/scripts that were written, reviewed, and — where the local environment allowed it — exercised against a disposable stand-in, but never against the real target (a live Nginx install, a real domain, a real Contabo VPS). Each section says explicitly which case it is. Nothing here should be read as "production is live."

## Architecture

```
Internet
  │  HTTPS (Certbot-issued cert, real domain — not yet provisioned)
  ▼
Nginx  ── / (static)          → miniapp/dist/ build
       ── /files/ (signed)    → verifies ADR-13 secure_link, serves from /var/comfort/uploads
       ── everything else     → reverse proxy → 127.0.0.1:8001
  │
  ▼
FastAPI (uvicorn, 127.0.0.1:8001 only — never bound to a public interface)
  ├── HTTP API (Mini App + admin/owner panels — same app, same Service layer, ADR-1)
  ├── POST /telegram/webhook (bot updates — same process, not a second service, see below)
  └── notification poller (background asyncio task inside the same process, ADR-016)
  │
  ▼
PostgreSQL 16 (localhost only, comfort_app role — §12.2)
```

**One systemd unit for the whole application, not two.** The Master TZ's §17.2/§17.5 sketch names `comfort-api` and `comfort-bot` as if they were separate services. They are not, in the code that actually exists: `bot/main.py`'s own docstring states the webhook route is "mounted into the same FastAPI app the Mini App API uses" per ADR-1 ("one system... same Service layer"), and this phase wired that up for real — `app/main.py`'s `lifespan` now constructs the `Bot`/`Dispatcher`, mounts the webhook router, calls `configure_bot`, and starts the notification poller as a background `asyncio.Task`, all inside the one FastAPI process. Running a second `comfort-bot.service` against the same codebase would start a second, functionally empty process — there is no separate bot entrypoint to run. `deploy/systemd/comfort-api.service` is the only application-process unit.

## Environment configuration

`backend/.env.example` documents every variable read by the application **and** by the backup/health timers (`DATABASE_NAME`, `COMFORT_BACKUP_PASSWORD`, `DATABASE_HOST`, `BACKUP_ROOT`, `RCLONE_REMOTE` — added by the 2026-09-19 audit; without `DATABASE_NAME`, `backup.sh` exits 1 and `deploy.sh` aborted at its backup step), split into runtime secrets (DB credentials, `BOT_TOKEN`, `SESSION_SECRET`, `SIGNING_SECRET`, `TELEGRAM_WEBHOOK_SECRET`) and public configuration (`OWNER_TELEGRAM_ID`, `MINIAPP_URL`, `UPLOADS_ROOT`, `ALLOWED_ORIGINS`, `LOG_LEVEL`). All four secrets, plus `BOT_TOKEN`/`DATABASE_URL`, are read via `_required()` in `app/config.py`/`bot/config.py` — missing any of them raises `RuntimeError` at startup, not a silent default. There is no debug/production toggle in this codebase to accidentally leave on (no `DEBUG` flag exists at all — FastAPI's own `debug=False` default, never overridden, is what keeps a raw traceback from ever reaching a client; see `docs/08_SECURITY.md` "Error exposure").

**`DATABASE_URL` has two different, incompatible-looking formats depending on which process reads it** — this is the single easiest deploy mistake to make, so it is called out three times across this repository (`.env.example`, `alembic/env.py`'s own docstring, and here): the running application uses a plain `postgresql://` DSN as `comfort_app` (asyncpg); Alembic migrations use `postgresql+psycopg://` as `comfort_migrate`. They must never be the same value, and the migration DSN must never be written into the application's own persistent `.env` file (it grants DDL).

### v2 rebuild additions (2026-09-29) — payment provider / AI provider

All new, all optional with a safe default (the app starts and runs fully functional without any of them set):

- `PAYMENT_PROVIDER` — `manual_receipt` (default, today's active flow) or `hamyon`. Setting `hamyon` without all four `HAMYON_*` variables below fails startup on purpose (`RuntimeError` in `app/config.py`) — **no Hamyon API is documented anywhere** (`13_V2_REBUILD_AUDIT.md` §2), so `HamyonPaymentProvider`'s every method raises `ProviderNotConfigured` rather than running a guessed integration against real money. Do not set `PAYMENT_PROVIDER=hamyon` in production until real API documentation exists and the adapter has been implemented against it.
- `HAMYON_API_URL`, `HAMYON_API_KEY`, `HAMYON_MERCHANT_ID`, `HAMYON_WEBHOOK_SECRET` — placeholders only in `.env.example`; required (and currently non-functional) only if `PAYMENT_PROVIDER=hamyon`.
- `AI_PROVIDER` — empty (default; stub deterministic parser handles the AI admin assistant's text commands, see `04_API_SPEC.md` "AI admin assistant") or `anthropic`. `ANTHROPIC_API_KEY` required if set; startup fails loudly otherwise.
- `STT_PROVIDER` — empty (default; voice messages get an actionable "not configured" reply, never fabricated text) or `openai_whisper`. `OPENAI_API_KEY` required if set.
- None of these four keys have ever been supplied in any environment this project has run in — live-provider behavior (`AnthropicAIProvider`, `OpenAIWhisperSTTProvider`) is implemented against each API's publicly documented shape but **is not live-verified**. Verify manually against a real key before enabling in production: send one text command through `/admin/ai/message` (or the bot) with `AI_PROVIDER=anthropic` set, and one voice message with `STT_PROVIDER=openai_whisper` set.

## Database production setup

Privilege model unchanged from Phase 02/08 — `comfort_app` (SELECT/INSERT/UPDATE, zero DELETE, blanket, no exceptions), `comfort_migrate` (DDL, Alembic only), `comfort_backup` (SELECT only). `backend/db/provision_roles.sql` is the authoritative, already-idempotent provisioning script — this phase did not modify it, and did not grant `comfort_app` DELETE, SUPERUSER, CREATEDB, CREATEROLE, or replication privileges under any circumstance (the brief's own explicit prohibition, consistent with every prior phase's audit). **Verified this phase**: re-ran the full migration-role bootstrap (`provision_roles.sql` → `alembic upgrade head` as `comfort_migrate`) against a disposable local cluster — clean.

**v2 rebuild migrations** (2026-09-29): `0017_finance_cancel_refund_ai` (cost price / `cancellation_requests` / `refunds` / `ai_command_drafts`, new `cancellation_requests.*`/`refunds.manage`/`ai.assistant.use` permissions) and `0018_ai_pending_media` (IMAGE+VOICE correlation). Both apply cleanly through the full chain — verified twice this session on disposable databases with **disposable, randomly-generated roles** (never the shared `comfort_app`/`comfort_migrate`/`comfort_backup` cluster roles — see the credential-safety note below), full suite green both times (366/408/419 passed across incremental verification runs, 3 deliberately skipped — see "Credential safety during verification" below).

### Credential safety during verification

Verifying migrations/integration tests requires a real Postgres role with the same grant shape as `comfort_app`/`comfort_migrate`. **Never reuse the real cluster-wide roles for this** — `ALTER ROLE comfort_app/comfort_migrate WITH PASSWORD ...` mutates the live password for every database on the cluster, including any real dev/staging database sharing it (this happened once during this project's history and is documented as an incident in `13_V2_REBUILD_AUDIT.md` §5b). The safe procedure, used for every verification pass since:
1. `createdb` a disposable, uniquely-named database.
2. Copy `db/provision_roles.sql`, substitute the three role names for disposable ones (e.g. `comfort_audit_app`/`comfort_audit_migrate`/`comfort_audit_backup`), generate random passwords, run it against the disposable database only.
3. `alembic upgrade head` as the disposable migrate role; run tests with `TEST_DATABASE_URL`/`SUPERUSER_DATABASE_URL` pointed at the disposable roles/database.
4. `dropdb` the disposable database and `DROP ROLE` the three disposable roles when done.

`tests/db/test_migration_role_e2e.py` and `test_provision_roles_quoting.py` are excluded from this procedure on purpose — they test `provision_roles.sql` itself by design against the literal `comfort_app`/`comfort_migrate`/`comfort_backup` names (see their own docstrings), so they always mutate real cluster-wide state regardless of which database they're pointed at. Run them only on a genuinely disposable cluster, never against any host sharing credentials with a real environment.

## Backups and restore verification

`deploy/scripts/backup.sh` implements §17.3's three-layer sketch's first layer (`pg_dump` as `comfort_backup`, gzipped, plus a `tar` of the uploads directory), with an `flock`-based lock against overlapping runs and 7-day local retention. Off-server copy (`rclone` to e.g. Cloudflare R2) is wired but conditional on `RCLONE_REMOTE` being set — no remote is configured for this project yet, so **the off-server leg of §17.3's backup requirement is not yet satisfied**; local-only backup is not a complete backup per the TZ's own stated rationale. WAL archiving/PITR (§17.3's Layer 2) and manual pre-risk snapshots (Layer 3) are not implemented — Layer 2 requires `archive_mode`/`archive_command` server tuning that has no server to apply it to yet; documented as deferred, not silently skipped.

**Restore genuinely tested, not just scripted**: `deploy/scripts/backup.sh` was run against a local disposable PostgreSQL 16 instance (1233 `users` rows and other tables from this session's accumulated test data), then `deploy/scripts/restore.sh` was run against the resulting dump, restoring into a fresh `comfort_restore_drill` database (never overwriting the source) and verifying row counts on `users`/`products`/`orders`/`audit_logs` — restore succeeded, row counts matched, drill database dropped afterward. This is a real execution, not a code-review claim — but it exercised the scripts' own logic against a local cluster, not the production server (which does not exist), and did not exercise the off-server/rclone leg since no remote is configured.

`deploy/systemd/comfort-backup.service` + `.timer` schedule this daily at 03:00 with `RandomizedDelaySec` and `Persistent=true` (a missed run due to downtime still fires on next boot).

## Nginx / HTTPS

`deploy/nginx/comfort.conf.template` + `deploy/nginx/comfort_proxy.conf` implement: HTTP→HTTPS redirect (with an ACME challenge passthrough for Certbot renewal), the reverse proxy to `127.0.0.1:8001` (FastAPI never bound to a public interface), `client_max_body_size 8m` (headroom over the app's own 5MB upload cap), `server_tokens off` + HSTS (§12.5), and per-endpoint `limit_req_zone` rate limiting following the Master TZ's §12.4 table (general 60/min, orders/payments 5/min, uploads 10/min, search 30/min, admin confirm/cancel 60/min) — see "Rate limiting" below for why this lives in Nginx and not application code. **Audit 2026-09-19:** the `/orders`, `/payments` and `/catalog/search` blocks were plain prefix locations, which nginx ranks below any matching regex location — the general `~ ^/(auth|catalog|…)` block always won, so those zones never applied; they are now `^~`. `/cart/items` was also listed as an "upload" path (10/min) and has been removed from that zone. `http2 on;` (nginx ≥ 1.25.1 only) became `listen … http2`. Still **not runtime-verified** — no nginx binary here.

**ADR-13 signed-URL verification is now implemented in the Nginx config** (`secure_link`/`secure_link_md5`, matching the exact string format `app/security/signing.py` hashes) — this closes the gap Phase 08 explicitly flagged as "not testable in this repo, no verifying layer exists." The config is a *template* (`${DOMAIN}`/`${SIGNING_SECRET}` substituted via `envsubst` at deploy time, since Nginx cannot read OS environment variables directly inside directives).

**Not verified**: this Nginx config has not been syntax-checked with `nginx -t` (no Nginx binary is installed in this development environment) and has never run against a real domain/TLS certificate/live traffic. It should be `nginx -t`-checked and smoke-tested against a real Telegram-served signed URL before being trusted in production.

## Systemd / process management

`deploy/systemd/comfort-api.service` — the one application unit (see "Architecture" above for why there is only one). Runs as a dedicated non-root `comfort` user, `Restart=on-failure`, `NoNewPrivileges=true`, `ProtectSystem=strict` with `ReadWritePaths=/var/comfort/uploads` as the sole writable exception, journald logging. `deploy/systemd/comfort-backup.{service,timer}` and `comfort-health.{service,timer}` schedule the two devops-owned workers (AGENTS/devops.md: "comfort-backup and comfort-health are fully owned by this agent, logic included, authored in Phase-09"). `comfort-reservation-expiry.{service,timer}` (every 5 minutes, §15/ADR-6) and `comfort-receipt-purge.{service,timer}` (daily 03:30, ADR-9) were added in the final hardening pass, once both workers had a real process entrypoint (`python -m app.workers.<name>`, see `app/workers/_entrypoint.py`). Both run as `Type=oneshot` under the `comfort` user, take a Postgres advisory lock so runs cannot overlap, exit non-zero on failure so `systemctl --failed` surfaces them, and are deliberately **not** started inside `comfort-api` — a periodic batch job would otherwise compete with request handling for the API's event loop and pool. `comfort-broadcast` and `comfort-idempotency-cleanup` remain unscheduled: neither has business logic anywhere in the codebase, and `comfort-broadcast` depends on Phase 10 — see "Deferred items."

**Not verified**: no systemd is available to actually install and start these units in this development environment; they have been written and reviewed, not executed as real systemd services.

## Telegram bot production configuration

**Bug found and fixed this phase**: `app/main.py` never actually wired the bot in — `bot/main.py` exposed `build_dispatcher`/`build_webhook_router`/`configure_bot`/`run_notification_poller_forever`, all fully built since Phase 04, but nothing called them. The webhook route did not exist on the running app at all; the notification poller never ran outside of tests. Fixed: `app/main.py`'s `lifespan` now does all four, wrapped so that a Telegram API failure at startup (e.g. `configure_bot`'s Menu Button call) is caught, logged, and does not prevent the HTTP API from starting — verified live: the app was started locally with a deliberately-invalid `BOT_TOKEN`; `configure_bot` failed with `TelegramUnauthorizedError`, was logged, and `/health/live`, `/health/ready`, and `/catalog/products` all served correctly afterward.

**Transport**: webhook, not polling (confirmed by reading `bot/main.py` — there is no `run_polling` call anywhere in this codebase, only `build_webhook_router`). The webhook secret-token check (`X-Telegram-Bot-Api-Secret-Token`) was verified locally, both via a new unit test (`tests/unit/test_bot_webhook.py`) and a real HTTP request against a running local server (missing/wrong secret → 401, correct secret → 200 + dispatched).

**Not verified**: `bot.setWebhook(...)` has never actually been called against Telegram's real API (that requires a real HTTPS URL Telegram can reach, which requires the domain/Nginx/TLS this phase does not have) — so end-to-end "Telegram sends an update, the bot receives it" is unverified, only the receiving side (webhook route → dispatcher) is.

## Mini App production configuration

`miniapp/src/api/client.ts`'s `VITE_API_BASE` defaults to an empty string — same-origin relative requests. This is why the primary deployment model (Nginx serving both `dist/` and the API from one domain) needs no CORS grant at all: same-origin requests are never subject to CORS. Confirmed no `localhost`/hardcoded dev URL exists anywhere in `miniapp/src/` (grepped). Production build re-run this phase: succeeds, `48.04 KB / 12.26 KB gzip`, unchanged from Phase 08 (no frontend source changed).

## CORS / trusted hosts

`app/cors.py` (new this phase): `ALLOWED_ORIGINS` env var, comma-separated, empty by default — no `CORSMiddleware` is even installed unless at least one origin is configured, which is correct for the same-origin deployment model above. `*` is never used. `allow_credentials=False` (the API uses bearer tokens, not cookies, so credentialed CORS was never a requirement). No `TrustedHostMiddleware` was added — Nginx is the only public entry point and already binds FastAPI to `127.0.0.1` only, which is the actual trust boundary; adding host-header validation inside the app as well was judged redundant defense for a single-domain deployment, not added to avoid unnecessary complexity per this phase's own scope constraint.

## File storage

Unchanged from Phase 03/06/08 (`app/security/uploads.py`, `ADR-14`): `UPLOADS_ROOT` (default `/var/comfort/uploads`) must be a persistent directory outside the git checkout, owned by the `comfort` user, surviving restarts/redeploys — `deploy.sh` never touches it, and `comfort-api.service`'s `ReadWritePaths` explicitly grants only this directory write access under `ProtectSystem=strict`. Backed up daily by `backup.sh`'s `tar` step. Signed-URL verification (now implemented in the Nginx template) is the only sanctioned direct-access path — Nginx never serves `/var/comfort/uploads` unsigned.

## Rate limiting

Implemented at the Nginx layer (`deploy/nginx/comfort.conf.template`'s `limit_req_zone` directives), not in application code — Phase 08 documented that no in-app framework existed to add per-endpoint limits to, and building one from scratch was out of that phase's scope; Nginx is also where the Master TZ's own §12.4 table says a second layer belongs regardless ("Nginx darajasida ham"). Limits match the table exactly: general 60/min, `/orders` and `/payments` 5/min, upload-bearing routes 10/min, `/catalog/search` 30/min, admin confirm/cancel/review 60/min. **Not load-tested** — the zone/rate values themselves have not been exercised against real concurrent traffic (no Nginx instance available in this environment).

## Observability

Phase 08's structured JSON logging + `X-Request-ID` correlation + global exception handler now has a concrete production destination: `comfort-api.service` sets `StandardOutput=journal`/`StandardError=journal`, so every log line — including every unhandled-exception log — lands in `journalctl -u comfort-api`, survives process restarts (journald persists independently of the process), and rotates via the system's own `journald`/`logrotate` policy (§17.6: 14 days). No secret/credential is ever included in a log line (verified by code review of every `logger.*` call site — none interpolate a password, token, or full `Authorization` header). `comfort-health.{service,timer}` (new this phase) is the disk-usage-to-Telegram alert §17.6 names — a plain `curl` call to the Bot API, deliberately zero Python/aiogram dependency, since it is ops logic, not application logic. **Not verified**: journald behavior (survives-restart, rotation) was not exercised against a real systemd instance; `comfort-health.sh`'s Telegram-send branch was exercised only for its "no `BOT_TOKEN` configured" failure path locally (a real send was not attempted, since no real bot token or chat exists to safely send a test alert to).

## Health / readiness

`app/health.py` (new this phase — no `/health` endpoint existed before): `GET /health/live` (process-only, never touches the DB — what a process supervisor should act on) and `GET /health/ready` (acquires a pool connection and runs `SELECT 1` — what an external uptime monitor and the deploy script's own post-restart check should use; 503 with `{"status": "not_ready", ...}` if the pool is not yet initialized or the DB is unreachable). Neither endpoint returns any configuration or secret value. Verified: both endpoints exercised via automated tests (`tests/integration/test_health.py`, 3 tests — success, DB-connected-ready, and pool-not-initialized-503) and via a real local HTTP request against a running uvicorn process.

## Deployment procedure

`deploy/scripts/deploy.sh` implements the §17.5 sequence plus a pre-migration backup and a health-check retry loop (it now also refuses to start the migration step without `OWNER_TELEGRAM_ID` exported — migration 0002 needs it on the first deploy; and note that it does **not** render/install the Nginx template or reload Nginx: `envsubst` the template as described in its header, copy `comfort_proxy.conf` to `/etc/nginx/`, `nginx -t`, `systemctl reload nginx` by hand): pull → install deps → **backup** → migrate (as `comfort_migrate`, via a separately-supplied `MIGRATION_DATABASE_URL`, never the app's own persisted env) → build frontend → `rsync` the build into the Nginx web root → restart `comfort-api` → poll `/health/ready` up to 5 times before declaring success or failing loudly. Syntax-checked (`bash -n`) and reviewed; **not executed against a real server** (no VPS exists).

## Rollback procedure

1. **Application code**: `git checkout <previous-tag>` (or `git revert`) in `/opt/comfort`, then re-run steps 2/6/7 of `deploy.sh` (reinstall deps if `requirements.txt` changed, restart, verify health) — skip the migration step entirely unless the rollback also needs a DB downgrade.
2. **Frontend**: re-run the frontend build/rsync steps of `deploy.sh` against the previous commit — the Nginx web root is fully replaced (`rsync --delete`) each deploy, so rolling back is just re-running the same step against older source.
3. **Database migration**: **only** run `alembic downgrade -1` if the specific migration being rolled back is genuinely reversible (its `downgrade()` doesn't destroy data the application still needs) — every migration in `backend/alembic/versions/` up to `0016` is additive-and-reversible by design (documented per-migration), but this must be checked per-migration at rollback time, never assumed. A migration that dropped a column or table is not safely reversible without a separate restore from backup. When in doubt, restore from the pre-deploy backup (`deploy/scripts/backup.sh` runs automatically as `deploy.sh` step 3, before any migration) into a parallel database and cut over, rather than downgrading in place.
4. **Service restart**: `systemctl restart comfort-api` after any of the above; `systemctl status comfort-api` + `journalctl -u comfort-api -n 100` to confirm a clean restart.
5. **Configuration rollback**: `/etc/comfort/backend.env` and the rendered Nginx config are not versioned by `deploy.sh` — keep the previous `.env`/rendered Nginx config as a dated copy before any change (`cp backend.env backend.env.$(date +%F)`) so a config-only rollback doesn't require re-deriving values.

Never a blind `alembic downgrade` as a default rollback action — this is the same principle CLAUDE.md's business-rules section applies elsewhere (destructive DB operations require deliberate justification, not routine use).

## Security verification after deployment

**Not performed** — no VPS is available. Section 19 of the Phase 09 brief (public HTTPS, HTTP redirect, public API, webhook, Mini App, full USER/ADMIN/OWNER flow, uploads, logs, DB connectivity, external confirmation that PostgreSQL is not publicly exposed) requires a real deployed server and has not been claimed as done anywhere in this document.

## Production smoke test

`deploy/scripts/smoke_test.py` (new this phase) — a standalone script, parameterized by `--base-url`, covering the USER/ADMIN/OWNER flows named in the Phase 09 brief (§20) against a running instance: catalog browse → product detail → `GET /cart` (USER); session + dashboard + orders + products + inventory read (ADMIN); dashboard/finance/analytics/admins/audit/settings read (OWNER). **Read-only** — it creates no cart item, order or payment (an earlier version of this sentence claimed it did; corrected 2026-09-19). The write path (checkout → payment → review → confirm → expiry worker) is exercised by `backend/scripts/audit_smoke.py`, which must only ever run against a disposable database. **Dry-run only**: executed against the local disposable stack used throughout this phase (all steps passed — see the Phase 09 report "Tests" section) — never against a real deployed production instance, since none exists.

## Deferred items

- Real VPS provisioning, DNS, and a real domain (OPEN-1 in `docs/06_OPEN_DECISIONS.md` — server region — remains unresolved without a real provisioning decision to make).
- TLS certificate issuance/auto-renewal (Certbot) — requires the domain above.
- `nginx -t` syntax verification and any live Nginx exercise — no Nginx binary in this development environment.
- Actual `systemctl` installation/start of any unit — no systemd service manager available to register against in this environment (units were reviewed, not installed).
- `bot.setWebhook(...)` against Telegram's real API — requires a real HTTPS URL. Nothing in the codebase or `deploy.sh` registers the webhook; do it once after the domain is live: `curl -s "https://api.telegram.org/bot$BOT_TOKEN/setWebhook" -d "url=https://$DOMAIN/telegram/webhook" -d "secret_token=$TELEGRAM_WEBHOOK_SECRET" -d drop_pending_updates=true` (run with the variables sourced from `/etc/comfort/backend.env`, never pasted). `scripts/dev.sh` does the same for the dev tunnel.
- Off-server backup copy (`rclone`/Cloudflare R2) — no remote configured yet.
- WAL archiving / PITR (§17.3 Layer 2) and manual pre-risk snapshots (Layer 3).
- ~~`comfort-reservation-expiry`, `comfort-receipt-purge` scheduling~~ — **resolved in the final hardening pass.** Both workers' logic exists (`comfort-receipt-purge` was implemented during the Phase 08 verification pass, after this item was first written), both now have a process entrypoint and a systemd service+timer, and `bootstrap.sh` installs and enables them. Verified by execution locally as real subprocesses (`tests/integration/test_worker_entrypoints.py`, 10 tests) and statically as unit files (`tests/unit/test_worker_scheduling_units.py`, 10 tests, plus `systemd-analyze verify` and `systemd-analyze calendar`). **Not verified:** actual systemd-driven execution on a timer — that requires installing units as root on a real host, which the verification environment cannot do.
- `comfort-broadcast`, `comfort-idempotency-cleanup` — still unscheduled, and correctly so: neither has business logic anywhere in the codebase (verified by search), and `comfort-broadcast` depends on Phase 10. Scheduling infrastructure for logic that does not exist was not fabricated.
- External uptime monitoring (healthchecks.io or equivalent) — requires a real deployed URL to ping.
- Full §17.7 go-live checklist and §19/§21 real-server verification.

## Known limitations

Everything in this document is either (a) code changes verified locally via the existing test suite plus manual local runs, or (b) infrastructure-as-config that was written, reviewed, and syntax/logic-checked where locally possible, but has never touched a real server. Treat every artifact under `deploy/` as a reviewed first draft to be validated against the actual target VPS, not as proof deployment will succeed unmodified.


## Unit installation (added in the final hardening pass)

Every unit in `deploy/systemd/` used to be a file that nothing ever installed: neither `bootstrap.sh` nor `deploy.sh` copied them into `/etc/systemd/system`, ran `daemon-reload`, or enabled anything, and this document contained no `systemctl enable` step either. Following the documented procedure end to end therefore left `comfort-api` stopped and every timer unscheduled — the units were correct and inert.

`deploy/scripts/bootstrap.sh` step `[5/5]` now does this, as part of one-time host provisioning (not per-release `deploy.sh`):

```bash
install -m 0644 deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable comfort-api.service          # enabled, NOT started
systemctl enable --now comfort-*.timer        # timers start immediately
```

`comfort-api` is enabled but deliberately never started by the script: `/etc/comfort/backend.env` is operator-owned and `bootstrap.sh` never creates it, so starting the service before that file exists would only crash-loop. Start it by hand once the environment file is in place.

**Verification status:** the units pass `systemd-analyze verify` (the only complaint being that `/opt/comfort/...` does not exist off-server) and their `OnCalendar` expressions were parsed by `systemd-analyze calendar`. The install step itself is **not executed** in the verification environment — it needs root and a real systemd instance. `tests/unit/test_worker_scheduling_units.py` asserts the step is present and covers every unit.
