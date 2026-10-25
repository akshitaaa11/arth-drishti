from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from bsp.common.config import get_env_var, get_project_root

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Ensure the SQLite target directory exists before Alembic connects.
root = get_project_root()
local_dir = root / ".local"
local_dir.mkdir(parents=True, exist_ok=True)

# Use environment override when a real Postgres connection is configured.
url = get_env_var("DATABASE_URL")
if url:
    config.set_main_option("sqlalchemy.url", url)
else:
    local_db = local_dir / "bsp.db"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{local_db.as_posix()}")


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=None,
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
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
