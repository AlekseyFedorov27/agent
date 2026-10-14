"""End-to-end тесты агента через текст в чате.

Каждый тест — реальный сценарий:
- пользователь пишет сообщение в /agent/run;
- граф triage → research → plan → budget_check → plan_approval проходит
  с мокнутой LLM и мокнутым RAG;
- проверяем, что агент вернул ожидаемый status и pending_approval_id;
- если нужно — реагируем на approval через /approvals/{id}/decide
  и проверяем финальное состояние.

Ни Ollama, ни реальная LLM не вызываются.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.nodes.plan import CostExtract, RequestPatch
from app.nodes.triage import Triage
from app.runs.models import RunStatus


pytestmark = pytest.mark.integration


PLAN_MD = (
    "# Маршрут: Барселона, {days} дней\n\n"
    "## День 1\nПрогулка по Готическому кварталу.\n\n"
    "## Жильё\nХостел в Эшампле.\n\n"
    "<!-- BUDGET -->\n"
)


def _triage_7_days(budget: float | None = 500, currency: str = "EUR") -> Triage:
    return Triage(
        destination="Барселона",
        country="Испания",
        duration_days=7,
        month="май",
        currency=currency,
        budget=budget,
        interests=["архитектура"],
        travel_type="couple",
    )


async def _get_run(session: AsyncSession, run_id: str):
    from app.runs.service import get_run

    import uuid as _uuid
    return await get_run(session, _uuid.UUID(run_id))


# --------------------------------------------------------------------------- #
# A. Сценарий без бюджета → plan_approval → approve → END
# --------------------------------------------------------------------------- #

async def test_chat_no_budget_approve(
    patch_llm, patch_rag, authenticated_client: AsyncClient,
):
    patch_rag()
    patch_llm([
        _triage_7_days(budget=None),
        AIMessage(content=PLAN_MD.format(days=7)),
        # budget=None → extract_costs не вызывается
    ])

    r = await authenticated_client.post(
        "/agent/run",
        json={"message": "Хочу в Барселону в мае на 7 дней, люблю архитектуру"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "interrupted"
    assert body["pending_approval_id"] is not None

    approval_id = body["pending_approval_id"]

    r = await authenticated_client.post(
        f"/approvals/{approval_id}/decide",
        json={"approved": True, "comment": None},
    )
    assert r.status_code == 200, r.text
    final = r.json()
    assert final["status"] == "completed"
    assert final["pending_approval_id"] is None


# --------------------------------------------------------------------------- #
# B. Бюджет задан, план в пределах → plan_approval → approve → END
# --------------------------------------------------------------------------- #

async def test_chat_budget_fits_approve(
    patch_llm, patch_rag, authenticated_client: AsyncClient,
):
    patch_rag()
    patch_llm([
        _triage_7_days(budget=800),
        AIMessage(content=PLAN_MD.format(days=7)),
        CostExtract(
            hotels=300, activities=50, transport=30, food=200,
            currency="EUR", confidence="estimated",
        ),
    ])

    r = await authenticated_client.post(
        "/agent/run",
        json={"message": "Барселона, 7 дней, май, 800 € на двоих"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "interrupted"

    r = await authenticated_client.post(
        f"/approvals/{body['pending_approval_id']}/decide",
        json={"approved": True},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


# --------------------------------------------------------------------------- #
# C. Бюджет маленький → auto-replan по бюджету → plan_approval
# --------------------------------------------------------------------------- #

async def test_chat_budget_over_triggers_auto_replan(
    patch_llm, patch_rag, authenticated_client: AsyncClient, session: AsyncSession,
):
    """500 € мало → over_budget → replan → новый план → plan_approval."""
    patch_rag()
    patch_llm([
        _triage_7_days(budget=500),
        AIMessage(content=PLAN_MD.format(days=7)),   # первый план
        CostExtract(hotels=400, activities=100, transport=50, food=300,
                    currency="EUR", confidence="estimated"),   # 850 € > 500 €
        AIMessage(content=PLAN_MD.format(days=7)),   # replan
        CostExtract(hotels=0, activities=0, transport=30, food=200,
                    currency="EUR", confidence="estimated"),   # 230 € < 500 €
    ])

    r = await authenticated_client.post(
        "/agent/run",
        json={"message": "Барселона, 7 дней, май, 500 € на двоих"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "interrupted"
    assert body["pending_approval_id"] is not None

    run = await _get_run(session, body["run_id"])
    assert run is not None
    assert run.status == RunStatus.INTERRUPTED


# --------------------------------------------------------------------------- #
# D. Reject с комментарием → replan → новый plan_approval → approve
# --------------------------------------------------------------------------- #

async def test_chat_reject_with_comment_then_approve(
    patch_llm, patch_rag, authenticated_client: AsyncClient,
):
    patch_rag()
    patch_llm([
        # --- первый проход ---
        _triage_7_days(budget=800),
        AIMessage(content=PLAN_MD.format(days=7)),
        CostExtract(hotels=300, activities=50, transport=30, food=200,
                    currency="EUR", confidence="estimated"),
        # --- после reject: извлекаем патч из комментария и пересобираем план ---
        RequestPatch(duration_days=9, interests=["архитектура", "рестораны"]),
        AIMessage(content=PLAN_MD.format(days=9)),
        CostExtract(hotels=300, activities=50, transport=30, food=400,
                    currency="EUR", confidence="estimated"),
    ])

    r = await authenticated_client.post(
        "/agent/run",
        json={"message": "Барселона, 7 дней, май, 800 €"},
    )
    assert r.status_code == 200
    first_approval = r.json()["pending_approval_id"]
    assert first_approval is not None

    r = await authenticated_client.post(
        f"/approvals/{first_approval}/decide",
        json={"approved": False, "comment": "Сделай 9 дней, добавь рестораны"},
    )
    assert r.status_code == 200, r.text
    after_reject = r.json()
    assert after_reject["status"] == "interrupted"
    assert after_reject["pending_approval_id"] is not None
    assert after_reject["pending_approval_id"] != first_approval

    # Approve второй план
    r = await authenticated_client.post(
        f"/approvals/{after_reject['pending_approval_id']}/decide",
        json={"approved": True},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


# --------------------------------------------------------------------------- #
# E. Два reject подряд — регрессия по счётчикам
# --------------------------------------------------------------------------- #

async def test_chat_two_rejects_do_not_finish_silently(
    patch_llm, patch_rag, authenticated_client: AsyncClient,
):
    """
    Раньше второй reject уходил в END из-за общего счётчика с бюджетным
    циклом. Теперь должен пересчитываться и снова давать plan_approval.
    """
    patch_rag()
    patch_llm([
        # 1) triage + plan + costs (в бюджете → без auto-replan)
        _triage_7_days(budget=800),
        AIMessage(content=PLAN_MD.format(days=7)),
        CostExtract(hotels=300, activities=50, transport=30, food=200,
                    currency="EUR", confidence="estimated"),
        # 2) первый reject → replan
        RequestPatch(duration_days=9),
        AIMessage(content=PLAN_MD.format(days=9)),
        CostExtract(hotels=300, activities=50, transport=30, food=200,
                    currency="EUR", confidence="estimated"),
        # 3) второй reject → replan (раньше здесь был END)
        RequestPatch(duration_days=7),
        AIMessage(content=PLAN_MD.format(days=7)),
        CostExtract(hotels=300, activities=50, transport=30, food=200,
                    currency="EUR", confidence="estimated"),
    ])

    r = await authenticated_client.post("/agent/run", json={"message": "Барселона, 7 дней, 800 €"})
    assert r.status_code == 200
    a1 = r.json()["pending_approval_id"]

    r = await authenticated_client.post(
        f"/approvals/{a1}/decide",
        json={"approved": False, "comment": "Сделай 9 дней"},
    )
    body = r.json()
    assert body["status"] == "interrupted", (
        "первый reject должен приводить к новому plan_approval"
    )
    a2 = body["pending_approval_id"]

    r = await authenticated_client.post(
        f"/approvals/{a2}/decide",
        json={"approved": False, "comment": "Верни 7 дней"},
    )
    body = r.json()
    assert body["status"] == "interrupted", (
        "второй reject должен приводить к новому plan_approval, "
        "а не в END"
    )
    assert body["pending_approval_id"] is not None

    r = await authenticated_client.post(
        f"/approvals/{body['pending_approval_id']}/decide",
        json={"approved": True},
    )
    assert r.json()["status"] == "completed"


# --------------------------------------------------------------------------- #
# F. USD-бюджет → unverified → plan_approval всё равно приходит
# --------------------------------------------------------------------------- #

async def test_chat_usd_budget_mismatch(
    patch_llm, patch_rag, authenticated_client: AsyncClient, session: AsyncSession,
):
    patch_rag()
    patch_llm([
        _triage_7_days(budget=500, currency="USD"),
        AIMessage(content=PLAN_MD.format(days=7)),
        # extractor вернёт EUR — валюты не совпадают
        CostExtract(hotels=300, activities=50, transport=30, food=200,
                    currency="EUR", confidence="estimated"),
    ])

    r = await authenticated_client.post(
        "/agent/run",
        json={"message": "Барселона, 7 дней, 500 $ на двоих"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # граф не должен уходить в replan из-за unverified — сразу plan_approval
    assert body["status"] == "interrupted"
    assert body["pending_approval_id"] is not None

    run = await _get_run(session, body["run_id"])
    assert run is not None
    assert run.status == RunStatus.INTERRUPTED


# --------------------------------------------------------------------------- #
# G. Граф доходит до END только после approve
# --------------------------------------------------------------------------- #

async def test_chat_state_next_empty_after_approve(
    patch_llm, patch_rag, authenticated_client: AsyncClient,
):
    patch_rag()
    patch_llm([
        _triage_7_days(budget=800),
        AIMessage(content=PLAN_MD.format(days=7)),
        CostExtract(hotels=300, activities=50, transport=30, food=200,
                    currency="EUR", confidence="estimated"),
    ])

    r = await authenticated_client.post("/agent/run", json={"message": "Барселона, 7 дней, 800 €"})
    body = r.json()
    thread_id = body["thread_id"]
    approval_id = body["pending_approval_id"]

    # До approve — тред ждёт
    r = await authenticated_client.get(f"/agent/status/{thread_id}")
    assert r.status_code == 200
    assert "plan_approval" in r.json()["next_nodes"]

    # Approve
    await authenticated_client.post(
        f"/approvals/{approval_id}/decide",
        json={"approved": True},
    )

    # После approve — next_nodes пустой
    r = await authenticated_client.get(f"/agent/status/{thread_id}")
    assert r.status_code == 200
    assert r.json()["next_nodes"] == []