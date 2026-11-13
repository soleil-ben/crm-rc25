"""Alembic environment.

``render_as_batch`` is enabled because SQLite cannot ALTER most constraints in place;
batch mode rebuilds the table instead, which keeps future migrations workable.

``include_object`` comes from ``autogenerate_policy`` beside this file: it excludes exactly
the one migration-owned table from autogeneration so ``alembic check`` stays a real drift
check instead of permanently proposing to drop it. Read that module before adding to it.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from app.core.config import settings
from app.core.db import build_engine
from app.models import Base

# Alembic loads this file by path rather than importing it as part of a package, so a module
# sitting next to it is not importable by name until its directory is on the path. Appended
# rather than prepended: this directory must never take precedence over a real package.
sys.path.append(str(Path(__file__).resolve().parent))

from autogenerate_policy import include_object  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = build_engine()
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
