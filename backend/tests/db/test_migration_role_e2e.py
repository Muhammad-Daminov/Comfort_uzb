"""End-to-end verification of the documented bootstrap procedure, genuinely
executed as `comfort_migrate` — Phase 02 acceptance audit, finding
"missing end-to-end migration-role test."

Every other test in this directory either connects to an already-migrated
database (`test_schema.py`'s `conn`/`autocommit_conn` fixtures) or checks
role privileges against a database someone else already migrated
(`TestRolePrivileges`). None of them actually run `provision_roles.sql`
followed by `alembic upgrade head` *as comfort_migrate* against a database
that starts with nothing — which is exactly the gap that let two real bugs
(missing `CREATE ON DATABASE` for `comfort_migrate`, and the `audit_logs`
REVOKE silently no-op'ing before the table existed) ship undetected. This
file closes that gap by doing the real thing: create a throwaway database,
run the actual `provision_roles.sql` via `psql`, run the actual `alembic
upgrade head` via a subprocess with `DATABASE_URL` pointed at
`comfort_migrate` (not a superuser), then assert on the result.

Requires `SUPERUSER_DATABASE_URL` — a connection string for a role with
CREATEDB privilege, used only to create/drop the throwaway database this
test provisions into. Skipped (not failed) if unset, matching the existing
skip-if-not-configured convention in this test directory. `comfort_app`/
`comfort_migrate`/`comfort_backup` are cluster-global roles; this test
does not drop them between runs (provision_roles.sql's role creation is
already idempotent), only the throwaway database — the roles' passwords
are reset to known test values each run via the same superuser connection,
so the test is self-contained regardless of prior state.

WARNING — this suite mutates CLUSTER-WIDE state. `ALTER ROLE ... PASSWORD`
is not scoped to the throwaway database, so running this file resets the
passwords of `comfort_app`/`comfort_migrate`/`comfort_backup` for every
database on the cluster. Any application or dev environment sharing this
cluster will stop authenticating until its own credentials are re-applied.
Run it against a disposable cluster, or expect to reset those passwords
afterwards. (Observed twice during the full-project verification pass: it
silently invalidated the running API's credentials mid-run.)

A second consequence: because the fixture pre-creates the roles, the
`CREATE ROLE ... PASSWORD` branch of provision_roles.sql is skipped here
and never exercised by this file. That is precisely how the password
double-quoting bug survived — `test_provision_roles_quoting.py` covers
that branch hermetically instead.
"""

import os
import pathlib
import subprocess
import sys
import uuid

import psycopg
import pytest

SUPERUSER_DATABASE_URL = os.environ.get("SUPERUSER_DATABASE_URL")
BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]

TEST_APP_PASSWORD = "e2e_test_app_pw"
TEST_MIGRATE_PASSWORD = "e2e_test_migrate_pw"
TEST_BACKUP_PASSWORD = "e2e_test_backup_pw"

pytestmark = pytest.mark.skipif(
    not SUPERUSER_DATABASE_URL,
    reason=(
        "SUPERUSER_DATABASE_URL not set — this test needs CREATEDB "
        "privilege to provision a genuinely fresh disposable database and "
        "run the documented bootstrap (provision_roles.sql -> alembic "
        "upgrade head AS comfort_migrate) end to end. See "
        "docs/03_DB_SCHEMA_PLAN.md 'Verification strategy'."
    ),
)


def _connect_super(dbname="postgres"):
    # Swap the target database in the superuser DSN without assuming its shape.
    conn = psycopg.connect(SUPERUSER_DATABASE_URL, autocommit=True)
    if dbname != "postgres":
        conn.close()
        base = psycopg.conninfo.conninfo_to_dict(SUPERUSER_DATABASE_URL)
        base["dbname"] = dbname
        conn = psycopg.connect(psycopg.conninfo.make_conninfo(**base), autocommit=True)
    return conn


def _dsn_for(dbname, user, password):
    base = psycopg.conninfo.conninfo_to_dict(SUPERUSER_DATABASE_URL)
    base["dbname"] = dbname
    base["user"] = user
    base["password"] = password
    return psycopg.conninfo.make_conninfo(**base)


def _password_from(*env_vars: str, expected_user: str) -> str | None:
    """Recover a role's real password from whichever DSN the developer/CI
    already supplied, so it can be put back after this suite mutates it."""
    for var in env_vars:
        dsn = os.environ.get(var)
        if not dsn:
            continue
        try:
            parts = psycopg.conninfo.conninfo_to_dict(dsn.replace("postgresql+psycopg://", "postgresql://"))
        except Exception:
            continue
        if parts.get("user") == expected_user and parts.get("password"):
            return parts["password"]
    return None


@pytest.fixture(scope="module", autouse=True)
def restore_cluster_role_passwords():
    """`ALTER ROLE ... PASSWORD` is cluster-wide, not scoped to this suite's
    throwaway database, so the resets below would otherwise leave every other
    environment on the cluster unable to authenticate.

    Concretely: running `pytest tests/db` collected this module before
    `test_schema.py`, whose `TestRolePrivileges` cases then failed with
    "password authentication failed for user comfort_app" — each file passed
    alone, the directory as a whole did not. This fixture puts back whatever
    passwords the surrounding environment already told us about.
    """
    originals = {
        "comfort_app": _password_from(
            "TEST_DATABASE_URL_AS_APP", "TEST_DATABASE_URL", "DATABASE_URL",
            expected_user="comfort_app",
        ),
        "comfort_migrate": _password_from(
            "MIGRATION_DATABASE_URL", "DATABASE_URL", expected_user="comfort_migrate",
        ),
        "comfort_backup": _password_from(
            "TEST_DATABASE_URL_AS_BACKUP", expected_user="comfort_backup",
        ),
    }

    yield

    recoverable = {role: pw for role, pw in originals.items() if pw}
    if not recoverable:
        return
    with _connect_super() as super_conn, super_conn.cursor() as cur:
        for role, password in recoverable.items():
            cur.execute(
                f"DO $$ BEGIN "
                f"IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "
                f"ALTER ROLE {role} WITH PASSWORD %s; "
                f"END IF; END $$;".replace("%s", "'" + password.replace("'", "''") + "'")
            )


@pytest.fixture
def fresh_db():
    db_name = f"comfort_e2e_{uuid.uuid4().hex[:10]}"
    with _connect_super() as super_conn, super_conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}";')
        # Deterministic credentials regardless of whether provision_roles.sql
        # creates these roles fresh or finds them already present from an
        # earlier run (its CREATE ROLE is idempotent-by-skip, not
        # idempotent-by-reset) — reset explicitly so this test never depends
        # on what password a previous run happened to use.
        for role, pw in (
            ("comfort_app", TEST_APP_PASSWORD),
            ("comfort_migrate", TEST_MIGRATE_PASSWORD),
            ("comfort_backup", TEST_BACKUP_PASSWORD),
        ):
            cur.execute(
                f"DO $$ BEGIN "
                f"IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "
                f"ALTER ROLE {role} WITH PASSWORD '{pw}'; "
                f"END IF; END $$;"
            )

    try:
        yield db_name
    finally:
        with _connect_super() as super_conn, super_conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE);')


def _run_provision_roles(db_name):
    admin_base = psycopg.conninfo.conninfo_to_dict(SUPERUSER_DATABASE_URL)
    psql_args = ["psql"]
    if admin_base.get("host"):
        psql_args += ["-h", admin_base["host"]]
    if admin_base.get("port"):
        psql_args += ["-p", str(admin_base["port"])]
    if admin_base.get("user"):
        psql_args += ["-U", admin_base["user"]]
    psql_args += [
        "-d", db_name,
        # Raw, WITHOUT embedded single quotes — this is the corrected
        # documented usage. provision_roles.sql's quote_literal() supplies
        # the SQL quoting itself; passing "'pw'" here quotes it twice and
        # creates the role with a password containing literal apostrophes
        # (see test_provision_roles_quoting.py, and the USAGE header in
        # db/provision_roles.sql).
        "-v", f"comfort_app_password={TEST_APP_PASSWORD}",
        "-v", f"comfort_migrate_password={TEST_MIGRATE_PASSWORD}",
        "-v", f"comfort_backup_password={TEST_BACKUP_PASSWORD}",
        "-v", "ON_ERROR_STOP=1",
        "-f", str(BACKEND_DIR / "db" / "provision_roles.sql"),
    ]
    env = dict(os.environ)
    if admin_base.get("password"):
        env["PGPASSWORD"] = admin_base["password"]
    result = subprocess.run(psql_args, cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
    assert result.returncode == 0, (
        f"provision_roles.sql failed (finding #1/#2 regression?):\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    return result


def _run_alembic_upgrade_head_as_migrate(db_name):
    migrate_dsn = _dsn_for(db_name, "comfort_migrate", TEST_MIGRATE_PASSWORD)
    # alembic/env.py expects a SQLAlchemy-style URL, not a libpq DSN string.
    parts = psycopg.conninfo.conninfo_to_dict(migrate_dsn)
    sqla_url = (
        f"postgresql+psycopg://{parts['user']}:{parts['password']}@"
        f"/{parts['dbname']}?host={parts.get('host', '')}&port={parts.get('port', '')}"
    )
    env = dict(os.environ)
    env["DATABASE_URL"] = sqla_url
    env["OWNER_TELEGRAM_ID"] = "999000111"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    return result


class TestMigrationRoleEndToEnd:
    def test_full_bootstrap_as_comfort_migrate(self, fresh_db):
        db_name = fresh_db

        # 1. Provisioning succeeds, in the documented order (roles BEFORE
        #    any migration has run — this is what finding #1/#2 broke).
        _run_provision_roles(db_name)

        # 2. `alembic upgrade head`, genuinely executed as comfort_migrate
        #    (not a superuser, then switched afterward).
        result = _run_alembic_upgrade_head_as_migrate(db_name)
        assert result.returncode == 0, (
            f"alembic upgrade head failed running AS comfort_migrate "
            f"(finding #1 regression — missing CREATE ON DATABASE?):\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        # All 13 migrations must have actually run, not just "some prefix
        # before a silent skip" — check the log output names every one.
        for revision in [
            "0001_identity", "0002_owner_bootstrap", "0003_catalog",
            "0004_vehicle", "0005_pricing", "0006_search", "0007_commerce",
            "0008_inventory", "0009_payments", "0010_communication_p0",
            "0011_security", "0012_seed_search_aliases", "0013_notification_delivery", "0014_compatibility_soft_delete", "0015_store_settings", "0016_cart_items_soft_delete",
        ]:
            assert revision in result.stderr, (
                f"migration {revision} never ran (partial chain?): {result.stderr}"
            )

        with _connect_super(db_name) as conn, conn.cursor() as cur:
            # 3. No partial migration state: alembic_version at head, and
            #    the full 27-table P0 schema present.
            cur.execute("SELECT version_num FROM alembic_version;")
            assert cur.fetchone()[0] == "0016_cart_items_soft_delete"

            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
            )
            # 27 P0 tables + store_settings (Phase 07, migration 0015) + alembic_version's own bookkeeping table.
            assert cur.fetchone()[0] == 29  # 28 + store_settings (migration 0015)

            # 4. Migration 0006 actually created pg_trgm (this is exactly
            #    the statement that used to fail as comfort_migrate).
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm';")
            assert cur.fetchone() is not None, "pg_trgm extension missing"

            # 5. audit_logs exists.
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'audit_logs';"
            )
            assert cur.fetchone() is not None

            # 6. comfort_app has exactly the intended audit_logs privileges
            #    — this is the live assertion that finding #2 is actually
            #    fixed, not just that the script ran without error.
            cur.execute(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE table_name = 'audit_logs' AND grantee = 'comfort_app' "
                "ORDER BY privilege_type;"
            )
            assert [r[0] for r in cur.fetchall()] == ["INSERT", "SELECT"], (
                "comfort_app has unexpected privileges on audit_logs "
                "(finding #2 regression — UPDATE/DELETE should be absent)"
            )

        # 7. Existing role boundaries remain intact, checked by actually
        #    connecting as each role (not just reading pg_catalog).
        app_dsn = _dsn_for(db_name, "comfort_app", TEST_APP_PASSWORD)
        with psycopg.connect(app_dsn, autocommit=True) as c, c.cursor() as cur:
            cur.execute("INSERT INTO roles (name) VALUES ('E2E_TEST_ROLE') RETURNING id;")
            assert cur.fetchone() is not None
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("DELETE FROM roles WHERE name = 'E2E_TEST_ROLE';")
        with psycopg.connect(app_dsn, autocommit=True) as c, c.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("CREATE TABLE hack (id int);")
        with psycopg.connect(app_dsn, autocommit=True) as c, c.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("UPDATE audit_logs SET action = 'x' WHERE false;")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("DELETE FROM audit_logs WHERE false;")

        backup_dsn = _dsn_for(db_name, "comfort_backup", TEST_BACKUP_PASSWORD)
        with psycopg.connect(backup_dsn, autocommit=True) as c, c.cursor() as cur:
            cur.execute("SELECT count(*) FROM roles;")
            assert cur.fetchone()[0] >= 1
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("INSERT INTO roles (name) VALUES ('HACK');")

    def test_migration_lifecycle_as_comfort_migrate(self, fresh_db):
        """upgrade head -> downgrade base -> upgrade head, all as
        comfort_migrate, on a fresh disposable database."""
        db_name = fresh_db
        _run_provision_roles(db_name)

        up1 = _run_alembic_upgrade_head_as_migrate(db_name)
        assert up1.returncode == 0, up1.stderr

        migrate_dsn = _dsn_for(db_name, "comfort_migrate", TEST_MIGRATE_PASSWORD)
        parts = psycopg.conninfo.conninfo_to_dict(migrate_dsn)
        sqla_url = (
            f"postgresql+psycopg://{parts['user']}:{parts['password']}@"
            f"/{parts['dbname']}?host={parts.get('host', '')}&port={parts.get('port', '')}"
        )
        env = dict(os.environ)
        env["DATABASE_URL"] = sqla_url
        env["OWNER_TELEGRAM_ID"] = "999000111"

        down = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "base"],
            cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
        )
        assert down.returncode == 0, down.stderr

        with _connect_super(db_name) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
            )
            assert cur.fetchone()[0] == 1  # only alembic_version left

        up2 = _run_alembic_upgrade_head_as_migrate(db_name)
        assert up2.returncode == 0, up2.stderr

        with _connect_super(db_name) as conn, conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version;")
            assert cur.fetchone()[0] == "0016_cart_items_soft_delete"
            # Re-confirm the audit_logs narrowing survives a second
            # clean provisioning + migration cycle, not just the first.
            cur.execute(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE table_name = 'audit_logs' AND grantee = 'comfort_app' "
                "ORDER BY privilege_type;"
            )
            assert [r[0] for r in cur.fetchall()] == ["INSERT", "SELECT"]
