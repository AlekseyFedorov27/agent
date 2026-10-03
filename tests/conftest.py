"""
Общие фикстуры для всех тестов.

Стратегия:
- Отдельная БД agent_test (создаётся и удаляется на сессию).
- Схема создаётся через Base.metadata.create_all (Alembic в тестах не гоняем —
  миграции проверяются отдельно, здесь важна скорость).
- Отдельный AsyncPostgresSaver на тестовую БД.
- Mock LLM — подменяет ChatOllama детерминированными ответами.
- FastAPI test client — httpx.AsyncClient с ASGITransport.
"""

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

# Для новых версий pytest-asyncio на Windows принудительно ставим SelectorEventLoopPolicy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
# ---------------------------------------------------------------------------
# ВАЖНО: переменные окружения должны быть установлены ДО первого импорта
# app.config.get_settings(), потому что там @lru_cache.
# ---------------------------------------------------------------------------
TEST_DB_NAME = "agent_test"
TEST_DB_URL = f"postgresql+asyncpg://postgres:postgres@localhost:5432/{TEST_DB_NAME}"
TEST_DB_URL_PSYCOPG = f"postgresql://postgres:postgres@localhost:5432/{TEST_DB_NAME}"
ADMIN_DB_URL = "postgresql://postgres:postgres@localhost:5432/postgres"

os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["JWT_SECRET_KEY"] = "test-secret-key-do-not-use-in-prod"
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"

# Импорты после установки env
import asyncpg  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.agent.graph import build_graph  # noqa: E402
from app.agent.runtime import AgentRuntimeService  # noqa: E402
from app.auth.models import User  # noqa: E402
from app.auth.service import register_user  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402


# ===========================================================================
# Event loop (Windows)
# ===========================================================================

@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Гарантирует использование SelectorEventLoop на Windows для psycopg."""
    if sys.platform == "win32":
        policy = asyncio.WindowsSelectorEventLoopPolicy()
        loop = policy.new_event_loop()
    else:
        loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Чтобы pytest-asyncio 0.24+ знал, какую фабрику использовать:
@pytest.fixture(scope="session")
def _asyncio_loop_factory():
    if sys.platform == "win32":
        import selectors
        return lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.new_event_loop

# ===========================================================================
# Тестовая БД: создание / удаление
# ===========================================================================

async def _admin_execute(*statements: str) -> None:
    conn = await asyncpg.connect(ADMIN_DB_URL)
    try:
        for stmt in statements:
            await conn.execute(stmt)
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
async def _setup_test_database() -> AsyncIterator[None]:
    """Создаёт agent_test до тестов, удаляет после."""
    await _admin_execute(
        f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)",
        f"CREATE DATABASE {TEST_DB_NAME}",
    )
    yield
    await _admin_execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")


# ===========================================================================
# Engine / session
# ===========================================================================

@pytest.fixture(scope="session")
async def test_engine(_setup_test_database):
    engine = create_async_engine(
        TEST_DB_URL,
        # pool_pre_ping=True,
        connect_args={
            "prepared_statement_cache_size": 0,
            "server_settings": {"application_name": "agent-backend-tests"},
        },
    )

    # Регистрируем все модели в metadata
    from app.auth import models as _auth_models  # noqa: F401
    from app.hitl import models as _hitl_models  # noqa: F401
    from app.runs import models as _runs_models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def test_session_factory(test_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture
async def test_session(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Свежая сессия на каждый тест. Не откатывает транзакции сама —
    изоляция обеспечивается через TRUNCATE в _clean_db."""
    async with test_session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
async def _clean_db(test_engine) -> AsyncIterator[None]:
    """
    TRUNCATE наших таблиц перед каждым тестом.
    LangGraph-таблицы чистим, только если они уже созданы (checkpointer
    поднимается отдельной фикстурой, которая не autouse).
    """
    from sqlalchemy import text

    async with test_engine.begin() as conn:
        # Наши таблицы — точно есть после Base.metadata.create_all
        await conn.execute(
            text(
                "TRUNCATE TABLE events, approvals, runs, users "
                "RESTART IDENTITY CASCADE"
            )
        )

        # LangGraph-таблицы — могут отсутствовать до первого test_checkpointer
        await conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF to_regclass('public.checkpoints') IS NOT NULL THEN
                        TRUNCATE TABLE checkpoint_writes,
                                       checkpoint_blobs,
                                       checkpoints
                        CASCADE;
                    END IF;
                END $$;
                """
            )
        )
    yield


# ===========================================================================
# Checkpointer / runtime
# ===========================================================================

@pytest.fixture(scope="session")
async def test_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(TEST_DB_URL_PSYCOPG) as saver:
        await saver.setup()
        yield saver


@pytest.fixture
def test_runtime(test_checkpointer) -> AgentRuntimeService:
    graph = build_graph(test_checkpointer)
    return AgentRuntimeService(graph)


# ===========================================================================
# FastAPI app / client
# ===========================================================================

@pytest.fixture
async def app(test_session_factory, test_runtime, monkeypatch):
    """
    Создаём приложение без стандартного lifespan (там свои checkpointer и engine).
    Подменяем get_db на тестовую фабрику и складываем runtime в app.state.
    """
    from app.agent.dependencies import get_runtime

    fastapi_app = create_app()

    # Убираем настоящий lifespan — он поднимет свой checkpointer на prod-БД.
    fastapi_app.router.lifespan_context = _null_lifespan

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with test_session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_runtime] = lambda: test_runtime

    fastapi_app.state.runtime = test_runtime

    monkeypatch.setattr(
        "app.agent.router.get_session_factory",
        lambda: test_session_factory,
    )
    return fastapi_app


async def _null_lifespan(app):
    """Заглушка lifespan для тестов — ничего не поднимаем/не закрываем."""
    yield


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ===========================================================================
# Пользователи
# ===========================================================================

@pytest.fixture
async def test_user(test_session: AsyncSession) -> User:
    user = await register_user(
        test_session,
        email="user@test.com",
        password="testpassword123",
    )
    return user


@pytest.fixture
async def auth_headers(client: AsyncClient, test_user: User) -> dict[str, str]:
    response = await client.post(
        "/auth/login",
        json={"email": test_user.email, "password": "testpassword123"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def authenticated_client(
    app, auth_headers: dict[str, str]
) -> AsyncIterator[AsyncClient]:
    """Отдельный клиент с Authorization. Не мутирует общий `client`."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_headers,
    ) as ac:
        yield ac


# ===========================================================================
# Mock LLM
# ===========================================================================

class FakeLLM:
    """
    Минимальный мок ChatOllama.
    Ответы задаются заранее; каждый вызов invoke() возвращает следующий.
    bind_tools() — no-op, возвращает self.
    """

    def __init__(self, responses: list[AIMessage]):
        self.responses = list(responses)
        self._idx = 0
        self.calls: list[Any] = []

    def bind_tools(self, tools, **kwargs) -> "FakeLLM":
        return self

    def invoke(self, messages, **kwargs) -> AIMessage:
        self.calls.append(messages)
        if self._idx >= len(self.responses):
            raise AssertionError(
                f"FakeLLM: no more responses (index={self._idx}, "
                f"got {len(self.responses)} total)"
            )
        resp = self.responses[self._idx]
        self._idx += 1
        return resp

    @property
    def call_count(self) -> int:
        return len(self.calls)


@pytest.fixture
def patch_llm(monkeypatch) -> callable:
    """
    Возвращает функцию, которая подменяет get_llm на FakeLLM с заданными ответами.
    Использование:
        patch_llm([AIMessage(content="hello")])
        patch_llm([AIMessage(tool_calls=[...]), AIMessage(content="done")])
    """
    from app.agent import nodes

    def _patch(responses: list[AIMessage]) -> FakeLLM:
        fake = FakeLLM(responses)
        monkeypatch.setattr(nodes, "get_llm", lambda: fake)
        return fake

    return _patch


# ===========================================================================
# Хелперы для tool_calls
# ===========================================================================

def make_tool_call(name: str, args: dict, *, id: str | None = None) -> dict:
    return {
        "name": name,
        "args": args,
        "id": id or str(uuid.uuid4()),
        "type": "tool_call",
    }