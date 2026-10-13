"""Извлекает структуру поездки из последнего сообщения пользователя."""

import json
import logging
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from app.agent.llm import get_llm
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


class Triage(BaseModel):
    currency: Literal["EUR", "USD", "RUB"] | None = None
    destination: str | None = Field(default=None, description="Город или страна назначения")
    country: str | None = Field(default=None, description="Страна на русском языке")
    duration_days: int | None = Field(default=None, ge=1, le=365)
    month: str | None = None
    budget: float | None = Field(default=None, ge=0, le=1_000_000_000)
    interests: list[str] = Field(default_factory=list)
    travel_type: Literal["solo", "family", "couple", "business"] | None = None
    constraints: list[str] = Field(default_factory=list)

    @field_validator("destination", "country", "month")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("interests", "constraints")
    @classmethod
    def clean_string_lists(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


REQUIRED_FIELDS = ["destination", "duration_days", "month"]

NEW_REQUEST_PROMPT = """Ты извлекаешь параметры новой поездки из ОДНОГО последнего сообщения.
Верни структурированные поля: currency (EUR/USD/RUB или null), destination, country
(страна на русском, если можно определить), duration_days (1..365), month, budget,
interests, travel_type (solo/family/couple/business), constraints.
Не выдумывай значения и не переноси их из старой истории. Если пользователь назвал
город, укажи страну только если уверен. Валюта по умолчанию будет выбрана приложением.
Интересы — предпочтения; constraints — жёсткие ограничения.
"""

CLARIFICATION_PROMPT = """Ты извлекаешь только параметры, которые пользователь сообщил в ответе
на уточняющий вопрос. Не повторяй уже известные значения: для неупомянутых полей
верни null или пустые списки. Не додумывай информацию.
"""


class TriageExtractionError(RuntimeError):
    """Обе стратегии структурированного извлечения не сработали."""


def _last_human_message(messages: list[Any]) -> str:
    for message in reversed(messages):
        if getattr(message, "type", "") == "human":
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


async def _safe_triage(messages: list[Any]) -> Triage:
    """Пробует два режима structured output; ошибки не маскируются пустой схемой."""
    llm = get_llm()
    errors: list[str] = []
    for method in ("json_schema", "function_calling"):
        try:
            result = await llm.with_structured_output(Triage, method=method).ainvoke(messages)
            if isinstance(result, Triage):
                logger.debug("Triage structured output успешен: %s", method)
                return result
            return Triage.model_validate(result)
        except Exception as exc:
            logger.warning("Triage structured output %s завершился ошибкой", method, exc_info=True)
            errors.append(f"{method}: {type(exc).__name__}")
    raise TriageExtractionError(
        "Не удалось разобрать запрос пользователя структурированно (" + ", ".join(errors) + ")"
    )


def _merge_request(previous: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Новое непустое значение заменяет старое; пустые поля уточнения игнорируются."""
    merged = dict(previous)
    for key, value in new.items():
        if value is not None and value != "" and value != []:
            merged[key] = value
    return merged


async def triage(state: AgentState) -> dict[str, Any]:
    messages = state.get("messages") or []
    last_human = _last_human_message(messages)
    if not last_human.strip():
        return {
            "request": {},
            "missing_fields": REQUIRED_FIELDS.copy(),
            "research": {"attractions": [], "restaurants": [], "rules": []},
            "plan": None,
            "budget_report": None,
            "final_itinerary": None,
            "triage_error": "В сообщениях нет текста пользователя.",
            "replan_count": 0,
            "max_replans": 2,
        }

    previous_request = state.get("request") or {}
    previous_missing = state.get("missing_fields") or []
    is_clarification = bool(previous_missing and previous_request)

    if is_clarification:
        prompt = (
            f"Известный запрос: {json.dumps(previous_request, ensure_ascii=False)}\n"
            f"Недостающие поля: {', '.join(previous_missing)}\n"
            f"Ответ пользователя: {last_human}"
        )
        extracted = await _safe_triage([
            SystemMessage(content=CLARIFICATION_PROMPT),
            HumanMessage(content=prompt),
        ])
        request = _merge_request(previous_request, extracted.model_dump())
    else:
        extracted = await _safe_triage([
            SystemMessage(content=NEW_REQUEST_PROMPT),
            HumanMessage(content=last_human),
        ])
        request = extracted.model_dump()
        if not request.get("currency"):
            request["currency"] = "EUR"

    # Валюта имеет значение только вместе с бюджетом, но фиксируем единый default.
    request.setdefault("currency", "EUR")
    missing = [field for field in REQUIRED_FIELDS if request.get(field) in (None, "", [])]
    logger.info(
        "Triage завершён: destination=%r, days=%r, month=%r, missing=%s, mode=%s",
        request.get("destination"), request.get("duration_days"), request.get("month"),
        missing, "clarification" if is_clarification else "new",
    )
    return {
        "request": request,
        "missing_fields": missing,
        "research": {"attractions": [], "restaurants": [], "rules": []},
        "plan": None,
        "budget_report": None,
        "final_itinerary": None,
        "triage_error": None,
        "replan_count": 0,
        "max_replans": 2,
    }
