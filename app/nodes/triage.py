"""
Узел triage: разбирает текст пользователя в структурированный Request.

Особенности:
- Извлекает `destination` (город/страна) и `country` (страна на русском).
- Смотрит ТОЛЬКО на последнее human-сообщение, а не на всю историю.
  Контекст предыдущего запроса берётся из state.request и state.missing_fields.
- Устойчив к пустым/битым ответам LLM: json_schema → function_calling → fallback.
- При новом запросе сбрасывает transient-поля (research, plan, budget_report).
"""

import json
import logging
from typing import Any, Literal

from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.agent.state import AgentState


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Схема
# ─────────────────────────────────────────────────────────────

class Triage(BaseModel):
    currency: Literal["EUR", "USD", "RUB"] | None = Field(default=None)

    destination: str | None = Field(
        default=None,
        description="Город или страна. Как пользователь сказал: 'Барселона', 'Испания'.",
    )
    country: str | None = Field(
        default=None,
        description=(
            "Страна на русском: 'Испания', 'Франция', 'Италия', 'Португалия'. "
            "Если пользователь назвал город — определи страну сам. "
            "Если назвал страну — продублируй её сюда."
        ),
    )

    duration_days: int | None = Field(default=None)
    month: str | None = Field(default=None)
    budget: float | None = Field(default=None)
    interests: list[str] = Field(default_factory=list)
    travel_type: Literal["solo", "family", "couple", "business"] | None = Field(default=None)
    constraints: list[str] = Field(default_factory=list)


REQUIRED_FIELDS = ["destination", "duration_days", "month"]


# ─────────────────────────────────────────────────────────────
# Промпты
# ─────────────────────────────────────────────────────────────

NEW_REQUEST_PROMPT = """Ты — извлекатель данных о поездке. Пользователь начинает
НОВЫЙ разговор о поездке. Читай ТОЛЬКО его последнее сообщение и заполняй схему.

СХЕМА:
{
  "currency": "EUR" | "USD" | "RUB" | null,
  "destination": строка или null,     // город ИЛИ страна, как сказал пользователь
  "country": строка или null,         // страна на русском, всегда указывай
  "duration_days": число или null,
  "month": строка или null,
  "budget": число или null,
  "interests": [строки],
  "travel_type": "solo" | "family" | "couple" | "business" | null,
  "constraints": [строки]
}

ПРАВИЛА:
1. Заполняй ТОЛЬКО тем, что есть в последнем сообщении пользователя.
   Если пользователь не назвал город/страну — destination=null, country=null.
   НЕ ДОДУМЫВАЙ и НЕ БЕРИ из предыдущих сообщений.

2. Поле `country` — ВСЕГДА заполняй, если можешь определить страну.
   "Барселона" → destination="Барселона", country="Испания"
   "Испания" → destination="Испания", country="Испания"
   "Париж" → destination="Париж", country="Франция"
   "куда-нибудь в Европу" → destination=null, country=null

3. Ограничения (constraints) — жёсткие запреты и требования:
   "без ранних подъёмов", "без ночных клубов", "не хочу переезжать каждый день".

4. Интересы (interests) — короткими словами: "архитектура", "море", "тапас",
   "сёрф", "музеи", "винодельни".

5. Если чего-то нет — null или [].

ПРИМЕР:
Вход: "Хочу неделю в Барселоне в сентябре. Нас двое, бюджет 1800 €.
       Интересует архитектура Гауди, море и тапас-бары.
       Ранние подъёмы — не мой вариант, хочу вставать к 10."
Выход: {
  "currency": "EUR", "destination": "Барселона", "country": "Испания",
  "duration_days": 7, "month": "сентябрь", "budget": 1800.0,
  "interests": ["архитектура", "Гауди", "море", "тапас"],
  "travel_type": "couple",
  "constraints": ["без ранних подъёмов"]
}

ПРИМЕР (неполный запрос):
Вход: "Куда-нибудь в Европу летом"
Выход: {
  "currency": null, "destination": null, "country": null,
  "duration_days": null, "month": "лето", "budget": null,
  "interests": [], "travel_type": null, "constraints": []
}
"""


CLARIFICATION_PROMPT = """Ты — извлекатель данных о поездке. Пользователь
ранее начал планировать поездку, но чего-то не хватало, и ассистент задал
уточняющий вопрос. Теперь пользователь отвечает на этот вопрос.

СХЕМА:
{
  "currency": "EUR" | "USD" | "RUB" | null,
  "destination": строка или null,
  "country": строка или null,
  "duration_days": число или null,
  "month": строка или null,
  "budget": число или null,
  "interests": [строки],
  "travel_type": "solo" | "family" | "couple" | "business" | null,
  "constraints": [строки]
}

Извлекай ТОЛЬКО те поля, которые упомянуты в ответе пользователя.
Остальные оставь null / []. НЕ ПОВТОРЯЙ значения из истории — их
подставит система.

ПРИМЕР:
Предыдущий запрос: {"destination": "Барселона", "country": "Испания", ...}
Не хватало: duration_days
Новое сообщение: "16 дней"
Выход: {
  "currency": null, "destination": null, "country": null,
  "duration_days": 16, "month": null, "budget": null,
  "interests": [], "travel_type": null, "constraints": []
}
"""


# ─────────────────────────────────────────────────────────────
# Хелперы
# ─────────────────────────────────────────────────────────────

def _last_human_message(messages: list) -> str:
    """Возвращает текст последнего human-сообщения."""
    for m in reversed(messages):
        if getattr(m, "type", "") == "human":
            return m.content if isinstance(m.content, str) else str(m.content)
    return ""


def _safe_triage(messages: list) -> Triage:
    """json_schema → function_calling → пустой fallback."""
    llm = get_llm()

    try:
        result = llm.with_structured_output(Triage, method="json_schema").invoke(messages)
        if isinstance(result, Triage):
            logger.info("[triage] json_schema OK")
            return result
    except Exception as e:
        logger.warning("[triage] json_schema failed: %s", e)

    try:
        result = llm.with_structured_output(Triage, method="function_calling").invoke(messages)
        if isinstance(result, Triage):
            logger.info("[triage] function_calling OK")
            return result
    except Exception as e:
        logger.warning("[triage] function_calling failed: %s", e)

    logger.error("[triage] all attempts failed, returning empty Triage")
    return Triage()


def _merge_request(prev: dict, new: dict) -> dict:
    """Мержит новый request со старым: новое перекрывает старое, если непусто."""
    merged = dict(prev)
    for k, v in new.items():
        if v not in (None, "", []):
            merged[k] = v
    return merged


# ─────────────────────────────────────────────────────────────
# Узел
# ─────────────────────────────────────────────────────────────

def triage(state: AgentState) -> dict[str, Any]:
    messages = state.get("messages") or []
    last_human = _last_human_message(messages)

    if not last_human.strip():
        logger.warning("[triage] последнее human-сообщение пустое")
        return {
            "request": {},
            "missing_fields": REQUIRED_FIELDS,
            "research": {"attractions": [], "restaurants": [], "rules": []},
            "plan": None,
            "budget_report": None,
            "final_itinerary": None,
            "replan_count": 0,
            "max_replans": 2,
        }

    prev_request = state.get("request") or {}
    prev_missing = state.get("missing_fields") or []

    # Различаем: это уточнение к старому запросу или новый запрос?
    is_clarification = bool(prev_missing) and bool(prev_request)

    if is_clarification:
        # Это ответ на ask_user. Смотрим, чего не хватало, и извлекаем только это.
        logger.info("[triage] режим уточнения, не хватало: %s", prev_missing)

        hint = (
            f"Предыдущий запрос: {json.dumps(prev_request, ensure_ascii=False)}\n"
            f"Не хватало полей: {', '.join(prev_missing)}\n\n"
            f"Новое сообщение пользователя: {last_human!r}"
        )
        result = _safe_triage([
            SystemMessage(content=CLARIFICATION_PROMPT),
            ("human", hint),
        ])
        request = _merge_request(prev_request, result.model_dump())
    else:
        # Это новый запрос. Смотрим ТОЛЬКО на последнее сообщение.
        logger.info("[triage] режим нового запроса")

        result = _safe_triage([
            SystemMessage(content=NEW_REQUEST_PROMPT),
            ("human", last_human),
        ])
        request = result.model_dump()

    missing = [
        f for f in REQUIRED_FIELDS
        if request.get(f) in (None, "", [])
    ]

    logger.info(
        "[triage] destination=%r country=%r days=%s month=%r budget=%s missing=%s mode=%s",
        request.get("destination"),
        request.get("country"),
        request.get("duration_days"),
        request.get("month"),
        request.get("budget"),
        missing,
        "clarification" if is_clarification else "new",
    )

    return {
        "request": request,
        "missing_fields": missing,
        # При новом запросе — сбрасываем весь transient-контекст.
        # При уточнении — тоже сбрасываем, чтобы не тащить старый research;
        # research всё равно перезапишется в следующем узле.
        "research": {"attractions": [], "restaurants": [], "rules": []},
        "plan": None,
        "budget_report": None,
        "final_itinerary": None,
        "replan_count": 0,
        "max_replans": 2,
    }