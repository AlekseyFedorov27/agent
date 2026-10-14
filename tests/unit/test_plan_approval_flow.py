"""Тесты маршрутизации HITL-цикла вокруг плана.

Проверяем то, что ломалось: разделение счётчиков budget-replan и
user-revision, чтобы второй reject не уходил в END, а пересчитывал план.
LLM и БД здесь не нужны — только чистые функции маршрутизации и replan
с моками внешних зависимостей.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.state import AgentState
from app.nodes.plan import replan, _make_plan
from app.nodes.budget_check import route_after_budget
from app.nodes.plan_approval import route_after_plan_approval


# --------------------------------------------------------------------------- #
# route_after_plan_approval
# --------------------------------------------------------------------------- #

def _state(**overrides) -> AgentState:
    """Дефолтный state с полями, которые читает роутер."""
    base: AgentState = {
        "plan_decision": None,
        "plan_revision_count": 0,
        "max_plan_revisions": 5,
        "replan_count": 0,
        "max_replans": 2,
    }
    base.update(overrides)
    return base


def test_approve_always_ends():
    """Approve уходит в END независимо от счётчиков."""
    state = _state(
        plan_decision="approved",
        plan_revision_count=99,
        replan_count=99,
    )
    assert route_after_plan_approval(state) == "end"


def test_first_reject_goes_to_replan():
    """Первый reject — дорабатываем, счётчик маленький."""
    state = _state(plan_decision="rejected", plan_revision_count=0)
    assert route_after_plan_approval(state) == "replan"


def test_second_reject_still_goes_to_replan():
    """
    Регрессия: раньше здесь смотрели replan_count, и после первого
    auto-replan (replan_count=1) + первого reject (replan_count=2)
    второй reject попадал на лимит и уходил в END. Теперь маршрут
    смотрит на plan_revision_count, который не тратится бюджетным циклом.
    """
    state = _state(
        plan_decision="rejected",
        replan_count=2,          # бюджетный счётчик исчерпан
        plan_revision_count=1,   # пользователь доработал один раз
        max_replans=2,
        max_plan_revisions=5,
    )
    assert route_after_plan_approval(state) == "replan"


def test_revisions_cap_hits_end():
    """Когда пользовательских доработок исчерпано — END."""
    state = _state(
        plan_decision="rejected",
        plan_revision_count=5,
        max_plan_revisions=5,
    )
    assert route_after_plan_approval(state) == "end"


def test_budget_replan_still_uses_own_counter():
    """Бюджетный цикл не сломан разделением: over_budget → replan."""
    state = _state(
        budget_report={"status": "over_budget"},
        replan_count=0,
        max_replans=2,
    )
    assert route_after_budget(state) == "replan"


def test_budget_replan_caps_at_max_replans():
    """Бюджетный счётчик исчерпан — выходим из цикла."""
    state = _state(
        budget_report={"status": "over_budget"},
        replan_count=2,
        max_replans=2,
    )
    assert route_after_budget(state) == "end"


# --------------------------------------------------------------------------- #
# replan — разделение счётчиков и обновление request
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_replan_user_rejection_increments_revision_only():
    """
    Пользовательский reject:
    - plan_revision_count += 1
    - replan_count не трогаем
    - request обновляется по комментарию
    - plan_decision/plan_comment сбрасываются
    """
    state = _state(
        plan_decision="rejected",
        plan_comment="Сделай 9 дней",
        plan_revision_count=1,
        replan_count=1,
        request={"duration_days": 7, "interests": ["архитектура"]},
        plan={"markdown": "# old plan"},
    )

    with patch(
        "app.nodes.plan._regenerate_markdown",
        new=AsyncMock(return_value="# new plan, 9 days"),
    ), patch(
        "app.nodes.plan._extract_costs",
        new=AsyncMock(return_value=(
            {"hotels": 0.0, "activities": 0.0, "transport": 10.0, "food": 100.0},
            "EUR",
            "estimated",
        )),
    ), patch(
        "app.nodes.plan._apply_comment_to_request",
        new=AsyncMock(return_value={"duration_days": 9}),
    ):
        result = await replan(state)

    assert result["plan_revision_count"] == 2, "user-revision должен +1"
    assert "replan_count" not in result, "budget-счётчик не трогаем"
    assert result["request"]["duration_days"] == 9, "request обновлён"
    assert result["plan_decision"] is None, "флаг сброшен"
    assert result["plan_comment"] is None, "комментарий сброшен"


@pytest.mark.asyncio
async def test_replan_budget_increments_replan_only():
    """
    Автоматический replan по бюджету:
    - replan_count += 1
    - plan_revision_count не трогаем
    - request НЕ меняется
    - plan_decision/plan_comment не появляются в ответе
    """
    state = _state(
        plan_decision=None,
        plan_comment=None,
        plan_revision_count=0,
        replan_count=0,
        request={"duration_days": 7, "budget": 500.0, "currency": "EUR"},
        plan={"markdown": "# old"},
        budget_report={"status": "over_budget", "over_by": 200.0, "limit": 500.0},
    )

    with patch(
        "app.nodes.plan._regenerate_markdown",
        new=AsyncMock(return_value="# cheaper plan"),
    ), patch(
        "app.nodes.plan._extract_costs",
        new=AsyncMock(return_value=(
            {"hotels": 0.0, "activities": 0.0, "transport": 10.0, "food": 90.0},
            "EUR",
            "estimated",
        )),
    ):
        result = await replan(state)

    assert result["replan_count"] == 1, "budget-счётчик +1"
    assert "plan_revision_count" not in result, "user-счётчик не трогаем"
    assert "request" not in result, "request не меняется при budget-replan"


# --------------------------------------------------------------------------- #
# _make_plan — три отдельные причины costs_valid=False
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_currency_mismatch_has_specific_error():
    """USD-бюджет при EUR-плане даёт actionable сообщение."""
    state = _state(
        request={"budget": 500.0, "currency": "USD"},
        plan=None,
    )
    with patch(
        "app.nodes.plan._generate_markdown",
        new=AsyncMock(return_value="# plan in EUR"),
    ), patch(
        "app.nodes.plan._extract_costs",
        new=AsyncMock(return_value=(
            {"hotels": 0.0, "activities": 0.0, "transport": 10.0, "food": 100.0},
            "EUR",
            "estimated",
        )),
    ):
        result = await _make_plan(state, is_replan=False)

    plan = result["plan"]
    assert plan["costs_valid"] is False
    assert "USD" in plan["costs_error"]
    assert "EUR" in plan["costs_error"]


@pytest.mark.asyncio
async def test_mixed_currency_has_specific_error():
    """MIXED-валюта даёт отдельное сообщение."""
    state = _state(
        request={"budget": 500.0, "currency": "EUR"},
        plan=None,
    )
    with patch(
        "app.nodes.plan._generate_markdown",
        new=AsyncMock(return_value="# mixed plan"),
    ), patch(
        "app.nodes.plan._extract_costs",
        new=AsyncMock(return_value=(
            {"hotels": 0.0, "activities": 0.0, "transport": 10.0, "food": 100.0},
            "MIXED",
            "estimated",
        )),
    ):
        result = await _make_plan(state, is_replan=False)

    plan = result["plan"]
    assert plan["costs_valid"] is False
    assert "смешаны" in plan["costs_error"].lower()


@pytest.mark.asyncio
async def test_unknown_confidence_has_specific_error():
    """confidence=unknown даёт отдельное сообщение."""
    state = _state(
        request={"budget": 500.0, "currency": "EUR"},
        plan=None,
    )
    with patch(
        "app.nodes.plan._generate_markdown",
        new=AsyncMock(return_value="# plan"),
    ), patch(
        "app.nodes.plan._extract_costs",
        new=AsyncMock(return_value=(
            {"hotels": 0.0, "activities": 0.0, "transport": 10.0, "food": 100.0},
            "EUR",
            "unknown",
        )),
    ):
        result = await _make_plan(state, is_replan=False)

    plan = result["plan"]
    assert plan["costs_valid"] is False
    assert "unknown" in plan["costs_error"]