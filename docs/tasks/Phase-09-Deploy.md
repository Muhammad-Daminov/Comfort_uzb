# Phase 09 — Production Deploy

**Owner:** devops
**Status:** PASS WITH LIMITATIONS — infrastructure code/config prepared and locally verified (see "Infrastructure pass" below); no real VPS/domain exists, so nothing in §17.7's go-live checklist is actually live. Not started → in-progress-but-blocked-on-external-prerequisites is the accurate state, not "not started."
**Last updated:** 2026-08-18
**Dependencies:** [Phase-08-Security.md](Phase-08-Security.md)

## Infrastructure pass (2026-08-18)

Everything in this section was written and, where the local environment allowed, actually executed and verified — never claimed without running it. Full detail: [`../09_DEPLOYMENT.md`](../09_DEPLOYMENT.md).

**Bug found and fixed**: `app/main.py` never wired the bot in — `bot/main.py`'s pieces (`build_dispatcher`, `build_webhook_router`, `configure_bot`, `run_notification_poller_forever`) existed since Phase 04 but nothing called them, so the webhook route did not exist on the running app and the notification poller never ran outside tests. Fixed this phase; verified with a real local `uvicorn` run (deliberately-invalid bot token → `configure_bot` failure logged, not fatal → app served `/health`, `/catalog/products`, and the webhook secret-check correctly).

**New this phase**: `app/health.py` (`/health/live`, `/health/ready`), `app/cors.py` (env-driven allowlist, empty by default), `.env.example`, `deploy/` (Nginx template with ADR-13 signed-URL verification and §12.4 rate-limit zones, systemd units for one application process + `comfort-backup` + `comfort-health`, `backup.sh`/`restore.sh`/`deploy.sh`/`health.sh`/`smoke_test.py`).

**Genuinely executed, not just written**: `backup.sh` and `restore.sh` run against a local disposable PostgreSQL cluster — a real dump was taken and successfully restored into a separate verification database, row counts confirmed. `smoke_test.py` run against a local `uvicorn` instance — all 15 USER/ADMIN/OWNER checks passed.

**Not done — genuinely blocked on external prerequisites this session cannot provide:** no VPS, no domain, no DNS, no TLS certificate, no live Nginx/systemd install, no real Telegram webhook registration, no off-server backup destination. `docs/06_OPEN_DECISIONS.md` OPEN-1 (server region) remains unresolved — there is no server to measure latency from yet.

## Objective
Provision the Contabo VPS, harden it, deploy the full stack, and pass the §17.7 go-live checklist.

## Prerequisites
- Phase 08 complete — security hardening and the full test matrix pass before production traffic is considered.
- OPEN-1 (server region) resolved — see `06_OPEN_DECISIONS.md`.
- Domain name and Cloudflare DNS available.

## Deliverables
- `docs/09_DEPLOYMENT.md` written (§16–§17 content, split from Master TZ).
- Server Setup Runbook and Deployment & Backup Runbook (the two §25 documents this phase produces).
- Live production stack: Nginx, FastAPI, aiogram bot, PostgreSQL 16, all six workers, backup pipeline, monitoring.
- **Worker scheduling/infra only** — systemd unit + timer + lock (flock/advisory lock) for each of the six workers, wired to the business logic each already has by this point: `comfort-reservation-expiry` (logic shipped in Phase-03), `comfort-broadcast` (logic shipped in Phase-10's P1 rollout — its timer may be added when that logic lands, not necessarily at initial go-live if broadcast isn't live yet), `comfort-receipt-purge`/`comfort-idempotency-cleanup` (logic owned by `security`, shipped early — concurrently with Phase-03, since `security`'s primitives, including receipt-retention and idempotency-key policy, are a Phase-03 prerequisite already; Phase-08 only hardens/tests it), `comfort-backup`/`comfort-health` (logic and infra both owned by `devops`, authored here). Per the Phase 0 review correction: this phase must never be where worker *business logic* is first written — only where it's scheduled and deployed.

## Definition of Done
- [ ] All 16 items in Master TZ §17.7 checked — **not possible without a real VPS/domain**; 0 of 16 can be checked from this environment.
- [x] Backup restore drill completed successfully against a separate target — **done, but against a local disposable database, not a production server** (see "Infrastructure pass" above). The monthly-cadence requirement (§17.3) cannot be scheduled until a real server exists.
- [x] `/health` endpoint exists and reports DB status (`app/health.py`) — does not report disk or worker status (worker status was judged out of scope for a liveness/readiness check; disk status is `comfort-health`'s separate job, not `/health`'s).
- [ ] External uptime monitoring confirmed to alert on a simulated outage — **not done**, requires a real deployed URL to point healthchecks.io (or equivalent) at.
- [ ] All Master TZ §24 Definition-of-Done items pass in production — **not applicable**, nothing is in production.

**Note on this file's own §"Deliverables" worker-scheduling claim above**: it states `comfort-receipt-purge`/`comfort-idempotency-cleanup` "logic owned by security, shipped early." This was checked during the Phase 09 infrastructure pass and found inaccurate — neither worker's business logic exists anywhere in `app/` (verified by search). Only `comfort-reservation-expiry` has real logic to schedule. `comfort-backup` and `comfort-health` (this phase's own responsibility, logic included) are scheduled. `comfort-broadcast` correctly awaits Phase 10. This discrepancy is flagged for `backend-commerce`/`security` to resolve, not silently worked around by inventing the missing logic here (out of this phase's scope).

**Update — full-project local verification pass (2026-08-20).** The note above is now partly stale, and the underlying gap is still open. Verified against the current tree:

- `app/workers/receipt_purge.py` **does** now exist (it was implemented in the Phase 08 verification pass, after the note above was written), alongside `app/workers/reservation_expiry.py`. Both expose a working `run_once(...)`, and both were executed successfully against a live disposable database during this pass.
- Neither worker is scheduled by anything. `deploy/systemd/` contains only `comfort-api`, `comfort-backup{.service,.timer}` and `comfort-health{.service,.timer}` — there is no `comfort-reservation-expiry` or `comfort-receipt-purge` unit or timer, and no call site in `app/` or `bot/` either (`app/main.py`'s lifespan starts only the notification poller). Confirmed by search: outside `app/workers/` and `tests/`, nothing references either module.
- Consequence if deployed as-is: ADR-6's reservation TTL never fires, so stock reserved by abandoned orders is never released and leaks permanently; ADR-9's receipt retention never purges, so receipts are kept past their stated retention window.
- `backend/README.md`'s file map still describes both workers' "systemd wiring is Phase-09, see ../deploy/" — that wiring does not exist. The README has been updated in this pass to say so.

This remains **unfixed on purpose**: writing the two units is small, but it is deployment infrastructure that cannot be verified in this environment (no systemd deployment, no VPS), and inventing unverified units would repeat exactly the kind of "documented as done, never executed" gap this pass exists to find.

## Audit correction (2026-09-19)
The two paragraphs above ("Neither worker is scheduled by anything… no `comfort-reservation-expiry` or `comfort-receipt-purge` unit", "remains unfixed on purpose") are **stale**: `deploy/systemd/` now contains `comfort-reservation-expiry.{service,timer}` and `comfort-receipt-purge.{service,timer}`, `app/workers/_entrypoint.py` is their shared process entrypoint (advisory lock, exit codes), and `bootstrap.sh` enables both timers. `comfort-idempotency-cleanup` (REQ-WRK-004) still has no implementation. The full-system audit report (`docs/11_FULL_SYSTEM_AUDIT_REPORT.md`) lists the deploy-config defects fixed on 2026-09-19 (Nginx location precedence and `http2`, `/var/comfort` group ownership for Nginx, backup/health variables in `.env.example`, `OWNER_TELEGRAM_ID` check in `deploy.sh`) — all config-level, none runtime-verified here (no VPS/Nginx/systemd).
