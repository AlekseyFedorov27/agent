"""Генерация и перепланирование маршрута.

Ключевые решения:
- Оценочные цены не считаются подтверждёнными: confidence передаётся в
  budget_check, где только confidence="exact" может дать окончательный
  вердикт о соответствии бюджету. Оценки показываются как ориентир.
- При отказе пользователя (plan_decision == "rejected") комментарий
  приоритетнее бюджета и **обновляет state.request** — иначе на
  следующей итерации LLM увидит старые duration_days/interests и
  откатится к исходному запросу.
"""

import json
import logging
import math
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.agent.state import AgentState, Currency

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Системные промпты
# --------------------------------------------------------------------------- #

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
   проверки.
6. Где это уместно, приводи **типовые ориентиры** по ценам (например: хостел
   25–45 €/чел/ночь, меню дня 12–15 €, метро 1,5–3 € за поездку) с явной
   пометкой, что это ориентир, а не подтверждённая цена. Это помогает
   пользователю оценить бюджет, не выдавая оценку за факт.
7. Сохраняй ссылки/названия источников, если они переданы в данных.
"""

REPLAN_SYSTEM_PROMPT = """Переработай существующий маршрут, чтобы снизить расходы и по возможности уложиться в бюджет.
Сначала сокращай стоимость жилья и заменяй платные активности бесплатными.
Сохраняй число дней, интересы и все жёсткие ограничения. Не придумывай цены и
не пересчитывай валюты без курса. Оставь строку <!-- BUDGET --> на месте.
Верни только полный обновлённый маршрут в Markdown.
"""

REVISION_SYSTEM_PROMPT = """Пользователь отклонил предыдущий маршрут и попросил доработать его.
Комментарий пользователя — приоритет №1, обязательно учти его.
Сохрани число дней, интересы и все жёсткие ограничения, которые пользователь
не просил менять.
Не придумывай цены и не пересчитывай валюты без надёжного курса.
Оставь строку <!-- BUDGET --> на месте.
Верни только полный обновлённый маршрут в Markdown.
"""

_EXTRACT_SYSTEM_PROMPT = """Ты извлекаешь стоимость поездки из маршрута на русском языке.

Правила:
1. Извлекай только цены, которые прямо указаны в маршруте или надёжно
   следуют из приведённых в нём расчётов. Не выдавай типовые цены за фактические.
2. Если для категории нет конкретной цены, допустима ориентировочная оценка
   только при наличии контекста о направлении, длительности и составе поездки.
   В поле notes перечисли все оценённые категории и допущения.
3. Значение 0 допустимо только если категория действительно бесплатна по тексту.
   «Нет данных» — это не ноль. Если невозможно обоснованно оценить расходы,
   укажи confidence="unknown"; не придумывай число ради заполнения поля.
4. confidence:
   - "exact"     — все категории рассчитаны по явно указанным ценам/суммам
   - "estimated" — все категории являются ориентировочными оценками
   - "partial"   — часть суммы подтверждена, часть является оценкой/неполна
   - "unknown"   — достоверная сумма или разумная оценка невозможна
5. Суммы должны охватывать весь маршрут, не только начало.
6. Если суммы разных валют нельзя корректно сложить — currency=MIXED.
7. Все суммы — за поездку целиком. Если неизвестно число путешественников,
   не делай вид, что рассчитана стоимость на всю группу; опиши это в notes.

Ожидаемая валюта бюджета: {currency}.
"""


# --------------------------------------------------------------------------- #
# Pydantic-модели для structured output
# --------------------------------------------------------------------------- #

class CostExtract(BaseModel):
    """Стоимость поездки; confidence обязательно отражает точность суммы."""

    hotels: float = Field(ge=0, description="Стоимость жилья за всю поездку")
    activities: float = Field(ge=0, description="Билеты и активности за всю поездку")
    transport: float = Field(ge=0, description="Транспорт за всю поездку, включая аэропорт")
    food: float = Field(ge=0, description="Питание за всю поездку")
    currency: Literal["EUR", "USD", "RUB", "MIXED", "UNKNOWN"]
    confidence: Literal["exact", "estimated", "partial", "unknown"] = "estimated"
    notes: str = Field(default="", description="Что оценено, а не прочитано")


class RequestPatch(BaseModel):
    """Изменения в параметрах поездки, извлечённые из комментария пользователя."""

    duration_days: int | None = Field(default=None, ge=1, le=365)
    month: str | None = None
    budget: float | None = Field(default=None, ge=0)
    interests: list[str] | None = None
    constraints: list[str] | None = None


_EMPTY_COSTS: dict[str, float] = {
    "hotels": 0.0,
    "activities": 0.0,
    "transport": 0.0,
    "food": 0.0,
}


# --------------------------------------------------------------------------- #
# Форматирование контекста
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Генерация markdown
# --------------------------------------------------------------------------- #

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
    """Пересобирает маршрут. Ветка выбирается по причине перепланирования."""
    old_plan = state.get("plan") or {}
    report = state.get("budget_report") or {}
    request = state.get("request") or {}
    currency = request.get("currency") or "EUR"
    plan_comment = state.get("plan_comment")
    is_rejection = state.get("plan_decision") == "rejected"

    interests = ", ".join(request.get("interests") or []) or "—"
    constraints = "; ".join(request.get("constraints") or []) or "—"

    if is_rejection:
        # Отказ пользователя: комментарий приоритетнее бюджета.
        system_prompt = REVISION_SYSTEM_PROMPT
        user_message = (
            "Пользователь отклонил предыдущий маршрут и просит доработать его.\n"
            f"Комментарий пользователя: {plan_comment or '(не указан)'}\n\n"
            f"Интересы: {interests}\n"
            f"Ограничения: {constraints}\n\n"
            f"Исходный маршрут:\n{old_plan.get('markdown', '')}\n\n"
            "Верни полный переработанный маршрут с учётом комментария."
        )
    else:
        # Автоматическое перепланирование из-за превышения бюджета.
        over = report.get("over_by")
        limit = report.get("limit")
        if over is None or limit is None:
            raise ValueError(
                "Нельзя перепланировать маршрут без проверенного отчёта о бюджете"
            )
        system_prompt = REPLAN_SYSTEM_PROMPT
        user_message = (
            f"Бюджет: {limit:.2f} {currency}. Превышение: {over:.2f} {currency}.\n"
            f"Интересы: {interests}\n"
            f"Ограничения: {constraints}\n\n"
            f"Исходный маршрут:\n{old_plan.get('markdown', '')}\n\n"
            "Верни полный переработанный маршрут."
        )

    response = await get_llm().ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ])
    markdown = _safe_content(response)
    if not markdown:
        raise ValueError("LLM вернула пустой маршрут при перепланировании")
    return markdown


# --------------------------------------------------------------------------- #
# Извлечение расходов
# --------------------------------------------------------------------------- #

async def _extract_costs(
    markdown: str, currency: Currency,
) -> tuple[dict[str, float], str, str, str]:
    """
    Возвращает (costs, currency, confidence, notes).

    В отличие от предыдущей версии, здесь нет «всё или ничего»: оценки
    допустимы, а их точность отражается в confidence. Исключение летит только
    при действительно некорректном ответе LLM (пустой markdown, отрицательные
    или NaN-числа).
    """
    if not markdown.strip():
        raise ValueError("Нельзя извлечь расходы из пустого маршрута")

    llm = get_llm().with_structured_output(CostExtract, method="function_calling")
    result = await llm.ainvoke([
        SystemMessage(content=_EXTRACT_SYSTEM_PROMPT.format(currency=currency)),
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
    if any(not math.isfinite(v) or v < 0 for v in costs.values()):
        raise ValueError("Извлечённые расходы содержат некорректные числа")
    return costs, result.currency, result.confidence, result.notes


# --------------------------------------------------------------------------- #
# Обновление request из комментария при отказе
# --------------------------------------------------------------------------- #

async def _apply_comment_to_request(
    request: dict[str, Any], comment: str | None,
) -> dict[str, Any]:
    """
    Извлекает изменения параметров поездки из комментария пользователя.

    Возвращает патч — только явно упомянутые поля. Ничего не додумывает.
    Список interests при наличии в патче заменяется целиком (чтобы «убери море»
    реально убирало «море» из интересов, а не мерджилось с ним).
    """
    if not comment or not comment.strip():
        return {}

    llm = get_llm().with_structured_output(RequestPatch, method="function_calling")
    patch = await llm.ainvoke([
        SystemMessage(content=(
            "Извлеки изменения в параметрах поездки из комментария пользователя. "
            "Заполни только те поля, которые явно упомянуты или прямо "
            "перефразированы. Не додумывай.\n"
            "Примеры:\n"
            "  'убери море'        → interests=['архитектура'] (если море было в списке), "
            "constraints=['без моря']\n"
            "  '9 дней вместо 7'   → duration_days=9\n"
            "  'бюджет 700 €'      → budget=700\n"
            "  'перенеси на июнь'  → month='июнь'\n"
            "Если поле не упоминалось — оставь None."
        )),
        HumanMessage(content=(
            f"Текущий запрос: {json.dumps(request, ensure_ascii=False)}\n"
            f"Комментарий пользователя: {comment}"
        )),
    ])
    if not isinstance(patch, RequestPatch):
        patch = RequestPatch.model_validate(patch)

    return {k: v for k, v in patch.model_dump().items() if v is not None}


# --------------------------------------------------------------------------- #
# Основной проход по состоянию
# --------------------------------------------------------------------------- #

async def _make_plan(state: AgentState, *, is_replan: bool) -> dict[str, Any]:
    """
    Готовит план. Счётчики (replan_count / plan_revision_count) здесь
    НЕ увеличиваются — это делает вызывающий код (plan / replan), потому что
    причина вызова известна только ему.
    """
    request = state.get("request") or {}
    currency: Currency = request.get("currency") or "EUR"  # type: ignore[assignment]

    markdown = await (
        _regenerate_markdown(state) if is_replan else _generate_markdown(state)
    )

    costs_confidence: str = "unknown"
    costs_notes = ""
    if request.get("budget") is None:
        # Без бюджета отдельный LLM-вызов ради суммы не нужен.
        costs = dict(_EMPTY_COSTS)
        costs_valid: bool | None = None
        costs_currency = currency
        costs_error = None
    else:
        try:
            costs, costs_currency, costs_confidence, costs_notes = await _extract_costs(
                markdown, currency,
            )

            # Три отдельные причины, три разных сообщения.
            if costs_confidence == "unknown":
                costs_valid = False
                costs_error = (
                    "Не удалось оценить стоимость маршрута — extractor вернул "
                    "confidence=unknown."
                )
            elif costs_currency == "MIXED":
                costs_valid = False
                costs_error = (
                    "В плане смешаны несколько валют — пересчёт без надёжного "
                    "курса невозможен."
                )
            elif costs_currency != currency:
                costs_valid = False
                costs_error = (
                    f"План составлен в {costs_currency}, а бюджет задан в {currency}. "
                    f"Система не пересчитывает валюты без надёжного курса. "
                    f"Укажите бюджет в {costs_currency} или явный курс — "
                    f"и повторите запрос."
                )
            else:
                costs_valid = True
                costs_error = None
        except Exception:
            logger.exception("Не удалось извлечь расходы из маршрута")
            costs = dict(_EMPTY_COSTS)
            costs_valid = False
            costs_currency = "UNKNOWN"
            costs_confidence = "unknown"
            costs_notes = ""
            costs_error = (
                "Не удалось извлечь расходы из маршрута. Повторите запрос позже."
            )

    plan_data: dict[str, Any] = {
        "markdown": markdown,
        "costs": costs,
        "costs_valid": costs_valid,
        "costs_currency": costs_currency,
        "costs_confidence": costs_confidence,
        "costs_notes": costs_notes,
        "costs_error": costs_error,
    }

    logger.info(
        "[%s] маршрут создан; chars=%d; costs_valid=%s; currency=%s; confidence=%s",
        "replan" if is_replan else "plan",
        len(markdown),
        costs_valid,
        costs_currency,
        costs_confidence,
    )
    return {"plan": plan_data}

async def plan(state: AgentState) -> dict[str, Any]:
    """Первичная генерация маршрута."""
    return await _make_plan(state, is_replan=False)


async def replan(state: AgentState) -> dict[str, Any]:
    """
    Перепланирование. Две разные причины → два разных счётчика.

    - Budget replan (auto): replan_count += 1, max=2. Смысл — не крутить
      граф бесконечно на over_budget.
    - User revision (reject): plan_revision_count += 1, max=5. Смысл —
      дать пользователю нормальное число итераций доработки.

    Флаги plan_decision / plan_comment сбрасываются после прохода,
    иначе следующий автоматический replan (по бюджету) ошибочно уйдёт
    в revision-ветку.
    """
    is_rejection = state.get("plan_decision") == "rejected"

    request = dict(state.get("request") or {})
    if is_rejection:
        try:
            patch = await _apply_comment_to_request(
                request, state.get("plan_comment"),
            )
        except Exception:
            logger.exception("Не удалось извлечь патч из комментария пользователя")
            patch = {}

        if patch:
            # interests заменяем целиком, а не мерджим — иначе «убери море»
            # не сработает.
            if "interests" in patch:
                request["interests"] = patch.pop("interests")
            request.update(patch)
            logger.info("Request обновлён по комментарию: %s", request)

    working_state: AgentState = {**state, "request": request}  # type: ignore[assignment]
    result = await _make_plan(working_state, is_replan=True)

    # --- Счётчики: разные для разных причин ---
    if is_rejection:
        result["plan_revision_count"] = state.get("plan_revision_count", 0) + 1
        # replan_count не трогаем — он про бюджет
    else:
        result["replan_count"] = state.get("replan_count", 0) + 1
        # plan_revision_count не трогаем

    # --- Обновляем request только при user rejection ---
    if is_rejection:
        result["request"] = request

    result["plan_decision"] = None
    result["plan_comment"] = None
    return result
