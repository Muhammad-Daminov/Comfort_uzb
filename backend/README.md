# backend/ — Database (Phase 02) + API (Phase 03) + Bot (Phase 04) + Admin (Phase 06) + Owner (Phase 07) + Hardening/Security/Testing docs (Phase 08) + Production infrastructure (Phase 09)

Full rationale and decision log: [`../docs/03_DB_SCHEMA_PLAN.md`](../docs/03_DB_SCHEMA_PLAN.md) (database), [`../docs/04_API_SPEC.md`](../docs/04_API_SPEC.md) (API), [`../docs/05_BOT_SPEC.md`](../docs/05_BOT_SPEC.md) (bot), [`../docs/07_ADMIN_PANEL_SPEC.md`](../docs/07_ADMIN_PANEL_SPEC.md) (admin + owner screens, share the `miniapp/` frontend with USER screens), [`../docs/08_SECURITY.md`](../docs/08_SECURITY.md) (full security posture, per-claim verified-by labeling), [`../docs/09_DEPLOYMENT.md`](../docs/09_DEPLOYMENT.md) (deployment architecture/procedure — no real VPS exists yet, see that doc's own caveats), [`../docs/10_TESTING.md`](../docs/10_TESTING.md) (full test architecture), [`../docs/tasks/Phase-08-Security.md`](../docs/tasks/Phase-08-Security.md) (hardening pass + Phase 08-FINAL completion pass). This file is just the "how do I run it" quick start.

```
alembic/                              16 migrations — the schema, in dependency order
db/provision_roles.sql                comfort_app / comfort_migrate / comfort_backup DDL (run once, by a superuser)
app/                                   FastAPI application — Router/Service/Repository per domain (ADR-015: raw asyncpg)
  main.py                             app + router mounting + connection-pool lifespan + bot wiring (Phase 09) + observability/CORS
  observability.py                    structured logging, request-id correlation, global exception handler (OPEN-2, Phase 08-FINAL)
  health.py                           /health/live, /health/ready (Phase 09)
  cors.py                             env-driven CORS allowlist, empty (no CORS) by default (Phase 09)
  security/                           initData verification, sessions, permissions, idempotency, audit, signed URLs, uploads (products + receipts)
  domains/                            identity, catalog (+admin_router.py: product/variant/brand/color/image/compatibility CRUD), vehicle, pricing, commerce (cart — soft-delete, Phase 08/orders/reservations/inventory), payments, owner (dashboard/finance/analytics/admin-management/audit/settings — read-heavy, no owned tables per AGENTS/backend-core.md)
  workers/reservation_expiry.py       comfort-reservation-expiry business logic (systemd wiring is Phase-09, see ../deploy/)
  workers/receipt_purge.py            comfort-receipt-purge business logic (ADR-9; systemd wiring is Phase-09, same split as reservation_expiry.py)
bot/                                   aiogram bot (Phase 04) — thin delivery channel, zero business logic (reuses app.domains.identity.service)
  main.py                             Bot/Dispatcher wiring, webhook route — now actually mounted into app/main.py's lifespan (Phase 09; was built in Phase 04 but never wired in until this phase), notification poll loop
  handlers/start.py                   /start, phone capture, blocked-user re-activation (ADR-12)
  notifications/poller.py             outbox poll loop (ADR-016 — resolves OPEN-6)
  locales/uz.py                       Uzbek message copy
tests/unit/                           71 pytest tests, no DB — pure functions, mocked bot/DB handler logic, .env.example secret guard, systemd worker-scheduling assertions
tests/integration/                    168 pytest tests, live PostgreSQL 16, exercised as comfort_app (includes the consolidated security suite, performance smoke test, /health tests, and comfort-receipt-purge worker tests)
tests/db/test_schema.py               34 pytest tests, run against a real PostgreSQL 16 instance (0 skipped when TEST_DATABASE_URL_AS_APP/_AS_BACKUP are set)
tests/db/test_migration_role_e2e.py   genuinely runs the bootstrap AS comfort_migrate against a fresh disposable DB
tests/db/test_provision_roles_quoting.py  3 tests pinning provision_roles.sql's password quoting (the documented bootstrap must stay executable verbatim)
.env.example                          every env var, secrets vs public config split, safe placeholders only (Phase 09)
requirements.txt
```

`../deploy/` (repo root, alongside `backend/` and `miniapp/`): Nginx config template + rate-limit zones + ADR-13 signed-URL verification, systemd units for the one application process plus `comfort-backup`/`comfort-health`, and `backup.sh`/`restore.sh`/`deploy.sh`/`health.sh`/`smoke_test.py` — see `docs/09_DEPLOYMENT.md` for what's been verified locally versus what still needs a real VPS.

**Known outstanding issues, all found and fixed in the pass that found them, none found beyond these:** the cart-item DELETE-vs-`comfort_app` bug (found Phase 06, fixed Phase 08 hardening pass); `GET /catalog/products`'s default-sort crash (found and fixed in the Phase 08-FINAL completion pass); the bot/notification-poller never actually being wired into the running app (found and fixed in Phase 09 — `bot/main.py`'s pieces existed since Phase 04, but nothing called them before this phase); `tests/db/test_schema.py::TestAuditAppendOnly`'s two mutation-rejection tests asserted the wrong exception type — they run as `comfort_app`, which has no UPDATE/DELETE grant on `audit_logs` at all (§12.2), so Postgres denies at the privilege layer before the `prevent_audit_mutation()` trigger is ever reached; the tests asserted only the trigger's exception type and had never actually been executed with real `comfort_app` credentials until this pass (found and fixed in the Phase 08 verification pass — both layers of the append-only defense are accepted now, whichever fires first); `comfort-receipt-purge` (ADR-9) had no implementation anywhere despite being named in ADR-9/Master TZ — found and implemented in the Phase 08 verification pass (`app/workers/receipt_purge.py`); Telegram `BackButton`/`MainButton.onClick` accumulates listeners across screens instead of replacing them, and no screen or router code ever called the returned disposer between navigations — found and fixed in the Phase 08 verification pass (`miniapp/src/telegram.ts` now tracks and clears the previously-registered handler itself). Product-image file purge remains genuinely unimplemented (no ADR defines its retention policy, unlike receipts) — deferred, not silently missing, see `docs/tasks/Phase-08-Security.md`.

**Found by the full-project local verification pass (2026-08-20), fixed in that pass:** `POST /cart/items` with an unknown `variant_id`, and `POST`/`PATCH /admin/products` with an unknown `brand_id`, let `asyncpg.exceptions.ForeignKeyViolationError` escape the Router and became HTTP **500** instead of 422 — the sibling variant routes in the same `admin_router.py` already carried exactly the guard that was missing (regression tests: `tests/integration/test_fk_violation_is_422.py`). `db/provision_roles.sql`'s USAGE header (and the matching block in this file) told operators to pass each password wrapped in embedded single quotes, which `quote_literal()` then quoted a *second* time — roles were created with a password containing literal apostrophes, so the documented production bootstrap could never authenticate afterwards; the SQL was always correct, only the documented usage was wrong. `tests/db/test_migration_role_e2e.py` resets the three `comfort_*` role passwords cluster-wide via `ALTER ROLE` (hardcoded `e2e_test_*_pw` constants) before running `provision_roles.sql`, which both invalidates any other environment sharing the cluster and means the script's own password path is never exercised (the first is now mitigated by a restore fixture; the second is covered by `tests/db/test_provision_roles_quoting.py`). **Resolved in the final hardening pass:** the worker-scheduling gap is closed. Both workers now have a process entrypoint (`python -m app.workers.<name>`, shared wrapper in `app/workers/_entrypoint.py`: advisory-lock so runs cannot overlap, structured log line per outcome, non-zero exit on failure), a systemd service+timer in `../deploy/systemd/` (`comfort-reservation-expiry` every 5 min per §15, `comfort-receipt-purge` daily 03:30 after the backup window per ADR-9), and `../deploy/scripts/bootstrap.sh` step [5/5] now installs and enables every unit — previously nothing ever copied a unit into `/etc/systemd/system` or enabled it, so even `comfort-api` and the pre-existing timers were inert. Also fixed in the same pass: duplicate brand/color names raised an unhandled `UniqueViolationError` and returned HTTP 500 on four routes (now 409; archived-name reuse still works, since the unique indexes are partial); and the live BotFather token committed in `.env.example` was replaced with a placeholder and is guarded by `tests/unit/test_env_example_has_no_secrets.py`. `tests/db/test_migration_role_e2e.py`'s cluster-wide `ALTER ROLE` password reset is also fixed: it broke `pytest tests/db` as a whole (that module collects first, so `test_schema.py::TestRolePrivileges` then failed to authenticate — each file passed alone, the directory did not). A module-scoped autouse fixture now restores whatever passwords the surrounding environment already supplied via `TEST_DATABASE_URL_AS_APP`/`_AS_BACKUP`/`MIGRATION_DATABASE_URL`; the reset itself is still cluster-wide and documented in that file's docstring. **Found during the 2026-08-27 UI pass, fixed in it:** the catalog *listing*'s primary-image subquery in `app/domains/catalog/repository.py` had no `deleted_at IS NULL` filter (the detail endpoint's did), so an image removed in the admin panel kept appearing in the grid forever — which is what "admin cannot replace a product image" actually was. Reproduced live against the running app (upload -> delete -> still listed) and covered by `tests/integration/test_catalog_images.py::test_listing_ignores_a_soft_deleted_primary_image` and `::test_listing_falls_back_to_the_next_image_when_the_primary_is_deleted`, both verified to fail without the fix. `GET /cart` now returns a signed `primary_image_url` per line (same ordering and the same `deleted_at` filter as the listing; ADR-13 signing in the router, raw `storage_path` never leaves the server) — `tests/integration/test_cart_item_image.py`. `scripts/seed_demo.py` no longer fabricates flat-colour rectangles as product photos: it wrote `product_images` rows that made the catalog look like it had images when it had none. Missing images are now shown honestly by `miniapp/src/components/product-media.ts`. **Still not verifiable here:** actual systemd-driven execution, Nginx signed-URL verification, a public-HTTPS Telegram webhook round-trip, and browser/on-device testing — all need root or infrastructure this environment does not have.

## Quick start (local dev — NOT the production role model)

This is the fast path for iterating on schema/migration content. It runs migrations as **your own Postgres user**, not `comfort_migrate` — fine for day-to-day schema work, but it does **not** exercise the least-privilege role boundaries §12.2 requires in production, and it would **not** have caught either of the two real bugs the Phase 02 acceptance audit found (both were bugs in `comfort_migrate`'s actual privileges — see `../docs/03_DB_SCHEMA_PLAN.md` "Roles & grants"). If you're touching `db/provision_roles.sql`, a migration's DDL, or anything privilege-related, use "Migration-role verification" below instead of, not in addition to, assuming this quick start proves it works.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql+psycopg://<your-dev-user>@/<db>?host=<socket_dir_or_host>&port=<port>"
export OWNER_TELEGRAM_ID="<your own Telegram numeric ID for local dev>"
alembic upgrade head

export TEST_DATABASE_URL="$DATABASE_URL"
python3 -m pytest tests/db/test_schema.py -v
```

## Migration-role verification (the actual production bootstrap procedure)

This is what genuinely proves the documented production flow — `provision_roles.sql` then `alembic upgrade head` as `comfort_migrate` — works, because it actually does that, against a throwaway database it creates and drops itself:

```bash
# Requires a role with CREATEDB privilege (used only to create/drop the
# throwaway test database — this is NOT comfort_migrate, and does not
# need to be a full superuser, just CREATEDB).
export SUPERUSER_DATABASE_URL="postgresql://<a-createdb-role>@/postgres?host=<socket_dir>&port=<port>"
python3 -m pytest tests/db/test_migration_role_e2e.py -v
```

To run the same bootstrap manually instead of through the test:

```bash
# Pass each password RAW — no embedded single quotes. provision_roles.sql
# adds the SQL quoting itself; wrapping the value in quotes here creates
# the role with a password that literally contains apostrophes, and every
# later connection then fails with "password authentication failed".
psql <connection-args-as-a-superuser> -d <fresh-db> \
     -v comfort_app_password="<pw>" \
     -v comfort_migrate_password="<pw>" \
     -v comfort_backup_password="<pw>" \
     -f db/provision_roles.sql

export DATABASE_URL="postgresql+psycopg://comfort_migrate:<pw>@/<fresh-db>?host=<socket_dir>&port=<port>"
export OWNER_TELEGRAM_ID="<any bigint for local dev>"
alembic upgrade head   # this line must succeed connected AS comfort_migrate, not your own user

export TEST_DATABASE_URL_AS_APP="postgresql://comfort_app:<pw>@/<fresh-db>?host=<socket_dir>&port=<port>"
export TEST_DATABASE_URL_AS_BACKUP="postgresql://comfort_backup:<pw>@/<fresh-db>?host=<socket_dir>&port=<port>"
python3 -m pytest tests/db/test_schema.py::TestRolePrivileges -v
```

Never point `DATABASE_URL` at a shared/production database from a dev machine — dev and prod never share a DB (REQ-OPS-008).

## Running the API + bot (one process — ADR-1, wired together in Phase 09)

There is one process, not two — `app/main.py`'s `lifespan` constructs the bot, mounts its webhook route, and starts the notification poller as a background task, all inside the same FastAPI app the Mini App/admin/owner API uses. See `docs/09_DEPLOYMENT.md` "Architecture" for why this is one systemd unit (`comfort-api`), not the separate `comfort-api`/`comfort-bot` pair the Master TZ's own napkin sketch names.

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://comfort_app:<pw>@/<db>?host=<socket_dir>&port=<port>"   # asyncpg DSN — the app connects as comfort_app, never a superuser
export BOT_TOKEN="<telegram bot token>"                # ADR-2 initData verification + bot API calls
export SESSION_SECRET="<random secret>"                # HMAC-signs POST /auth/session tokens
export SIGNING_SECRET="<random secret>"                # ADR-13 signed-URL secret — must match Nginx's secure_link_md5
export UPLOADS_ROOT="/var/comfort/uploads"             # ADR-14 layout; a scratch dir is fine for local dev
export MINIAPP_URL="https://<your-domain>/"            # Menu Button target (ADR-1); any HTTPS URL works for local dev
export TELEGRAM_WEBHOOK_SECRET="<random secret>"        # validated against X-Telegram-Bot-Api-Secret-Token
uvicorn app.main:app --reload
```

If `BOT_TOKEN` doesn't correspond to a real bot (e.g. local dev without a live Telegram bot), the app still starts and serves HTTP traffic normally — `configure_bot`'s one-time Menu Button call is wrapped so a Telegram API failure at startup is logged, not fatal (`app/main.py::lifespan`). `bot/main.py` still exposes `build_dispatcher`/`build_webhook_router`/`configure_bot`/`run_notification_poller_forever` as importable pieces (e.g. for the unit tests in `tests/unit/test_bot_webhook.py`), but production/local-dev running goes through `app/main.py` only — there is no separate bot entrypoint to run.

## Tests

See [`../docs/10_TESTING.md`](../docs/10_TESTING.md) for the full test architecture (what each suite proves, environment requirements, the §12.6 security-case-to-test mapping). Quick commands:

```bash
python3 -m pytest tests/unit -v          # 59 tests, no DB, pure functions + mocked bot handler/poller logic

# Live-Postgres integration tests — connect as comfort_app (the real
# production role), plus SUPERUSER_DATABASE_URL for test-data cleanup only
# (comfort_app has no DELETE/TRUNCATE grant by design, §12.2).
export TEST_DATABASE_URL="postgresql://comfort_app:<pw>@/<db>?host=<socket_dir>&port=<port>"
export SUPERUSER_DATABASE_URL="postgresql://<a-superuser>@/<db>?host=<socket_dir>&port=<port>"
python3 -m pytest tests/integration -v   # 168 tests: checkout re-validation, parallel-confirm,
                                          # parallel-last-unit-purchase, reservation expiry, audit
                                          # transaction participation, payment one-way approval,
                                          # bot identity flows, notification delivery (ADR-016),
                                          # cart soft-delete, IDOR regression, inventory concurrency,
                                          # consolidated security suite, performance smoke, /health (Phase 08/09)
```

## Minimal local development startup (verified end to end)

**Why there is no `.env`:** this application never reads one. `app/config.py`
and `bot/config.py` read `os.environ` only — `python-dotenv` is not a
dependency and `load_dotenv()` is called nowhere. `.env.example` is
*documentation*, not configuration: editing it changes nothing at runtime.
Production gets its environment from systemd (`EnvironmentFile=/etc/comfort/backend.env`,
outside the repository); local development gets it from `backend/.env.local`,
which `scripts/dev.sh` loads into the shell before starting anything.

```bash
cp backend/.env.example backend/.env.local   # then fill in real values
chmod 600 backend/.env.local                 # git-ignored, never committed
bash scripts/dev.sh up
```

`scripts/dev.sh up` starts the whole stack in the order Telegram requires and
prints the URLs to open:

1. **HTTPS tunnel** (`cloudflared`) — Telegram cannot reach `localhost`, and a
   Mini App URL must be HTTPS.
2. **Backend** on `:8000` with `MINIAPP_URL` set to the tunnel, which is what
   makes `configure_bot()` point the bot's Menu Button at this session. The
   script checks the log for `configure_bot failed` and says so loudly —
   otherwise a rejected token is swallowed silently and the bot just looks
   empty.
3. **Mini App** on `:5173` (Vite proxies the API, so both share one origin —
   same model as Nginx in production, no CORS needed).
4. **`setWebhook`** against the tunnel. Nothing in the codebase registers a
   webhook, and without one Telegram delivers no updates at all, so `/start`
   stays silent.

Other commands: `down` (stops everything and removes the webhook), `status`,
`urls`, `seed` (fills the demo catalogue via `backend/scripts/seed_demo.py`).
Override ports with `API_PORT=8010 WEB_PORT=5174 bash scripts/dev.sh up`.

The tunnel URL changes on every start, so re-run `up` rather than reusing an
old URL. The bot token is read from `.env.local` and is never printed to the
terminal or written to a log.

### Running pieces by hand

If you would rather not use the script, export the variables yourself — that
is all the script does:

```bash
set -a; source backend/.env.local; set +a
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
```

> **Local gotcha:** a default Debian/Ubuntu `pg_hba.conf` uses `peer` for
> unix-socket connections, so the socket DSN in `.env.example` will fail
> password auth for `comfort_app`/`comfort_migrate` on a dev box. Use
> `127.0.0.1` (scram) locally. Production uses the socket.

**Not needed locally:** Nginx (signed-URL *verification* is Nginx's job in
production, so `/files/...` URLs are generated but served by a dev-only Vite
middleware instead), systemd, and a public HTTPS host of your own.
