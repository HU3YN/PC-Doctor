"""Alembic environment: runs migrations against the configured database."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from pcdoctor_api import models  # noqa: F401 - registers the tables on Base.metadata
from pcdoctor_api.config import get_settings
from pcdoctor_api.db import Base, ensure_sqlite_folder

config = context.config
if not config.get_main_option("sqlalchemy.url"):
    # Run from the command line (alembic upgrade head): use the app's settings.
    config.set_main_option("sqlalchemy.url", get_settings().sqlalchemy_url.replace("%", "%%"))

ensure_sqlite_folder(config.get_main_option("sqlalchemy.url") or "")
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things; batch mode rebuilds the table.
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
