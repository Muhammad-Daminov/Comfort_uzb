# 06 — Open Decisions

**Purpose:** Points where the Master TZ leaves a choice unresolved, or where two of its own passages pull in different directions. Per the Phase 0 brief: do not guess — document, identify affected domains, propose alternatives, wait for approval.
**Owner:** architect
**Last updated:** 2026-08-17
**Dependencies:** [00_MASTER_TZ.md](00_MASTER_TZ.md)

None of these block Phase 0 or Phase-02 (Database) specifically — confirmed by the Phase 0 review. OPEN-3 and OPEN-6 must close before Phase-03/04 implementation work reaches the areas they affect (Repository-layer code, notification delivery). Each entry is flagged with the phase it must be closed by.

---

### OPEN-1 — Server region (EU Hub vs India vs Singapore)
**TZ passage:** §16.1 — "checkout paytida Contabo real latency ko'rsatadi — EU Hub, Hindiston, Singapur uchtasini solishtirib, eng kichigini tanlang" (compare the three at checkout, pick the lowest-latency one).
**Why open:** This requires an empirical measurement at provisioning time; the TZ gives a strong prior (EU Hub, since Uzbekistan traffic usually routes via Europe) but explicitly defers the final call to measurement.
**Affected domain:** devops (INFRASTRUCTURE)
**Alternatives:** (a) EU Hub by default per the TZ's own stated prior, measure post-launch and migrate only if data justifies it; (b) block server provisioning on a manual latency test from Tashkent before purchase.
**Must close by:** Phase-09 (Deploy), before VPS purchase.
**Recommendation:** (a) — avoids blocking the roadmap on a manual step that has a clear default answer already in the TZ.

---

### OPEN-2 — Error tracking: Sentry vs ERROR-log→Telegram
**TZ passage:** §17.6 — "Xatolar: Sentry (bepul tier) yoki ERROR log → Telegram" (Sentry free tier *or* error-log-to-Telegram — "yoki" = "or", not decided).
**Why open:** TZ explicitly offers two options without picking one.
**Affected domain:** devops, security (both consume error visibility)
**Alternatives:** (a) Sentry free tier — richer stack traces/grouping, external dependency, another account to secure; (b) ERROR-log → Telegram via `comfort-health`-style worker — zero new dependency, reuses the bot channel already built for disk alerts (§11.4), coarser signal.
**Must close by:** Phase-09 (Deploy) / Phase-08 (Security) — needed before go-live checklist item "Xatolar" tracking is checked off.
**Recommendation:** (b) for MVP — reuses infrastructure already required by REQ-WRK-006, no new third-party account; revisit Sentry post-MVP if error volume justifies it.

---

### OPEN-3 — asyncpg direct vs SQLAlchemy Core — **CLOSED (Phase-03)**
**TZ passage:** §13.2 — "asyncpg (SQLAlchemy Core ixtiyoriy)" (asyncpg, SQLAlchemy Core optional).
**Why open:** TZ names asyncpg as required and SQLAlchemy Core as an explicitly optional layer on top, without a firm call either way.
**Affected domain:** database, backend-core, backend-commerce, backend-engagement (whichever pattern is picked, all Repository-layer code follows it)
**Alternatives:** (a) raw asyncpg + hand-written SQL in the Repository layer — matches the "Unix socket, minimal overhead" performance framing of ADR-1; (b) SQLAlchemy Core over asyncpg — more structured query building, easier to keep ~30 tables' worth of repositories consistent.
**Must close by:** Phase-03 (Backend) — before the first Repository-layer code is written, since it's a repo-wide convention, not a per-feature choice. **Corrected per Phase 0 review:** this was previously (incorrectly) listed as a Phase-02 blocker; Phase-02 is pure schema/DDL/migrations/constraints/indexes/roles and does not depend on this choice — only the Repository-layer code written in Phase-03 does.
**Resolution:** (a) raw asyncpg. Formalized in [ADR-015](adr/ADR-015-repository-data-access.md) at the start of Phase-03, before any Repository-layer code was written. Binding on all domains going forward.

---

### OPEN-4 — Refund states appear in the P0 lifecycle diagram but refund itself is P3 — **CLOSED (v2 rebuild, 2026-09-29)**
**TZ passage:** §8.1 shows `CONFIRMED ─▶ REFUND_PENDING ─▶ REFUNDED (v2.0)` directly beneath the main lifecycle diagram, but §2 places "Refund lifecycle" in P3/v2.0 scope.
**Why open:** Not a contradiction in intent (the `(v2.0)` annotation makes the phasing clear) but worth flagging so no agent implements `REFUND_PENDING`/`REFUNDED` transitions or UI in the P0 order state machine by mistake.
**Affected domain:** backend-commerce
**Original resolution (no approval needed — this is a scoping clarification, not a conflict):** P0's transition table (REQ-COM-003) includes only `CREATED, AWAITING_PAYMENT, PAYMENT_SUBMITTED, UNDER_REVIEW, CONFIRMED, REJECTED, CANCELLED, EXPIRED`. `REFUND_PENDING`/`REFUNDED` are added to the transition table only when P3 is scheduled.
**Closed by:** the v2 rebuild brief explicitly moved refund/cancellation into scope now. `docs/adr/ADR-017-post-confirmation-cancellation-refund.md` implements it — but *not* as `REFUND_PENDING`/`REFUNDED` values on `orders.status` (that part of the original resolution still holds). Refund is instead a fully independent `refunds` table/entity, never an `orders.status` value; `orders.status` only gains `CONFIRMED -> CANCELLED` (reachable solely via the new cancellation-request + admin-decision path). See ADR-017 and `docs/13_V2_REBUILD_AUDIT.md` §4.

---

### OPEN-5 — Worker business logic vs worker infrastructure ownership
**TZ passage:** §15 lists 6 workers whose *logic* spans multiple domains (e.g. `comfort-reservation-expiry` is Commerce/Inventory logic, `comfort-broadcast` is Communication logic) but whose *infrastructure* (systemd unit, timer, locking) is one consistent pattern.
**Why open:** Not a TZ ambiguity but an agent-boundary decision this bootstrap has to make explicitly so it isn't guessed differently per worker later.
**Affected domain:** devops, backend-commerce, backend-engagement
**Resolution (architect decision, stated here for visibility):** `devops` owns the systemd/timer/locking scaffolding and the two purely-infra workers (`comfort-backup`, `comfort-health`). The domain agent owns the worker's business logic and calls it through the same Service layer it uses elsewhere: `backend-commerce` owns `comfort-reservation-expiry`'s logic, `security` owns `comfort-receipt-purge` and `comfort-idempotency-cleanup` (both are retention/security policy), `backend-engagement` owns `comfort-broadcast`'s logic. See `AGENTS/devops.md` and the relevant domain agent files for the split. Sequencing corrected per Phase 0 review: this logic ships with its owning domain's phase (`docs/tasks/Phase-03-Backend.md`, `Phase-10-Optimization.md`), not deferred to `Phase-09-Deploy.md`, which now only wires the already-built logic into systemd.

---

### OPEN-6 — Notification delivery trigger mechanism (sync call vs. async event) — **CLOSED (Phase-04)**
**TZ passage:** §10 ("Notification — ikki kanal: Telegram xabari + notifications jadvali") and ADR-12 specify *what* the dual-channel notification design must do, but not *how* the Telegram-send half gets triggered once `backend-commerce`/`backend-engagement` decide a notification is needed.
**Why open:** Not found during initial Phase 0 drafting — added during the Phase 0 review. `AGENTS/bot.md` lists `backend-engagement` as a dependency, and `AGENTS/backend-engagement.md` lists `bot` as a dependency, with neither file specifying which one calls which. Read literally, that's a mutual dependency: if implemented naively as direct two-way function calls (bot calling into backend-engagement's write path, and backend-engagement calling directly into bot's send function), it becomes a real circular code dependency that would need an awkward refactor to unwind later.
**Affected domain:** `bot`, `backend-engagement` (also relevant to `backend-commerce`, whose order/payment events are the other source of notifications)
**Alternatives:** (a) **Synchronous/direct invocation** — the Service layer that decides a notification is needed calls a `bot`-owned send function directly, in the same request; simplest to implement, but couples `backend-*` request latency to Telegram API latency/availability, and is the design most likely to produce the circular-dependency problem above if not disciplined about direction (only `backend-*` → `bot`, never the reverse). (b) **Asynchronous/event-queue delivery** — `backend-commerce`/`backend-engagement` only ever write a row (e.g. to `notifications`, or a dedicated outbox), and `bot` (or a small worker it owns) polls/consumes it independently; no direct call in either direction, so no circularity, at the cost of a small delivery delay and one more moving part.
**Must close by:** Before Phase-03/04 implementation reaches notification delivery integration — **non-blocking for Phase-02** (schema for `notifications` is the same either way; this only affects the call/trigger mechanism, not the table shape).
**Resolution:** (b) asynchronous/event-queue. Formalized in [ADR-016](adr/ADR-016-notification-delivery.md) at the start of Phase-04, before any bot-side notification-delivery code was written: `backend-engagement`/`backend-commerce` only ever write a `notifications` row; `bot` owns an in-process poll loop that reads unsent rows (`telegram_sent_at IS NULL`, a new nullable column added by migration `0013_notification_delivery`) and sends them, one direction only. No circular call in either direction.
**Interim documentation state (now resolved):** `AGENTS/bot.md` and `AGENTS/backend-engagement.md`'s mutual "Dependencies" listing should now be read through ADR-016 — the row-based, one-directional flow it specifies, not a direct two-way call.

---

### OPEN-7 — Notifications screen tagged P0, but its backend endpoint is P1-owned
**Source passage:** `docs/02_FEATURE_INVENTORY.md` line 111 lists "Notifications" as one of the 13 P0 USER screens (REQ-FE-001/002/003). `AGENTS/backend-engagement.md` lists `GET /notifications` under its own Output Documents, and that agent's whole scope (ENGAGEMENT, COMMUNICATION, MARKETPLACE) is explicitly P1, with the file itself stating "do not build ahead of P0 (REQ-BIZ-005)."
**Why open:** A direct contradiction between two source-of-truth documents, found during Phase-05 planning — not a case where one document is merely silent. The `notifications` table exists (P0, migration `0010_communication_p0`, extended by `0013_notification_delivery` in Phase-04 for the bot's outbox poller), but no domain agent is currently authorized to expose it over HTTP: building the read endpoint now would cross `backend-engagement`'s explicit ownership assignment ahead of its P1 phase; not building it leaves a screen the feature inventory tags P0 unimplemented.
**Affected domain:** `frontend` (Phase-05, blocked), `backend-engagement` (P1, owns the endpoint), `backend-core`/`architect` (whoever ultimately resolves the ownership question)
**Alternatives:** (a) Move the Notifications *screen* to Phase-05's deferred list and treat the feature-inventory P0 tag as the artifact needing correction (most likely explanation: the screen inventory was drafted before the Communication/Engagement domain split was finalized and never reconciled); (b) reassign `GET /notifications` to `backend-core` (or `database`/no owning agent) as a P0 read-only exception so the screen can ship on schedule, leaving `backend-engagement` only the P1 write-side (favorites/chat/sell/broadcast) and any future write-side notification types.
**Must close by:** Before the Notifications screen is built — currently blocking, deferred rather than resolved.
**Recommendation:** (a) for now — the screen's absence doesn't block any other P0 USER flow (checkout/payment/order-status are all reachable without it), whereas (b) would require deciding, without architect input, whether a "P0 exception" inside an otherwise-P1 domain sets a precedent for the rest of that domain's tables. Phase-05 defers the screen and does not implement `GET /notifications`.

---

### OPEN-8 — Payment review vs. order confirmation: two admin actions for one decision
**Source passage:** §8.1 (`UNDER_REVIEW → CONFIRMED | REJECTED`), §8.2 (explicit admin confirm with `FOR UPDATE`), §8.3 (payment `PENDING | APPROVED | REJECTED`, reviewed by admin).
**Why open:** The TZ defines both a payment review and an order confirm but never states their relationship. The full-system audit (2026-09-19) found that no code path ever set an order to `REJECTED`; this is now done when the admin *rejects the payment* (`payments/service.py::review_payment`), which is the only reading under which the §8.1 diagram is reachable. What remains undecided: (a) whether `confirm_order` must require an `APPROVED` payment (today an admin can confirm an `UNDER_REVIEW` order whose payment is still `PENDING`, leaving `paid_amount = 0` on a `CONFIRMED` order), and (b) whether approving the payment should confirm the order automatically (one tap instead of two). The audit deliberately did not add either rule — both change documented admin behaviour.
**Affected domain:** backend-commerce, frontend (admin order detail / payments screens).
**Alternatives:** (a) require `payments.status = 'APPROVED'` in `confirm_order` (422 otherwise); (b) auto-confirm on approve inside the same transaction (§8.2's lock already exists there); (c) keep two independent actions and document it as intended.
**Must close by:** before go-live (§17.7) — it decides what "CONFIRMED" means for the finance report.
**Recommendation:** (a) — smallest change, keeps §8.2's explicit confirm, and makes `CONFIRMED` imply money was accepted.

---

### OPEN-9 — User cancellation of an `UNDER_REVIEW` order after its payment was approved — **CLOSED (v2 rebuild, 2026-09-29)**
**Source passage:** §8.1 lists `CANCELLED (user yoki admin)` reachable from every pre-terminal state; §8.4 only constrains the reason; refunds are v2.0 (OPEN-4).
**Why open:** `POST /orders/{id}/cancel` accepts `UNDER_REVIEW` even when `paid_amount > 0` (payment approved, order not yet confirmed). The money stays recorded as revenue on a `CANCELLED` order and there is no refund state in P0 to move it to. Found by the audit; not changed, because forbidding it is a business rule the TZ does not state.
**Affected domain:** backend-commerce, owner finance reporting.
**Alternatives:** (a) forbid user cancel once `paid_amount > 0` (admin-only from then on); (b) allow it and exclude `CANCELLED` orders from revenue; (c) pull `REFUND_PENDING` forward from v2.0.
**Must close by:** before go-live.
**Recommendation:** (a).
**Closed by:** option (a), exactly as recommended — implemented in `orders/service.py::cancel_order` (rejects with `OrderHasApprovedPayment` whenever `status == 'CONFIRMED'` or `paid_amount > 0`) and `docs/adr/ADR-017-post-confirmation-cancellation-refund.md`. A paid order routes through `cancellation_requests` + an explicit admin decision (`app/domains/commerce/cancellations/`) instead.
