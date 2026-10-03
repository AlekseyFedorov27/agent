import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.core.database import Base

# noqa: F401 — импорты нужны, чтобы модели зарегистрировались в Base.metadata
from app.auth import models as _auth_models  # noqa: F401
from app.hitl import models as _hitl_models  # noqa: F401
from app.runs import models as _runs_models  # noqa: F401

# Alembic Config object
config = context.config

# Логирование
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Подменяем URL из наших настроек
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Metadata для autogenerate
target_metadata = Base.metadata


# --------------------------------------------------------------------------- #
# Таблицы, которыми управляет LangGraph. Мы их не трогаем в миграциях.
# AsyncPostgresSaver.setup() создаёт их сам.
# --------------------------------------------------------------------------- #
LANGGRAPH_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}


def include_object(obj, name, type_, reflected, compare_to):
    """Исключает таблицы LangGraph из autogenerate."""
    if type_ == "table" and name in LANGGRAPH_TABLES:
        return False
    return True


# --------------------------------------------------------------------------- #
# Offline-режим (генерация SQL без подключения к БД)
# --------------------------------------------------------------------------- #

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# --------------------------------------------------------------------------- #
# Online-режим (подключение к БД, async)
# --------------------------------------------------------------------------- #

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()