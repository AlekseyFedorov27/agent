"""Генерация и перепланирование маршрута.

- Оценочные цены не считаются подтверждёнными: plan только извлекает costs и
  confidence, а вердикт выносит budget_check.
- При отказе пользователя комментарий приоритетнее бюджета и обновляет
  state.request, иначе следующая итерация откатится к исходному запросу.
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
# Промпты
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
6. Где уместно, приводи типовые ориентиры по ценам (например: хостел
   25–45 €/чел/ночь, меню дня 12–15 €) с явной пометкой, что это ориентир,
   а не подтверждённая цена.
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
   «Нет данных» — это не ноль. Если разумно оценить расходы невозможно,
   укажи confidence="unknown"; не придумывай число ради заполнения поля.
4. confidence:
   - "exact"     — все категории рассчитаны по явно указанным ценам/суммам
   - "estimated" — все категории являются ориентировочными оценками
   - "partial"   — часть суммы подтверждена, часть является оценкой/неполна
   - "unknown"   — достоверная сумма или разумная оценка невозможна
5. Суммы должны охватывать весь маршрут, не только начало.
6. Если суммы разных валют нельзя корректно сложить — currency=MIXED.
7. Все суммы — за поездку целиком. Если неизвестно число путешественников,
   опиши это в notes.

Ожидаемая валюта бюджета: {currency}.
"""

_PATCH_SYSTEM_PROMPT = (
    "Извлеки изменения в параметрах поездки из комментария пользователя. "
    "Заполни только те поля, которые явно упомянуты. Не додумывай.\n"
    "Примеры:\n"
    "  '9 дней вместо 7'   → duration_days=9\n"
    "  'бюджет 700 €'      → budget=700\n"
    "  'перенеси на июнь'  → month='июнь'\n"
    "  'без музеев'        → constraints=['без музеев']\n"
    "Если поле не упоминалось — оставь None."
)


# --------------------------------------------------------------------------- #
# Модели structured output
# --------------------------------------------------------------------------- #

class CostExtract(BaseModel):
    hotels: float = Field(ge=0, description="Стоимость жилья за всю поездку")
    activities: float = Field(ge=0, description="Билеты и активности за всю поездку")
    transport: float = Field(ge=0, description="Транспорт за всю поездку, включая аэропорт")
    food: float = Field(ge=0, description="Питание за всю поездку")
    currency: Literal["EUR", "USD", "RUB", "MIXED", "UNKNOWN"]
    confidence: Literal["exact", "estimated", "partial", "unknown"] = "estimated"
    notes: str = Field(default="", description="Что оценено, а не прочитано")


class RequestPatch(BaseModel):
    duration_days: int | None = Field(default=None, ge=1, le=365)
    month: str | None = None
    budget: float | None = Field(default=None, ge=0)
    interests: list[str] | None = None
    constraints: list[str] | None = None


_EMPTY_COSTS: dict[str, float] = {"hotels": 0.0, "activities": 0.0, "transport": 0.0, "food": 0.0}


# --------------------------------------------------------------------------- #
# Форматирование контекста
# --------------------------------------------------------------------------- #

def _format_request(request: dict[str, Any]) -> str:
    currency = request.get("currency") or "EUR"
    fields = (
        ("Куда", request.get("destination")),
        ("Страна", request.get("country")),
        ("Дней", request.get("duration_days")),
        ("Когда", request.get("month")),
        ("Бюджет", f"{request['budget']} {currency}" if request.get("budget") is not None else None),
        ("Интересы", ", ".join(request.get("interests") or [])),
        ("Тип поездки", request.get("travel_type")),
        ("Ограничения", "; ".join(request.get("constraints") or [])),
    )
    return "\n".join(f"{label}: {value}" for label, value in fields if value) or "(запрос пустой)"


def _format_research(research: dict[str, Any]) -> str:
    sections = (
        ("attractions", "ДОСТОПРИМЕЧАТЕЛЬНОСТИ"),
        ("restaurants", "ЕДА И РЕСТОРАНЫ"),
        ("rules", "ПРАВИЛА И ЛОГИСТИКА"),
    )
    parts: list[str] = []
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
            source = document.get("doc_id") or meta.get("source") or meta.get("url")
            suffix = f"; источник: {source}" if source else ""
            parts.append(f"[{index}{suffix}] {content}")
    return "\n".join(parts) or "(В базе знаний нет подходящих документов.)"


def _safe_content(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = [item.get("text", "") for item in content if isinstance(item, dict)]
        return "\n".join(t for t in texts if t).strip()
    return str(content).strip()


# --------------------------------------------------------------------------- #
# Генерация markdown
# --------------------------------------------------------------------------- #

async def _generate_markdown(state: AgentState, *, is_replan: bool) -> str:
    request = state.get("request") or {}
    old_markdown = (state.get("plan") or {}).get("markdown", "")
    currency = request.get("currency") or "EUR"
    interests = ", ".join(request.get("interests") or []) or "—"
    constraints = "; ".join(request.get("constraints") or []) or "—"

    if not is_replan:
        system_prompt = PLAN_SYSTEM_PROMPT
        user_message = (
            "ЗАПРОС ПОЛЬЗОВАТЕЛЯ:\n" + _format_request(request)
            + "\n\nДОКУМЕНТЫ БАЗЫ ЗНАНИЙ:\n" + _format_research(state.get("research") or {})
            + "\n\nСоставь маршрут по правилам системного сообщения."
        )
    elif state.get("plan_decision") == "rejected":
        system_prompt = REVISION_SYSTEM_PROMPT
        user_message = (
            f"Комментарий пользователя: {state.get('plan_comment') or '(не указан)'}\n\n"
            f"Интересы: {interests}\nОграничения: {constraints}\n\n"
            f"Исходный маршрут:\n{old_markdown}\n\n"
            "Верни полный переработанный маршрут с учётом комментария."
        )
    else:
        report = state.get("budget_report") or {}
        over, limit = report.get("over_by"), report.get("limit")
        if over is None or limit is None:
            raise ValueError("Нельзя перепланировать маршрут без проверенного отчёта о бюджете")
        system_prompt = REPLAN_SYSTEM_PROMPT
        user_message = (
            f"Бюджет: {limit:.2f} {currency}. Превышение: {over:.2f} {currency}.\n"
            f"Интересы: {interests}\nОграничения: {constraints}\n\n"
            f"Исходный маршрут:\n{old_markdown}\n\n"
            "Верни полный переработанный маршрут."
        )

    response = await get_llm().ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ])
    markdown = _safe_content(response)
    if not markdown:
        raise ValueError("LLM вернула пустой маршрут")
    return markdown


# --------------------------------------------------------------------------- #
# Извлечение расходов и патч запроса
# --------------------------------------------------------------------------- #

async def _extract_costs(markdown: str, currency: Currency) -> tuple[dict[str, float], str, str, str]:
    """Возвращает (costs, currency, confidence, notes)."""
    llm = get_llm().with_structured_output(CostExtract, method="function_calling")
    result = await llm.ainvoke([
        SystemMessage(content=_EXTRACT_SYSTEM_PROMPT.format(currency=currency)),
        HumanMessage(content=markdown),
    ])
    if not isinstance(result, CostExtract):
        result = CostExtract.model_validate(result)

    costs = {k: float(getattr(result, k)) for k in _EMPTY_COSTS}
    if not all(math.isfinite(v) for v in costs.values()):
        raise ValueError("Извлечённые расходы содержат некорректные числа")
    return costs, result.currency, result.confidence, result.notes


async def _patch_request(request: dict[str, Any], comment: str | None) -> dict[str, Any]:
    """Возвращает только явно упомянутые в комментарии поля. При ошибке — {}."""
    if not comment or not comment.strip():
        return {}
    try:
        llm = get_llm().with_structured_output(RequestPatch, method="function_calling")
        patch = await llm.ainvoke([
            SystemMessage(content=_PATCH_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"Текущий запрос: {json.dumps(request, ensure_ascii=False)}\n"
                f"Комментарий пользователя: {comment}"
            )),
        ])
        if not isinstance(patch, RequestPatch):
            patch = RequestPatch.model_validate(patch)
    except Exception:
        logger.exception("Не удалось извлечь патч из комментария пользователя")
        return {}
    return {k: v for k, v in patch.model_dump().items() if v is not None}


# --------------------------------------------------------------------------- #
# Узлы графа
# --------------------------------------------------------------------------- #

async def _make_plan(state: AgentState, *, is_replan: bool) -> dict[str, Any]:
    request = state.get("request") or {}
    currency: Currency = request.get("currency") or "EUR"  # type: ignore[assignment]

    markdown = await _generate_markdown(state, is_replan=is_replan)

    costs, costs_currency, confidence, notes = dict(_EMPTY_COSTS), "UNKNOWN", "unknown", ""
    if request.get("budget") is not None:  # без бюджета лишний LLM-вызов не нужен
        try:
            costs, costs_currency, confidence, notes = await _extract_costs(markdown, currency)
        except Exception:
            logger.exception("Не удалось извлечь расходы из маршрута")

    logger.info(
        "[%s] маршрут создан; chars=%d; currency=%s; confidence=%s",
        "replan" if is_replan else "plan", len(markdown), costs_currency, confidence,
    )
    return {"plan": {
        "markdown": markdown,
        "costs": costs,
        "costs_currency": costs_currency,
        "costs_confidence": confidence,
        "costs_notes": notes,
    }}


async def plan(state: AgentState) -> dict[str, Any]:
    """Первичная генерация маршрута."""
    return await _make_plan(state, is_replan=False)


async def replan(state: AgentState) -> dict[str, Any]:
    """
    Перепланирование. Две причины — два счётчика:
    - отказ пользователя: plan_revision_count += 1 (и обновление request);
    - превышение бюджета: replan_count += 1.
    Флаги plan_decision / plan_comment сбрасываются, чтобы следующий
    авто-replan по бюджету не ушёл в ветку отказа.
    """
    is_rejection = state.get("plan_decision") == "rejected"

    request = dict(state.get("request") or {})
    if is_rejection:
        request.update(await _patch_request(request, state.get("plan_comment")))

    result = await _make_plan({**state, "request": request}, is_replan=True)  # type: ignore[typeddict-item]

    if is_rejection:
        result["plan_revision_count"] = state.get("plan_revision_count", 0) + 1
        result["request"] = request
    else:
        result["replan_count"] = state.get("replan_count", 0) + 1

    result["plan_decision"] = None
    result["plan_comment"] = None
    return result