-- Comfort UZB — PostgreSQL role/grant DDL
--
-- Owner: database agent (docs/05_AGENT_ARCHITECTURE.md, AGENTS/database.md
-- "Postgres role/grant DDL ownership"). `security` defines the
-- least-privilege policy this file implements and reviews it; `devops`
-- does not author or modify this file — it owns only runtime config
-- (pg_hba.conf, postgresql.conf), addressed separately in Phase-09.
--
-- Source: docs/00_MASTER_TZ.md §12.2, copied close to verbatim.
--
-- WHY THIS IS A STANDALONE SCRIPT, NOT AN ALEMBIC MIGRATION:
-- comfort_migrate is the role Alembic connects as for every ordinary
-- migration (per §12.2: "Migration roli — faqat Alembic ishlatadi"). That
-- role has to exist *before* Alembic can run anything — including a
-- hypothetical "migration 0000 that creates comfort_migrate" — so role
-- creation can't be bootstrapped through the same connection it's meant
-- to gate. This script is run once, manually, by a Postgres superuser
-- during initial server provisioning (Server Setup Runbook, §25/Phase-09,
-- executed by `devops` but authored by `database`), before the first
-- `alembic upgrade head` ever runs. Passwords are placeholders — real
-- values come from the environment/secrets store at provisioning time,
-- never committed here (§12.1: secrets in .env, not in git).
--
-- Idempotent: safe to re-run against an already-provisioned cluster.
--
-- USAGE (run once, as a Postgres superuser, e.g. the `postgres` OS role):
--   psql -U postgres -d comfort_uzb \
--        -v comfort_app_password="<secret>" \
--        -v comfort_migrate_password="<secret>" \
--        -v comfort_backup_password="<secret>" \
--        -f provision_roles.sql
-- The `:'var'` psql-variable syntax below requires running through psql
-- (not a generic SQL client) with these three variables supplied.
--
-- PASS THE PASSWORD RAW — do NOT wrap it in embedded single quotes. The
-- `quote_literal(:'var')` calls below already add the SQL quoting when
-- they build the CREATE ROLE command text for \gexec. An earlier version
-- of this header told operators to pass `"'<secret>'"`, which quoted the
-- value twice: the role was then created with a password that literally
-- began and ended with an apostrophe, so every later connection using the
-- password the operator actually typed failed with "password
-- authentication failed". Found by running this documented procedure
-- verbatim against a fresh cluster during the full-project verification
-- pass; the SQL below was always correct, only this USAGE block was wrong.

-- Abort on the first error. Without this a forgotten `-v` password made
-- `quote_literal(:'var')` a syntax error, the role was silently not
-- created, every later GRANT failed, and psql still exited 0.
\set ON_ERROR_STOP on

-- NOTE: psql variable interpolation (:'var') does not work inside a
-- dollar-quoted DO $$ ... $$ block — psql's lexer treats the whole block
-- as an opaque token before Postgres ever parses it, so an earlier draft
-- of this script that put `CREATE ROLE ... PASSWORD :'var'` inside
-- `DO $$ BEGIN ... END $$` silently failed with a syntax error at `:`
-- (caught by running this script against a live test cluster during
-- Phase 02 — see docs/tasks/Phase-02-Database.md verification notes).
-- \gexec avoids the problem: the SELECT below is plain SQL (variables
-- interpolate normally), and \gexec then executes whatever it returned.
SELECT 'CREATE ROLE comfort_app LOGIN PASSWORD ' || quote_literal(:'comfort_app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'comfort_app') \gexec

SELECT 'CREATE ROLE comfort_migrate LOGIN PASSWORD ' || quote_literal(:'comfort_migrate_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'comfort_migrate') \gexec

SELECT 'CREATE ROLE comfort_backup LOGIN PASSWORD ' || quote_literal(:'comfort_backup_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'comfort_backup') \gexec

-- Application role: least privilege. No DELETE (soft delete is used
-- everywhere, §5.4/§21), no DDL, never connects as superuser/DB owner.
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO comfort_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO comfort_app;
REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM comfort_app;

-- audit_logs: even narrower than the app-wide grant above — insert/read
-- only, no UPDATE either (the append-only trigger in migration 0011_security
-- already blocks UPDATE/DELETE at the table level; this REVOKE is the
-- role-level belt to that trigger's suspenders, per §12.2's own example).
--
-- THE AUTHORITATIVE NARROWING LIVES IN MIGRATION 0011_SECURITY, NOT HERE.
-- FOUND BY LIVE VERIFICATION (Phase 02 acceptance audit): this script is
-- documented to run BEFORE the first `alembic upgrade head`, meaning
-- `audit_logs` does not exist yet when these two statements first run.
-- psql does not abort the script on a statement error by default, so they
-- used to fail silently with "relation audit_logs does not exist" and
-- never re-apply — leaving comfort_app with UPDATE on audit_logs via the
-- blanket ALTER DEFAULT PRIVILEGES grant below, contradicting §12.2.
-- Fixed at the root: migration 0011_security's upgrade() now applies this
-- exact REVOKE/GRANT itself, immediately after creating the table (guarded
-- to no-op if comfort_app doesn't exist yet, e.g. local dev without role
-- provisioning) — so the correct privilege state holds regardless of
-- whether this script ran before or after migrations, or was never told
-- to expect audit_logs. The block below is now a defensive, idempotent
-- *reapplication* for the case this script is re-run later (e.g. to
-- rotate a password) with audit_logs already present — it is guarded so
-- it no longer errors when the table doesn't exist yet.
SELECT 'REVOKE UPDATE, DELETE ON audit_logs FROM comfort_app;'
WHERE EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'audit_logs'
) \gexec

SELECT 'GRANT INSERT, SELECT ON audit_logs TO comfort_app;'
WHERE EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'audit_logs'
) \gexec

-- Migration role: full DDL rights, used only by Alembic, never by the
-- running application.
GRANT ALL ON SCHEMA public TO comfort_migrate;

-- Database-level CREATE, required for CREATE EXTENSION (migration
-- 0006_search's `CREATE EXTENSION IF NOT EXISTS pg_trgm;`, and any future
-- migration that installs a trusted extension). Schema-level `GRANT ALL
-- ON SCHEMA public` above is NOT sufficient for this — Postgres requires
-- database-level CREATE to install even a "trusted" extension (pg_trgm
-- has been trusted since PG13), independent of schema privileges.
--
-- FOUND BY LIVE VERIFICATION (Phase 02 acceptance audit): running
-- `alembic upgrade head` as `comfort_migrate` against a database
-- provisioned by an earlier version of this script (without this grant)
-- failed at migration 0006 with "permission denied to create extension
-- pg_trgm — Must have CREATE privilege on current database", and because
-- env.py wraps the whole upgrade run in one transaction, the failure
-- rolled back migrations 0001-0005 too. This grant is what was missing.
--
-- Uses current_database() rather than a hardcoded name — this script is
-- always invoked already connected to the target database (see USAGE
-- above: `psql ... -d comfort_uzb ... -f provision_roles.sql`), so
-- current_database() is exactly the database being provisioned, on any
-- environment (dev, staging, prod), without hardcoding a name here.
SELECT format('GRANT CREATE ON DATABASE %I TO comfort_migrate;', current_database()) \gexec

-- Backup role: read-only, used only by comfort-backup (§17.3, pg_dump).
GRANT SELECT ON ALL TABLES IN SCHEMA public TO comfort_backup;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO comfort_backup;

-- Ensure future tables created by comfort_migrate (i.e. every future
-- Alembic migration) automatically pick up these same grants without a
-- manual re-run of this script after each new migration.
ALTER DEFAULT PRIVILEGES FOR ROLE comfort_migrate IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO comfort_app;
ALTER DEFAULT PRIVILEGES FOR ROLE comfort_migrate IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO comfort_app;
ALTER DEFAULT PRIVILEGES FOR ROLE comfort_migrate IN SCHEMA public
    GRANT SELECT ON TABLES TO comfort_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE comfort_migrate IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO comfort_backup;

-- No RLS. Per §12.2's explicit rationale: RLS was needed on Supabase
-- because Postgres was reachable from the internet via Supabase's REST
-- API; on Contabo, Postgres listens on localhost only (devops-owned
-- postgresql.conf) and only the backend ever connects, so least-privilege
-- roles are sufficient and RLS would be redundant work. This decision is
-- preserved deliberately — do not reintroduce RLS without a new ADR
-- superseding this rationale (see docs/adr/, ADR-001's context and
-- AGENTS/security.md).

