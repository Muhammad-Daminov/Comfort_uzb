"""Alembic migration runner for Comfort UZB.

Database domain (docs/05_AGENT_ARCHITECTURE.md) owns this file. Every
migration in versions/ is hand-written raw SQL via op.execute() — there is
no ORM model layer here and autogenerate is not used, so schema drift
between "what the models say" and "what's actually in the DB" can't
happen. This is a deliberate choice, not an oversight: it also means using
SQLAlchemy here is purely a migration-tooling dependency and does not
resolve OPEN-3 (asyncpg vs SQLAlchemy Core for the Repository layer,
Phase-03's concern).

Connection string comes from the DATABASE_URL environment variable only —
never hardcoded — so dev and prod (REQ-OPS-008) can never accidentally
share a migration run. Expected in production to be a
`postgresql+psycopg://comfort_migrate:...@/comfort_uzb?host=/var/run/postgresql`
style DSN (Unix socket, per ADR-1/§13.3), since comfort_migrate is the only
role Alembic is allowed to connect as (§12.2, AGENTS/database.md).
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL is not set. Refusing to guess a connection string — "
        "dev and prod must never share one (REQ-OPS-008)."
    )
# Alembic stores this in a ConfigParser section, which treats `%` as the
# start of an interpolation — a URL-encoded password (`%40` for `@`) or a
# `?options=-c%20role%3D...` clause raised "invalid interpolation syntax"
# and refused to migrate at all. Escaping is the documented Alembic rule.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# No ORM models / target_metadata: every migration is explicit raw SQL,
# so there is nothing to autogenerate against.
target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (`alembic upgrade --sql`)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
