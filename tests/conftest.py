"""Общие фикстуры.

E2E-тесты (`tests/test_e2e_chat.py`) работают так:
- Postgres — одноразовая test-БД на 5433 (docker-compose.yml);
- LangGraph — `InMemorySaver`, поэтому `interrupt()` и `Command(resume=...)`
  работают без реального checkpointer;
- LLM — мок через `patch_llm`;
- RAG — мок через `patch_rag` (не зовём Ollama).

Unit-тесты (без `integration` маркера) не требуют БД вообще.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base, get_db


# --------------------------------------------------------------------------- #
# Конфиг БД
# --------------------------------------------------------------------------- #

DB_HOST = os.getenv("TEST_DB_HOST", "localhost")
DB_PORT = os.getenv("TEST_DB_PORT", "5433")
DB_USER = os.getenv("TEST_DB_USER", "postgres")
DB_PASSWORD = os.getenv("TEST_DB_PASSWORD", "postgres")
TEST_DB_NAME = os.getenv("TEST_DB_NAME", f"agent_test_{uuid.uuid4().hex[:8]}")

ADMIN_DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/postgres"
TEST_DB_URL_ASYNC = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"
)

# Файлы, автоматически помечаемые маркером integration.
INTEGRATION_PATHS = ("test_e2e_chat.py",)


async def _admin_execute(sql: str) -> None:
    conn = await asyncpg.connect(ADMIN_DB_URL)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if any(m in path for m in INTEGRATION_PATHS):
            item.add_marker(pytest.mark.integration)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_test_database(request: pytest.FixtureRequest):
    needs_db = any("integration" in it.keywords for it in request.session.items)
    if not needs_db:
        yield
        return
    await _admin_execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
    await _admin_execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    yield
    await _admin_execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')


# --------------------------------------------------------------------------- #
# Engine / Schema / Session
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture(scope="session")
async def engine(_setup_test_database) -> AsyncIterator[AsyncEngine]:
    from app.auth import models as _auth_models          # noqa: F401
    from app.hitl import models as _hitl_models          # noqa: F401
    from app.runs import models as _runs_models          # noqa: F401
    from app.knowledge import models as _knowledge_models  # noqa: F401

    eng = create_async_engine(TEST_DB_URL_ASYNC, echo=False)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


async def _truncate_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE'))


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await _truncate_all(engine)


@pytest_asyncio.fixture
async def test_session(session: AsyncSession) -> AsyncSession:
    """Алиас на `session` — старое имя в unit-тестах сервисов."""
    return session


# --------------------------------------------------------------------------- #
# FastAPI-клиент c InMemorySaver и без lifespan
# --------------------------------------------------------------------------- #

def _build_test_app():
    """Собирает приложение, но не запускает lifespan."""
    from app.main import create_app
    from app.agent.graph import build_graph
    from app.agent.runtime import AgentRuntimeService
    from langgraph.checkpoint.memory import InMemorySaver

    app = create_app()

    # Граф с InMemorySaver — interrupt()/resume() работают в памяти,
    # реальный AsyncPostgresSaver не нужен.
    app.state.runtime = AgentRuntimeService(build_graph(InMemorySaver()))
    return app


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    app = _build_test_app()
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with maker() as s:
            try:
                yield s
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authenticated_client(client: AsyncClient) -> AsyncIterator[AsyncClient]:
    email = f"user_{uuid.uuid4().hex[:8]}@test.local"
    password = "password123"

    r = await client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "Test User"},
    )
    assert r.status_code == 201, r.text

    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    client.headers["Authorization"] = f"Bearer {token}"
    try:
        yield client
    finally:
        client.headers.pop("Authorization", None)


# --------------------------------------------------------------------------- #
# Мок LLM
# --------------------------------------------------------------------------- #

class _FakeStructuredOutput:
    def __init__(self, schema: type, queue: list[Any], label: str) -> None:
        self._schema = schema
        self._queue = queue
        self._label = label

    async def ainvoke(self, messages, **kw):
        # 1) точное совпадение типа
        for i, r in enumerate(self._queue):
            if isinstance(r, self._schema):
                return self._queue.pop(i)
        # 2) dict → валидируем в схему
        for i, r in enumerate(self._queue):
            if isinstance(r, dict):
                try:
                    validated = self._schema.model_validate(r)
                    self._queue.pop(i)
                    return validated
                except Exception:
                    continue
        raise AssertionError(
            f"[{self._label}] нет ответа для {self._schema.__name__}. "
            f"Остаток очереди: {[type(x).__name__ for x in self._queue]}"
        )


class _FakeLLM:
    def __init__(self, queue: list[Any], label: str) -> None:
        self._queue = queue
        self._label = label

    def bind_tools(self, tools):
        return self

    def with_structured_output(self, schema, method=None):
        return _FakeStructuredOutput(schema, self._queue, self._label)

    async def ainvoke(self, messages, **kw):
        from langchain_core.messages import AIMessage
        for i, r in enumerate(self._queue):
            if isinstance(r, (AIMessage, str)):
                item = self._queue.pop(i)
                return item if isinstance(item, AIMessage) else AIMessage(content=item)
        raise AssertionError(
            f"[{self._label}] нет AIMessage в очереди. "
            f"Остаток: {[type(x).__name__ for x in self._queue]}"
        )


@pytest.fixture
def patch_llm(monkeypatch) -> Callable[[list[Any]], None]:
    """
    Устанавливает фейковый `get_llm` во всех модулях, которые его используют.

    Порядок в очереди не важен: `patch_llm` отдаёт ответ по типу схемы —
    `Triage` для `with_structured_output(Triage)`, `CostExtract` для
    `with_structured_output(CostExtract)` и т.д.
    """
    def _apply(responses: list[Any]) -> None:
        # Общая очередь на все модули — так сохраняется порядок вызовов
        # внутри одного сценария, но узлы всё равно берут «свой» тип.
        queue = list(responses)

        def _factory(label: str):
            def _get_llm():
                return _FakeLLM(queue, label)
            return _get_llm

        # Патчим в каждом модуле, где есть собственный `get_llm`
        for mod in (
            "app.nodes.triage",
            "app.nodes.plan",
            "app.nodes.ask_user",
        ):
            monkeypatch.setattr(f"{mod}.get_llm", _factory(mod))

    return _apply


# --------------------------------------------------------------------------- #
# Мок RAG
# --------------------------------------------------------------------------- #

@pytest.fixture
def patch_rag(monkeypatch) -> Callable[..., None]:
    """
    Возвращает фиктивные документы из `search_knowledge`.

    По умолчанию — один документ `spain.md`. Можно переопределить
    содержимое через аргументы.
    """
    def _apply(documents: list[dict[str, Any]] | None = None) -> None:
        docs = documents if documents is not None else [
            {
                "doc_id": "spain.md",
                "content": "Барселона — май, архитектура Гауди, пляжи.",
                "meta": {"country_ru": "Испания", "path": "spain.md"},
                "score": 0.9,
            }
        ]

        async def _fake_search(session, query, *, top_k=5, filters=None):
            return list(docs)

        monkeypatch.setattr("app.nodes.research.search_knowledge", _fake_search)

    return _apply


# --------------------------------------------------------------------------- #
# Мелкие хелперы
# --------------------------------------------------------------------------- #

@pytest.fixture
def user_payload() -> dict[str, str]:
    return {
        "email": f"u_{uuid.uuid4().hex[:8]}@test.local",
        "password": "password123",
        "name": "Test User",
    }