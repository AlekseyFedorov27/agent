# Travel Planning Agent

**Серверный ИИ-агент для планирования путешествий на LangGraph + FastAPI + PostgreSQL/pgvector, с подтверждением плана человеком (Human-in-the-Loop), RAG по базе знаний и детерминированной проверкой бюджета.**

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-6B46C1)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white)
![Vue](https://img.shields.io/badge/Vue_3-42B883?logo=vuedotjs&logoColor=white)
![Status](https://img.shields.io/badge/status-portfolio%20project-informational)

> **English summary.** A stateful LLM agent (not a single prompt): it extracts trip parameters from free text, asks clarifying questions, retrieves context from a pgvector knowledge base (RAG), drafts an itinerary, checks the budget in plain Python (the LLM never decides whether the budget fits), and pauses for human approval via LangGraph `interrupt()`. State is persisted in PostgreSQL, runs and events are stored for debugging, the API is JWT-protected and traced with OpenTelemetry. Includes a Vue 3 chat UI and admin pages.

---

## Кратко для рекрутера и тимлида

| Вопрос | Ответ |
|---|---|
| Что это? | Бэкенд ИИ-агента, который по сообщению вида «Хочу в Португалию на 7 дней в мае, бюджет 1200 €, люблю музеи» собирает маршрут, проверяет его на соответствие бюджету и отдаёт пользователю на подтверждение. |
| Чем это не «обёртка над ChatGPT»? | Агент работает по явному графу состояний с лимитами итераций, сохраняет состояние в БД, приостанавливается на решение человека и продолжает с той же точки. Вердикт по бюджету выносит код, а не модель. |
| Что в стеке? | Python 3.11, FastAPI, LangGraph, SQLAlchemy 2 (async), PostgreSQL + pgvector, Alembic, JWT, OpenTelemetry, Vue 3 + TypeScript. |
| Что можно проверить за 5 минут? | Граф агента — `app/agent/graph.py`; проверка бюджета — `app/nodes/budget_check.py`; HITL — `app/nodes/plan_approval.py` и `app/hitl/`; RAG — `app/nodes/research.py` и `app/knowledge/`. |
| Что здесь честно не доделано? | См. раздел [Известные ограничения](#известные-ограничения-и-план-развития). |

---

## Какую задачу решает

Один вызов языковой модели не делает продукт. Чтобы агентом можно было пользоваться, нужно:

- понимать, каких данных не хватает, и **задавать уточняющие вопросы**, а не выдумывать;
- опираться на **проверяемый контекст** (база знаний), а не только на память модели;
- не выдавать **оценки модели за подтверждённые цены**;
- давать человеку **подтвердить или отклонить** результат, и учитывать его комментарий;
- **сохранять состояние** диалога и восстанавливать его после паузы;
- оставлять **историю запусков и событий**, чтобы можно было разобраться, что пошло не так.

Проект показывает, как собрать это в одном приложении с понятными границами ответственности.

## Как это выглядит в работе

1. Пользователь пишет: *«Хочу в Италию»*. Агент понимает, что не хватает длительности и месяца, и задаёт **один** короткий уточняющий вопрос.
2. Пользователь отвечает: *«На 5 дней, в сентябре, бюджет 900 €»*. Агент объединяет ответ с уже известными данными (диалог продолжается по тому же `thread_id`).
3. Агент ищет в базе знаний достопримечательности, еду и логистику по стране, составляет маршрут в Markdown и извлекает из него стоимость по статьям: жильё, активности, транспорт, питание.
4. Код сравнивает сумму с бюджетом и добавляет в маршрут блок «Бюджет» с честным статусом: подтверждено, превышение или «только ориентировочная оценка».
5. Если подтверждённое превышение есть, агент автоматически перепланирует маршрут (не более 2 раз).
6. Граф **останавливается** и отдаёт план пользователю. Пользователь подтверждает его или отклоняет с комментарием («9 дней вместо 7», «без музеев»). Комментарий меняет параметры запроса, и агент дорабатывает маршрут (не более 5 раз).

---

## Архитектура

```mermaid
flowchart TB
    U[Пользователь / администратор] --> FE[Vue 3 SPA]
    FE -->|HTTP + SSE, JWT| API[FastAPI]

    API --> AUTH[Аутентификация и роли]
    API --> RUNS[Запуски и события]
    API --> HITL[Подтверждения HITL]
    API --> RT[Runtime агента]

    RT --> G[Граф LangGraph]
    G --> LLM[LLM: OpenAI-совместимый API]
    G --> RAG[Поиск по базе знаний]
    RAG --> EMB[Эмбеддинги: nomic-embed-text через Ollama]

    RUNS --> PG[(PostgreSQL + pgvector)]
    HITL --> PG
    RAG --> PG
    G --> CP[AsyncPostgresSaver] --> PG
    API -. трассы .-> OTEL[OpenTelemetry / OTLP]
```

### Граф агента

```mermaid
flowchart TD
    S((START)) --> T[triage: извлечь параметры поездки]
    T -->|не хватает данных| Q[ask_user: задать вопрос]
    Q --> E1((END))
    T -->|данных достаточно| R[research: RAG по базе знаний]
    R --> P[plan: составить маршрут]
    P --> B[budget_check: проверить бюджет кодом]
    B -->|подтверждённое превышение,<br/>replan_count < 2| RP[replan]
    RP --> B
    B --> A[plan_approval: interrupt, ждём человека]
    A -->|подтверждено| E2((END))
    A -->|отклонено,<br/>revisions < 5| RP
```

Обязательные поля запроса: `destination`, `duration_days`, `month`. Остальные (`budget`, `currency`, `interests`, `constraints`, `travel_type`) опциональны; валюта по умолчанию — EUR, поддерживаются EUR, USD, RUB.

---

## Ключевые инженерные решения

| Решение | Зачем |
|---|---|
| **Явный граф LangGraph вместо свободного ReAct-цикла** | Переходы и лимиты итераций (`max_replans=2`, `max_plan_revisions=5`) заданы кодом: поведение предсказуемо и тестируемо, агент не уходит в бесконечные циклы. |
| **Структурированный вывод через Pydantic** (`triage`, `plan`) | Параметры поездки и расходы приходят как валидированные модели (границы значений, очистка строк). Используются два режима structured output (`json_schema`, затем `function_calling`), а ошибка не маскируется «пустой» схемой. |
| **Бюджет проверяет код, а не LLM** (`budget_check.py`) | Модель только извлекает суммы и уровень уверенности (`exact` / `estimated` / `partial` / `unknown`). Вердикт (`verified`, `over_budget`, `estimated`, `unverified`) выносит детерминированная функция. Ориентировочные цены не выдаются за подтверждённые, валюты без курса не пересчитываются. |
| **Автоперепланирование только при подтверждённом превышении** | Не сжигаем токены на гипотетических оценках; отдельные счётчики для авто-replan по бюджету и для доработок по отказу пользователя. |
| **HITL на уровне плана** (`interrupt()` + `Command(resume=...)`) | Пользователь решает, принимать ли маршрут. Комментарий пользователя имеет приоритет над бюджетом и **обновляет запрос** (отдельный структурированный «патч» полей), иначе следующая итерация откатилась бы к исходным данным. |
| **Два слоя хранения** | Чекпоинты LangGraph (`AsyncPostgresSaver`) хранят состояние графа; прикладные таблицы `runs`, `events`, `approvals` хранят историю для API и отладки. |
| **Надёжность запусков** | Статусы `running` / `interrupted` / `completed` / `failed`; при обрыве SSE-соединения запуск помечается как `failed` (запись защищена `asyncio.shield`); при ошибке возобновления решение по подтверждению откатывается, чтобы пользователь мог повторить. |
| **RAG на pgvector** | Эмбеддинги `nomic-embed-text` (768 измерений), косинусное расстояние, фильтр по метаданным (`country_ru`), три тематических запроса на запуск (достопримечательности, еда, правила и логистика), чанкинг по абзацам (900 символов, перекрытие 150). |
| **Безопасность** | bcrypt с проверкой лимита 72 байта; JWT access и refresh с проверкой типа токена; все запуски, диалоги и подтверждения проверяются на принадлежность пользователю; админ-маршруты только для суперпользователя. |
| **Наблюдаемость** | OpenTelemetry для FastAPI, SQLAlchemy и HTTPX; к спанам добавляются `user_id`, `thread_id`, `run_id`. |

---

## Технологический стек

| Область | Технологии |
|---|---|
| Язык и API | Python 3.11+, FastAPI, Uvicorn, Pydantic v2, pydantic-settings |
| Агент | LangGraph, LangChain Core, `langchain-openai` (OpenAI-совместимый API) |
| RAG | pgvector, `langchain-ollama` (`nomic-embed-text`), `python-frontmatter` |
| Данные | PostgreSQL 16, SQLAlchemy 2 (async), asyncpg, psycopg, Alembic |
| Безопасность | JWT (`python-jose`), bcrypt |
| Наблюдаемость | OpenTelemetry (API, SDK, OTLP gRPC, инструментирование FastAPI, SQLAlchemy, HTTPX) |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Vue Router, Axios, Markdown-рендеринг, экспорт в PDF |
| Инструменты разработки | uv, pytest, pytest-asyncio, Ruff |

---

## Структура проекта

```text
.
├── app/
│   ├── agent/            # граф, состояние, runtime, LLM-клиент, SSE и HTTP-маршруты агента
│   │   ├── graph.py      # сборка StateGraph
│   │   ├── state.py      # типизированное состояние (TypedDict)
│   │   ├── runtime.py    # запуск, возобновление, стриминг
│   │   └── router.py     # /agent/run, /agent/stream, /agent/status
│   ├── nodes/            # узлы графа
│   │   ├── triage.py         # извлечение параметров поездки
│   │   ├── ask_user.py       # уточняющий вопрос
│   │   ├── research.py       # RAG
│   │   ├── plan.py           # план и перепланирование
│   │   ├── budget_check.py   # проверка бюджета
│   │   └── plan_approval.py  # HITL: подтверждение плана
│   ├── knowledge/        # модель чанков, эмбеддинги, поиск, загрузка документов
│   ├── hitl/             # подтверждения: модель, сервис, API
│   ├── runs/             # запуски и события, админ-маршруты
│   ├── auth/             # регистрация, вход, токены, админ-управление
│   ├── core/             # БД, безопасность, телеметрия
│   ├── tools/            # инструменты агента
│   ├── config.py         # настройки из переменных окружения
│   └── main.py           # приложение FastAPI и жизненный цикл
├── alembic/              # миграции прикладной схемы
├── frontend/             # Vue 3 + TypeScript
├── tests/                # unit и integration (нужен PostgreSQL)
├── docker-compose.yml    # PostgreSQL с pgvector
└── pyproject.toml
```

---

## Быстрый старт

### Что понадобится

- Python 3.11+ и [uv](https://docs.astral.sh/uv/)
- Node.js 20+ (для frontend)
- Docker (для PostgreSQL)
- [Ollama](https://ollama.com/) с моделью `nomic-embed-text` (эмбеддинги для RAG)
- Доступ к любому **OpenAI-совместимому API** для языковой модели (ключ, адрес и название модели)

### 1. База данных

```bash
docker compose up -d postgres
```

PostgreSQL с расширением pgvector поднимется на порту **5433** (база `agent_db`). Учётные данные в `docker-compose.yml` предназначены только для локальной разработки.

### 2. Переменные окружения

Создайте файл `.env` в корне репозитория:

```dotenv
APP_NAME=agent-backend
APP_ENV=dev
DEBUG=true

DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/agent_db

JWT_SECRET_KEY=замените-на-длинный-случайный-секрет
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Языковая модель: любой OpenAI-совместимый endpoint
OPENAI_API_KEY=ваш-ключ
OPENAI_BASE_URL=https://адрес-провайдера/v1
LLM_MODEL=название-модели
LLM_TEMPERATURE=0.0
LLM_TOP_P=1.0

# Ollama используется для эмбеддингов (nomic-embed-text)
OLLAMA_BASE_URL=http://localhost:11434
```

Не добавляйте `.env` с реальными ключами в Git.

### 3. Зависимости и миграции

```bash
uv sync
uv run alembic upgrade head
```

Таблицы чекпоинтов LangGraph создаются приложением при старте и не входят в миграции Alembic.

### 4. База знаний (RAG)

```bash
ollama pull nomic-embed-text
```

Положите Markdown-документы в папку `knowledge/` в корне репозитория. В начале каждого файла указывается YAML-frontmatter с метаданными; для фильтрации по стране используется поле `country_ru`:

```markdown
---
country_ru: Португалия
---

# Лиссабон: что посмотреть
...
```

Загрузка документов (документы режутся на чанки, считаются эмбеддинги, чанки пишутся в `knowledge_chunks`; по умолчанию таблица перед загрузкой очищается):

```bash
uv run python -m app.knowledge.ingest
```

### 5. Backend

```bash
uv run uvicorn app.main:app --reload --port 8000
```

- Swagger UI: http://localhost:8000/docs
- Проверка состояния: http://localhost:8000/health

### 6. Frontend (опционально)

```bash
cd frontend
npm install
npm run dev
```

Откройте адрес, который покажет Vite (обычно http://localhost:5173).

---

## Пример использования через API

```bash
# 1. Регистрация и вход (схемы полей смотрите в /docs)
#    POST /auth/register, POST /auth/login → access_token

# 2. Запуск агента
curl -X POST http://localhost:8000/agent/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Хочу в Португалию на 7 дней в мае, бюджет 1200 EUR, люблю музеи и местную кухню"}'
```

Ответ содержит `thread_id`, `run_id`, `status` и, если граф остановился на подтверждении плана, `pending_approval_id`. Статус `interrupted` означает, что агент ждёт решения человека.

Если агенту не хватило данных, он вернёт уточняющий вопрос. Ответьте на него, передав тот же `thread_id`:

```bash
curl -X POST http://localhost:8000/agent/run \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"thread_id": "<thread_id из предыдущего ответа>", "message": "На 5 дней, в сентябре"}'
```

Подтверждение или отклонение плана с комментарием:

```bash
curl -X POST http://localhost:8000/approvals/$APPROVAL_ID/decide \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"approved": false, "comment": "9 дней вместо 7, без музеев"}'
```

### Основные эндпоинты

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/health` | Базовая проверка состояния |
| `POST` | `/agent/run` | Запуск или продолжение диалога (синхронно) |
| `POST` | `/agent/stream` | Запуск со стримингом событий через SSE |
| `GET` | `/agent/status/{thread_id}` | Состояние диалога пользователя |
| `GET` | `/approvals` | Ожидающие подтверждения пользователя |
| `GET` | `/approvals/{approval_id}` | Одно подтверждение |
| `POST` | `/approvals/{approval_id}/decide` | Подтвердить или отклонить, возобновить граф |

Также есть маршруты аутентификации, истории запусков и событий и административные маршруты; полный список и схемы — в `/docs`.

---

## Тесты

```bash
uv run pytest                      # все тесты
uv run pytest tests/unit           # быстрые, без БД
uv run pytest tests/integration    # нужен PostgreSQL
uv run ruff check .                # статический анализ
```

Сейчас покрыты, в частности, хеширование паролей и JWT (корректный круг, подделка, просрочка, неверный ключ, подмена типа токена).

---

## Известные ограничения и план развития

Проект учебно-портфолио, а не готовая к продакшену платформа. Что я вижу как незакрытое и намерен сделать:

- **Тесты графа и API.** Нужны тесты маршрутизации узлов с замоканной LLM, сценариев подтверждения и отказа, изоляции пользователей и завершения SSE-потока.
- **Оценка качества агента.** Небольшой воспроизводимый набор запросов с метриками (корректность извлечения параметров, доля маршрутов, укладывающихся в бюджет, число доработок).
- **Стоимость маршрута** извлекается из текста самой моделью, поэтому для неё честно выставляется уровень уверенности; источников цен в базе знаний пока нет.
- **Потоковая выдача токенов** в SSE привязана к узлу `llm` прежнего графа и для текущих узлов требует доработки; события узлов стримятся.
- **Конкурентные решения по одному подтверждению** не защищены блокировкой строки в БД.
- **Безопасность на публичном стенде:** нет ограничения частоты запросов, нет ротации и отзыва refresh-токенов, ошибки отдаются клиенту подробно.
- **Развёртывание:** в `docker-compose.yml` только PostgreSQL; нет Dockerfile для приложения и CI.
- **Локальные модели:** клиент рассчитан на OpenAI-совместимый API; настройки Ollama для генерации в конфиге остались от прежней версии и не используются (Ollama нужен для эмбеддингов).

```mermaid
flowchart LR
    NOW[Сейчас: граф, RAG, HITL, бюджет, история] --> T[Тесты графа и API]
    T --> CI[Dockerfile и CI]
    CI --> EV[Оценка качества агента]
    EV --> HARD[Rate limiting, ротация токенов, блокировки]
    HARD --> SRC[Источники цен и расширение базы знаний]
```

---

## Что проект демонстрирует

- Проектирование **агента с состоянием** на LangGraph: условные переходы, лимиты, прерывание и возобновление.
- **RAG на pgvector**: загрузка, чанкинг, векторный поиск с метаданными.
- Аккуратную работу с **неопределённостью LLM**: structured output, валидация, уровни уверенности, запрет выдавать оценку за факт.
- **HITL** как механизм управления процессом, а не украшение.
- Разделение слоёв (граф, runtime, API, хранение) и **асинхронный** бэкенд на SQLAlchemy 2 / asyncpg.
- **Аутентификацию и авторизацию**, историю запусков и **наблюдаемость**.
- Понимание того, что ещё нужно сделать до продакшена, и честный список этих вещей.

## Автор

GitHub: [AlekseyFedorov27](https://github.com/AlekseyFedorov27)
