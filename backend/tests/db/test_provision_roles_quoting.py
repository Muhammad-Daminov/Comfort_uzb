"""Regression: `db/provision_roles.sql` must quote a supplied password
exactly once, and its documented USAGE must be executable verbatim.

THE BUG THIS PINS DOWN
----------------------
The script builds its `CREATE ROLE` statements as text for `\\gexec`:

    SELECT 'CREATE ROLE comfort_app LOGIN PASSWORD '
           || quote_literal(:'comfort_app_password') ...

`quote_literal()` adds the SQL quoting itself, so the password must be
passed RAW. The USAGE header (and backend/README.md) instead told operators
to pass `-v comfort_app_password="'<secret>'"` — quotes included — which
quoted the value a second time. The role was then created with a password
that literally began and ended with an apostrophe, and every later
connection using the password the operator actually typed failed with
"password authentication failed". The documented production bootstrap could
not be followed successfully by anyone.

It survived because `test_migration_role_e2e.py` pre-creates the three
roles with `ALTER ROLE` before running the script, so the script's
`CREATE ROLE ... WHERE NOT EXISTS` always skipped and its password path
never executed there.

WHY THIS TEST IS SHAPED LIKE THIS
---------------------------------
It asserts on the SQL *text the script generates*, obtained by running the
same `quote_literal(:'var')` expression through real `psql` with the real
documented invocation. That exercises the actual quoting behaviour —
psql's `:'var'` interpolation plus Postgres's `quote_literal()`, the exact
pair that produced the bug — without dropping or recreating the real
cluster-global `comfort_*` roles, which would break any other environment
sharing the cluster (the problem documented at the top of
test_migration_role_e2e.py).

Needs only `SUPERUSER_DATABASE_URL`, same convention as the rest of this
directory; skipped, not failed, when unset.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess

import psycopg
import pytest

SUPERUSER_DATABASE_URL = os.environ.get("SUPERUSER_DATABASE_URL")
BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
PROVISION_SQL = BACKEND_DIR / "db" / "provision_roles.sql"

pytestmark = pytest.mark.skipif(
    not SUPERUSER_DATABASE_URL,
    reason="SUPERUSER_DATABASE_URL not set — needed to run psql for the quoting check.",
)

SAMPLE_PASSWORD = "s4mple-P4ss_w0rd"


def _psql_eval(sql: str, variables: dict[str, str]) -> str:
    """Run one SELECT through psql with -v variables, exactly as the real
    bootstrap procedure does, and return the single value it produced."""
    base = psycopg.conninfo.conninfo_to_dict(SUPERUSER_DATABASE_URL)
    args = ["psql", "-tA", "-v", "ON_ERROR_STOP=1"]
    if base.get("host"):
        args += ["-h", base["host"]]
    if base.get("port"):
        args += ["-p", str(base["port"])]
    if base.get("user"):
        args += ["-U", base["user"]]
    args += ["-d", base.get("dbname", "postgres")]
    for key, value in variables.items():
        args += ["-v", f"{key}={value}"]
    # Fed on stdin, not via `-c`: psql only performs `:'var'` interpolation
    # for input that goes through its lexer (a script/stdin), which is how
    # provision_roles.sql itself is run (`-f`). `-c` sends the string
    # straight to the server and the `:` is a syntax error.
    args += ["-f", "-"]

    env = dict(os.environ)
    if base.get("password"):
        env["PGPASSWORD"] = base["password"]

    result = subprocess.run(args, input=sql, capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"psql failed: {result.stderr}"
    return result.stdout.strip()


def _create_role_expression() -> str:
    """The real password-bearing expression from provision_roles.sql, so
    this test can never drift away from the script it is protecting."""
    text = PROVISION_SQL.read_text(encoding="utf-8")
    match = re.search(
        r"(SELECT 'CREATE ROLE comfort_app LOGIN PASSWORD ' \|\| quote_literal\(:'comfort_app_password'\))",
        text,
    )
    assert match, (
        "provision_roles.sql no longer contains the expected "
        "`quote_literal(:'comfort_app_password')` CREATE ROLE expression — "
        "if the script was restructured, update this regression test with it."
    )
    return match.group(1)


def test_documented_usage_quotes_the_password_exactly_once():
    """The documented (raw) invocation must yield a command whose password
    literal is 's4mple-P4ss_w0rd' — one level of quotes, no apostrophes
    inside the value."""
    generated = _psql_eval(
        _create_role_expression(),
        {"comfort_app_password": SAMPLE_PASSWORD},
    )
    assert generated == f"CREATE ROLE comfort_app LOGIN PASSWORD '{SAMPLE_PASSWORD}'", generated
    # The password itself must not contain quote characters.
    inner = generated.split("PASSWORD ", 1)[1]
    assert inner == f"'{SAMPLE_PASSWORD}'"
    assert "''" not in inner, "password was quoted twice — the original bug is back"


def test_old_double_quoted_usage_is_what_broke_and_still_would():
    """Documents the failure mode explicitly: passing the password wrapped
    in quotes (the old documented usage) produces a doubled literal. This is
    a characterisation test — if someone 'fixes' the script by stripping
    quote_literal(), this is the test that will notice."""
    generated = _psql_eval(
        _create_role_expression(),
        {"comfort_app_password": f"'{SAMPLE_PASSWORD}'"},
    )
    assert generated != f"CREATE ROLE comfort_app LOGIN PASSWORD '{SAMPLE_PASSWORD}'"
    assert "''" in generated.split("PASSWORD ", 1)[1]


def test_documented_usage_in_files_passes_the_password_raw():
    """The USAGE header and the README must not tell operators to embed
    quotes — that is the documentation half of the same bug."""
    for path in (PROVISION_SQL, BACKEND_DIR / "README.md"):
        text = path.read_text(encoding="utf-8")
        offenders = re.findall(r"-v\s+comfort_\w+_password=\"'[^\"]*'\"", text)
        assert not offenders, (
            f"{path.name} still documents the double-quoting invocation: {offenders}"
        )
