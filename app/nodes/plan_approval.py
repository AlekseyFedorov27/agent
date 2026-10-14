"""Human-in-the-loop: запрос подтверждения маршрута у пользователя."""

import logging
from typing import Any

from langgraph.types import interrupt

from app.agent.state import AgentState

logger = logging.getLogger(__name__)


def plan_approval(state: AgentState) -> dict[str, Any]:
    """Останавливает граф и передаёт фронтенду план вместе с отчётом бюджета."""
    plan = state.get("plan") or {}
    budget_report = state.get("budget_report") or {}
    request = state.get("request") or {}
    plan_markdown = state.get("final_itinerary") or plan.get("markdown") or ""

    decision = interrupt({
        "type": "plan_approval",
        "plan_markdown": plan_markdown,
        "budget_report": budget_report,
        "request": request,
    })

    if isinstance(decision, dict):
        # Не используем bool(value): bool("false") == True.
        approved = decision.get("approved") is True
        comment_value = decision.get("comment")
        comment = comment_value.strip() if isinstance(comment_value, str) else None
    else:
        approved = decision is True
        comment = None

    if approved:
        logger.info("Пользователь подтвердил маршрут")
        return {"plan_decision": "approved", "plan_comment": None}

    logger.info("Пользователь отклонил маршрут")
    return {"plan_decision": "rejected", "plan_comment": comment or None}


def route_after_plan_approval(state: AgentState) -> str:
    """Ограничивает число пользовательских доработок независимо от budget replan."""
    if state.get("plan_decision") == "approved":
        return "end"

    revisions = state.get("plan_revision_count", 0)
    max_revisions = state.get("max_plan_revisions", 5)
    if revisions >= max_revisions:
        logger.warning(
            "plan_revision_count=%d >= max_plan_revisions=%d — завершаем",
            revisions, max_revisions,
        )
        return "end"
    return "replan"
