"""
Узлы plan и replan.

- plan   — генерирует маршрут через LLM, извлекает стоимости.
- replan — перерабатывает маршрут под бюджет.

Стоимости извлекаются ВТОРЫМ вызовом LLM через function_calling.
Если извлечение падает — возвращаются нули, чтобы граф не зацикливался.
"""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.agent.state import AgentState


logger = logging.getLogger(__name__)


# Сколько символов markdown отдавать в _extract_costs.
# Free-модели через Token Harbor не тянут очень длинные промпты —
# жёсткая обрезка + function_calling вместо json_schema.
EXTRACT_MAX_CHARS = 12_000


# ─────────────────────────────────────────────────────────────
# Промпты
# ─────────────────────────────────────────────────────────────

PLAN_SYSTEM_PROMPT = """Ты — опытный travel-планировщик. Составляешь подробный
маршрут поездки на русском языке в формате markdown.

ЖЁСТКИЕ ПРАВИЛА:

1. Отвечай ТОЛЬКО финальным маршрутом. Никаких "Конечно!", "Вот ваш план".

2. Структура ответа — строго такая:

# Маршрут: <город/страна>, <N> дней

Краткое вступление (2–3 предложения) — почему маршрут подойдёт этому
пользователю (интересы, тип поездки, ограничения).

<!-- BUDGET -->

## День 1: <короткое название>

**Утро.** Что, где, во сколько, сколько стоит.
**День.** Конкретно.
**Вечер.** Конкретно.
**Заметки.** Опционально.

## День 2: ...

(и так все дни)

## Жильё

- **Район 1** — почему подойдёт, ~X €/ночь
- **Район 2** — ...

## Транспорт

- Как перемещаться, цены
- Что важно знать

## Что взять с собой / на что обратить внимание

- Пункт 1
- Пункт 2

3. Строку `<!-- BUDGET -->` оставь как есть, ничего вместо неё не пиши.
   Python подставит туда таблицу бюджета.

4. **Используй конкретные цены из предоставленных ДАННЫХ.**
   Если в данных есть "билет 26 €" — пиши "26 €", не "уточнить".
   Пиши "уточнить" только там, где данных реально нет.

5. Учитывай ВСЕ ограничения пользователя (constraints). Если "без ранних
   подъёмов" — не ставь активности до 10:00.

6. Единицы: если валюта EUR — пиши "€".
"""

REPLAN_SYSTEM_PROMPT = """Ты — опытный travel-планировщик. Пользователь уже
получил план, но он превысил бюджет. Переработай его, чтобы уложиться.

Сокращай в первую очередь:
- жильё (выбери район дешевле или другой формат)
- платные активности (замени на бесплатные прогулки)

Сохраняй структуру ответа ровно как в исходном плане, включая строку
`<!-- BUDGET -->` на том же месте. Не выдумывай новые цифры — опирайся
на те, что есть в исходном плане.

Никаких вводных слов. Только финальный маршрут.
"""


class CostExtract(BaseModel):
    """Стоимости из готового плана (в EUR)."""
    hotels_eur: float = Field(default=0.0, ge=0, description="Жильё за все ночи")
    activities_eur: float = Field(default=0.0, ge=0, description="Билеты, экскурсии, развлечения")
    transport_eur: float = Field(default=0.0, ge=0, description="Транспорт внутри и переезды")
    food_eur: float = Field(default=0.0, ge=0, description="Питание за всю поездку")


# ─────────────────────────────────────────────────────────────
# Хелперы форматирования
# ─────────────────────────────────────────────────────────────

def _format_request(request: dict[str, Any]) -> str:
    lines: list[str] = []
    cur = request.get("currency") or "EUR"
    if request.get("destination"):   lines.append(f"Куда: {request['destination']}")
    if request.get("country"):       lines.append(f"Страна: {request['country']}")
    if request.get("duration_days"): lines.append(f"Дней: {request['duration_days']}")
    if request.get("month"):         lines.append(f"Когда: {request['month']}")
    if request.get("budget"):        lines.append(f"Бюджет: {request['budget']} {cur}")
    if request.get("interests"):     lines.append(f"Интересы: {', '.join(request['interests'])}")
    if request.get("travel_type"):   lines.append(f"Тип: {request['travel_type']}")
    if request.get("constraints"):   lines.append(f"Ограничения: {'; '.join(request['constraints'])}")
    return "\n".join(lines) or "(запрос пустой)"


def _format_research(research: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, label in (
        ("attractions", "ДОСТОПРИМЕЧАТЕЛЬНОСТИ"),
        ("restaurants", "ЕДА"),
        ("rules", "ПРАВИЛА И ЛОГИСТИКА"),
    ):
        chunks = research.get(key) or []
        if not chunks:
            continue
        parts.append(f"### {label}")
        for i, c in enumerate(chunks, 1):
            content = (c.get("content") or "").strip()
            if content:
                parts.append(f"[{i}] {content}")
    return "\n".join(parts) if parts else "(База знаний пуста.)"


def _safe_content(response: Any) -> str:
    """LLM иногда возвращает не строку — приводим к строке."""
    content = getattr(response, "content", response)
    if not isinstance(content, str):
        content = str(content)
    return content.strip()


# ─────────────────────────────────────────────────────────────
# Генерация markdown
# ─────────────────────────────────────────────────────────────

async def _generate_markdown(state: AgentState) -> str:
    request = state.get("request") or {}
    research = state.get("research") or {}

    user_message = (
        "ЗАПРОС:\n" + _format_request(request) + "\n\n"
        "ДАННЫЕ:\n" + _format_research(research) + "\n\n"
        "Составь маршрут по правилам."
    )

    response = await get_llm().ainvoke([
        SystemMessage(content=PLAN_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])
    return _safe_content(response)


async def _regenerate_markdown(state: AgentState) -> str:
    old_markdown = (state.get("plan") or {}).get("markdown", "")
    report = state.get("budget_report") or {}
    request = state.get("request") or {}

    over = report.get("over_by", 0)
    limit = report.get("limit", 0)
    cur = request.get("currency") or "EUR"

    user_message = (
        f"Предыдущий план превысил бюджет на {over:.0f} {cur}.\n"
        f"Бюджет: {limit:.0f} {cur}.\n\n"
        f"Интересы: {', '.join(request.get('interests') or []) or '—'}\n"
        f"Ограничения: {'; '.join(request.get('constraints') or []) or '—'}\n\n"
        f"Исходный план:\n\n{old_markdown}\n\n"
        "Переработай план так, чтобы уложиться в бюджет. "
        "Сохрани структуру и строку <!-- BUDGET --> на месте."
    )

    response = await get_llm().ainvoke([
        SystemMessage(content=REPLAN_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])
    return _safe_content(response)


# ─────────────────────────────────────────────────────────────
# Извлечение стоимостей
# ─────────────────────────────────────────────────────────────

def _empty_costs() -> dict[str, float]:
    return {
        "hotels_eur": 0.0,
        "activities_eur": 0.0,
        "transport_eur": 0.0,
        "food_eur": 0.0,
    }


async def _extract_costs(markdown: str) -> dict[str, float]:
    """
    LLM извлекает суммы по 4 статьям из готового markdown.

    Особенности:
    - Обрезаем markdown до EXTRACT_MAX_CHARS — free-модели не тянут
      длинные промпты и падают с "Unsupported message type: <class 'ellipsis'>".
    - function_calling вместо json_schema — устойчивее.
    - Любая ошибка → возвращаем нули, чтобы граф не зацикливался.
    """
    if not markdown.strip():
        logger.warning("[costs] markdown пустой — возвращаю нули")
        return _empty_costs()

    snippet = markdown
    if len(snippet) > EXTRACT_MAX_CHARS:
        logger.warning(
            "[costs] markdown слишком длинный (%d симв.), обрезаю до %d",
            len(snippet), EXTRACT_MAX_CHARS,
        )
        snippet = snippet[:EXTRACT_MAX_CHARS]

    try:
        llm = get_llm().with_structured_output(CostExtract, method="function_calling")
        result = await llm.ainvoke([
            SystemMessage(content=(
                "Извлеки стоимости из плана поездки. Суммируй все статьи. "
                "Если чего-то не указано — верни 0. Будь точным."
            )),
            HumanMessage(content=snippet),
        ])
        if result is None:
            logger.warning("[costs] structured output вернул None")
            return _empty_costs()
        data = result.model_dump()
        total = sum(v for v in data.values())
        logger.info(
            "[costs] извлечено: %s, итого=%.0f",
            {k: round(v) for k, v in data.items()}, total,
        )
        return data
    except Exception as e:
        logger.warning("[costs] extraction failed: %s — возвращаю нули", e)
        return _empty_costs()


# ─────────────────────────────────────────────────────────────
# Узлы графа
# ─────────────────────────────────────────────────────────────

async def plan(state: AgentState) -> dict[str, Any]:
    """Первый проход: генерируем маршрут."""
    logger.info("[plan] старт первого прохода")

    markdown = await _generate_markdown(state)
    logger.info("[plan] markdown сгенерирован, %d символов", len(markdown))

    costs = await _extract_costs(markdown)
    total = sum(costs.values())
    logger.info("[plan] итоговая сумма: %.0f", total)

    return {
        "plan": {"markdown": markdown, "costs": costs},
        "replan_count": state.get("replan_count", 0),
        "max_replans": state.get("max_replans", 2),
    }


async def replan(state: AgentState) -> dict[str, Any]:
    """Повторный проход под бюджет."""
    old_plan = state.get("plan") or {}
    report = state.get("budget_report") or {}
    replan_count = state.get("replan_count", 0)
    attempt = replan_count + 1

    over = report.get("over_by", 0)
    total = report.get("total", 0)
    limit = report.get("limit", 0)
    cur = report.get("currency") or "EUR"

    logger.info(
        "[replan] попытка %d: было total=%.0f, limit=%.0f, over=%.0f %s",
        attempt, total, limit, over, cur,
    )

    if not old_plan.get("markdown"):
        logger.warning("[replan] предыдущий план пуст — нечего переделывать")
        return {"replan_count": attempt}

    markdown = await _regenerate_markdown(state)
    logger.info("[replan] новый markdown: %d символов", len(markdown))

    costs = await _extract_costs(markdown)
    new_total = sum(costs.values())
    logger.info("[replan] новые costs, итого=%.0f", new_total)

    return {
        "plan": {"markdown": markdown, "costs": costs},
        "replan_count": attempt,
    }