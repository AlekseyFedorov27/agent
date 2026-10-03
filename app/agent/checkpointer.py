from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import get_settings

_saver: AsyncPostgresSaver | None = None
_ctx_manager = None


def _to_psycopg_url(asyncpg_url: str) -> str:
    """asyncpg-URL → обычный psycopg-URL."""
    return asyncpg_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def init_checkpointer() -> AsyncPostgresSaver:
    """Создаёт saver и таблицы. Вызывается один раз в lifespan."""
    global _saver, _ctx_manager
    if _saver is not None:
        return _saver

    settings = get_settings()
    conn_string = _to_psycopg_url(settings.database_url)

    _ctx_manager = AsyncPostgresSaver.from_conn_string(conn_string)
    _saver = await _ctx_manager.__aenter__()
    await _saver.setup()  # создаёт таблицы checkpoints, checkpoint_blobs, ...
    return _saver


async def close_checkpointer() -> None:
    global _saver, _ctx_manager
    if _ctx_manager is not None:
        await _ctx_manager.__aexit__(None, None, None)
    _saver = None
    _ctx_manager = None


def get_checkpointer() -> AsyncPostgresSaver:
    if _saver is None:
        raise RuntimeError("Checkpointer is not initialized")
    return _saver