"""Генерация и перепланирование маршрута.

Важно: извлечение стоимости не должно подменять ошибку нулями. При неудаче
узел явно помечает стоимость как непроверенную, а budget_check завершает ветку
с предупреждением вместо ложного утверждения, что бюджет соблюдён.
"""

import logging
import math
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.agent.state import AgentState, Currency

logger = logging.getLogger(__name__)

PLAN_SYSTEM_PROMPT = """Ты — опытный travel-планировщик. Составляй подробный маршрут на русском языке в Markdown.

Правила:
1. Отвечай только готовым маршрутом, без вступительных фраз от ассистента.
2. Начни с '# Маршрут: <место>, <N> дней'. Сделай отдельные разделы по дням,
   жилью, транспорту и практическим советам.
3. Оставь строку <!-- BUDGET --> отдельной строкой: Python подставит туда отчёт.
4. Учитывай все ограничения пользователя. Не выдумывай конкретные факты из базы
   знаний; если цены/часы неизвестны, явно укажи, что их нужно уточнить.
5. Валюта пользователя указана в запросе. Не смешивай валюты в одном плане.
   Если цена в источнике указана в другой валюте и надёжного курса нет, не
   пересчитывай её наугад: укажи исходную валюту и отметь, что стоимость требует
   проверки. Не выдавай оценочные цены за подтверждённые цены.
6. Сохраняй ссылки/названия источников, если они переданы в данных.
"""

REPLAN_SYSTEM_PROMPT = """Переработай существующий маршрут, чтобы снизить расходы и по возможности уложиться в бюджет.
Сначала сокращай стоимость жилья и заменяй платные активности бесплатными.
Сохраняй число дней, интересы и все жёсткие ограничения. Не придумывай цены и
не пересчитывай валюты без курса. Оставь строку <!-- BUDGET --> на месте.
Верни только полный обновлённый маршрут в Markdown.
"""


class CostExtract(BaseModel):
    """Сумма расходов, извлечённая из всего маршрута.

    currency должна быть MIXED/UNKNOWN, если валюту нельзя определить
    однозначно или суммы в разных валютах нельзя корректно сложить.
    """
    hotels: float = Field(ge=0, description="Стоимость жилья за всю поездку")
    activities: float = Field(ge=0, description="Все билеты и активности за поездку")
    transport: float = Field(ge=0, description="Весь транспорт за поездку")
    food: float = Field(ge=0, description="Питание за всю поездку")
    currency: Literal["EUR", "USD", "RUB", "MIXED", "UNKNOWN"]
    complete: bool = Field(description="True, если оценка охватывает все категории; False, если существенные расходы неизвестны")
    notes: str = Field(default="", description="Краткое пояснение о неопределённых расходах")


_EMPTY_COSTS: dict[str, float] = {
    "hotels": 0.0,
    "activities": 0.0,
    "transport": 0.0,
    "food": 0.0,
}


def _format_request(request: dict[str, Any]) -> str:
    lines: list[str] = []
    currency = request.get("currency") or "EUR"
    if request.get("destination"):
        lines.append(f"Куда: {request['destination']}")
    if request.get("country"):
        lines.append(f"Страна: {request['country']}")
    if request.get("duration_days"):
        lines.append(f"Дней: {request['duration_days']}")
    if request.get("month"):
        lines.append(f"Когда: {request['month']}")
    if request.get("budget") is not None:
        lines.append(f"Бюджет: {request['budget']} {currency}")
    if request.get("interests"):
        lines.append(f"Интересы: {', '.join(request['interests'])}")
    if request.get("travel_type"):
        lines.append(f"Тип поездки: {request['travel_type']}")
    if request.get("constraints"):
        lines.append(f"Ограничения: {'; '.join(request['constraints'])}")
    return "\n".join(lines) or "(запрос пустой)"


def _format_research(research: dict[str, Any]) -> str:
    parts: list[str] = []
    sections = (
        ("attractions", "ДОСТОПРИМЕЧАТЕЛЬНОСТИ"),
        ("restaurants", "ЕДА И РЕСТОРАНЫ"),
        ("rules", "ПРАВИЛА И ЛОГИСТИКА"),
    )
    for key, label in sections:
        documents = research.get(key) or []
        if not documents:
            continue
        parts.append(f"### {label}")
        for index, document in enumerate(documents, 1):
            content = str(document.get("content") or "").strip()
            if not content:
                continue
            meta = document.get("meta") or {}
            doc_id = document.get("doc_id") or meta.get("source") or meta.get("url")
            score = document.get("score")
            suffix = f"; источник: {doc_id}" if doc_id else ""
            if isinstance(score, (int, float)):
                suffix += f"; релевантность: {score:.2f}"
            parts.append(f"[{index}{suffix}] {content}")
    return "\n".join(parts) if parts else "(В базе знаний нет подходящих документов.)"


def _safe_content(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts = [item.get("text", "") for item in content if isinstance(item, dict)]
        return "\n".join(part for part in text_parts if part).strip()
    return str(content).strip()


async def _generate_markdown(state: AgentState) -> str:
    request = state.get("request") or {}
    research = state.get("research") or {}
    user_message = (
        "ЗАПРОС ПОЛЬЗОВАТЕЛЯ:\n" + _format_request(request)
        + "\n\nДОКУМЕНТЫ БАЗЫ ЗНАНИЙ:\n" + _format_research(research)
        + "\n\nСоставь маршрут по правилам системного сообщения."
    )
    response = await get_llm().ainvoke([
        SystemMessage(content=PLAN_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])
    markdown = _safe_content(response)
    if not markdown:
        raise ValueError("LLM вернула пустой маршрут")
    return markdown


async def _regenerate_markdown(state: AgentState) -> str:
    old_plan = state.get("plan") or {}
    report = state.get("budget_report") or {}
    request = state.get("request") or {}
    currency = request.get("currency") or "EUR"
    over = report.get("over_by")
    limit = report.get("limit")
    if over is None or limit is None:
        raise ValueError("Нельзя перепланировать маршрут без проверенного отчёта о бюджете")

    user_message = (
        f"Бюджет: {limit:.2f} {currency}. Превышение: {over:.2f} {currency}.\n"
        f"Интересы: {', '.join(request.get('interests') or []) or '—'}\n"
        f"Ограничения: {'; '.join(request.get('constraints') or []) or '—'}\n\n"
        f"Исходный маршрут:\n{old_plan.get('markdown', '')}\n\n"
        "Верни полный переработанный маршрут."
    )
    response = await get_llm().ainvoke([
        SystemMessage(content=REPLAN_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])
    markdown = _safe_content(response)
    if not markdown:
        raise ValueError("LLM вернула пустой маршрут при перепланировании")
    return markdown


async def _extract_costs(markdown: str, currency: Currency) -> tuple[dict[str, float], str]:
    """Извлекает категории расходов. При ошибке выбрасывает исключение, не нули."""
    if not markdown.strip():
        raise ValueError("Нельзя извлечь расходы из пустого маршрута")
    llm = get_llm().with_structured_output(CostExtract, method="function_calling")
    result = await llm.ainvoke([
        SystemMessage(content=(
            "Извлеки общие расходы из ПОЛНОГО маршрута. Не считай одну цену дважды: "
            "цена за ночь умножается на число ночей только если число ночей известно; "
            "цена за человека умножается на число путешественников только если это явно "
            "указано. Если цена неизвестна, не выдумывай её и оценивай эту категорию как 0, "
            "но не скрывай неизвестность: currency=UNKNOWN. Если суммы разных валют "
            "нельзя корректно сложить, currency=MIXED. В поле currency укажи валюту "
            f"всех учтённых сумм; ожидаемая валюта бюджета: {currency}. "
            "Суммы должны охватывать весь маршрут, не только его начало. Поле complete=true "
            "только если по всем четырём категориям есть оценка или подтверждённый ноль "
            "(например, бесплатная активность); если существенная категория неизвестна, "
            "complete=false. Неизвестные расходы нельзя выдавать за ноль."
        )),
        HumanMessage(content=markdown),
    ])
    if not isinstance(result, CostExtract):
        result = CostExtract.model_validate(result)
    costs = {
        "hotels": float(result.hotels),
        "activities": float(result.activities),
        "transport": float(result.transport),
        "food": float(result.food),
    }
    if any(not math.isfinite(value) or value < 0 for value in costs.values()):
        raise ValueError("Извлечённые расходы содержат некорректные числа")
    if not result.complete:
        raise ValueError(result.notes or "В маршруте есть существенные расходы без оценки")
    return costs, result.currency


async def _make_plan(state: AgentState, *, is_replan: bool) -> dict[str, Any]:
    request = state.get("request") or {}
    currency: Currency = request.get("currency") or "EUR"  # type: ignore[assignment]
    markdown = await (_regenerate_markdown(state) if is_replan else _generate_markdown(state))

    # Нет лимита — нет смысла делать отдельный LLM-вызов ради суммы.
    if request.get("budget") is None:
        costs = dict(_EMPTY_COSTS)
        costs_valid: bool | None = None
        costs_currency = currency
        costs_error = None
    else:
        try:
            costs, costs_currency = await _extract_costs(markdown, currency)
            costs_valid = costs_currency == currency
            costs_error = None if costs_valid else (
                f"Валюту расходов определить однозначно нельзя или она не совпадает "
                f"с валютой бюджета ({currency}); определено: {costs_currency}."
            )
        except Exception as exc:
            logger.exception("Не удалось проверить стоимость маршрута")
            costs = dict(_EMPTY_COSTS)
            costs_valid = False
            costs_currency = "UNKNOWN"
            costs_error = "Не удалось надёжно извлечь расходы из маршрута. Повторите запрос позже."

    plan_data: dict[str, Any] = {
        "markdown": markdown,
        "costs": costs,
        "costs_valid": costs_valid,
        "costs_currency": costs_currency,
        "costs_error": costs_error,
    }
    result: dict[str, Any] = {"plan": plan_data}
    if not is_replan:
        result["replan_count"] = state.get("replan_count", 0)
        result["max_replans"] = state.get("max_replans", 2)
    else:
        result["replan_count"] = state.get("replan_count", 0) + 1
    logger.info(
        "[%s] маршрут создан; chars=%d; costs_valid=%s; currency=%s",
        "replan" if is_replan else "plan", len(markdown), costs_valid, costs_currency,
    )
    return result


async def plan(state: AgentState) -> dict[str, Any]:
    """Первичная генерация маршрута."""
    return await _make_plan(state, is_replan=False)


async def replan(state: AgentState) -> dict[str, Any]:
    """Перепланирование с ограниченным числом попыток."""
    return await _make_plan(state, is_replan=True)
