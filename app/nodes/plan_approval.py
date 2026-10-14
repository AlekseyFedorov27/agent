"""Human-in-the-loop: запрос подтверждения маршрута у пользователя."""

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from app.agent.state import AgentState

logger = logging.getLogger(__name__)


def plan_approval(state: AgentState) -> dict[str, Any]:
    """Останавливает граф и передаёт фронтенду план вместе с отчётом бюджета."""
    plan = state.get("plan") or {}
    plan_markdown = state.get("final_itinerary") or plan.get("markdown") or ""

    decision = interrupt({
        "type": "plan_approval",
        "plan_markdown": plan_markdown,
        "budget_report": state.get("budget_report") or {},
        "request": state.get("request") or {},
    })

    # Не используем bool(value): bool("false") == True.
    if isinstance(decision, dict):
        approved = decision.get("approved") is True
        raw_comment = decision.get("comment")
        comment = raw_comment.strip() if isinstance(raw_comment, str) else ""
    else:
        approved = decision is True
        comment = ""

    logger.info("Пользователь %s маршрут", "подтвердил" if approved else "отклонил")
    return {
        # Сообщение добавляется здесь, после interrupt, чтобы не дублироваться при resume.
        "messages": [AIMessage(content=plan_markdown)],
        "plan_decision": "approved" if approved else "rejected",
        "plan_comment": None if approved else (comment or None),
    }


def route_after_plan_approval(state: AgentState) -> str:
    """Ограничивает число пользовательских доработок независимо от budget replan."""
    if state.get("plan_decision") == "approved":
        return "end"

    revisions = state.get("plan_revision_count", 0)
    max_revisions = state.get("max_plan_revisions", 5)
    if revisions >= max_revisions:
        logger.warning("plan_revision_count=%d >= max_plan_revisions=%d — завершаем",
                       revisions, max_revisions)
        return "end"
    return "replan"