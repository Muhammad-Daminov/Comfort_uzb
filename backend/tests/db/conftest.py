"""Fixtures for Phase 02 database verification tests.

These tests need a real, disposable PostgreSQL 16 database — they are not
mocked, because the whole point of Phase 02 is that the *database itself*
enforces the invariants (constraints, triggers, roles), not application
code standing in for it. Point TEST_DATABASE_URL at a throwaway database
that already has `alembic upgrade head` applied (see
docs/tasks/Phase-02-Database.md "Verification strategy" for the exact
commands). Tests are skipped, not failed, if it isn't set — this suite is
meant to run in CI/local dev with a real Postgres, not as a pure-unit
suite.
"""

import os

import psycopg
import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# `pytestmark` is a no-op inside a conftest (it only marks the module it
# is defined in, and a conftest collects no tests) — without this hook the
# suites *errored* in their fixtures when the env var was unset instead of
# skipping as documented.
_SKIP_MARK = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — point it at a disposable Postgres DB "
        "with `alembic upgrade head` already applied to run Phase 02 "
        "database verification tests."
    ),
)


@pytest.fixture
def conn():
    with psycopg.connect(TEST_DATABASE_URL, autocommit=False) as connection:
        yield connection
        connection.rollback()  # never let a test leak data into the next one


@pytest.fixture
def autocommit_conn():
    """For tests that must observe committed state across connections
    (e.g. role-privilege checks that open a second connection as a
    different role) or that test constraint violations, which Postgres
    requires a ROLLBACK to recover from mid-transaction."""
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        yield connection


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(_SKIP_MARK)
