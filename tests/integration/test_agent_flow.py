"""Integration-тесты: полный HITL-цикл через HTTP endpoints."""

import pytest
from httpx import AsyncClient
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.hitl.models import ApprovalStatus
from app.runs.models import EventType, RunStatus
from tests.conftest import make_tool_call


# ===========================================================================
# Run без tool_calls — простой ответ
# ===========================================================================

class TestRunSimple:
    async def test_simple_response(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        patch_llm([AIMessage(content="Привет!")])

        r = await authenticated_client.post(
            "/agent/run", json={"message": "Привет!"}
        )
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["status"] == "completed"
        assert body["run_id"] is not None
        assert body["pending_approval_id"] is None
        assert len(body["messages"]) == 2
        assert body["messages"][0]["type"] == "human"
        assert body["messages"][0]["content"] == "Привет!"
        assert body["messages"][1]["type"] == "ai"
        assert body["messages"][1]["content"] == "Привет!"

    async def test_run_requires_auth(self, client: AsyncClient) -> None:
        r = await client.post("/agent/run", json={"message": "Привет!"})
        assert r.status_code == 401

    async def test_empty_message_rejected(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        patch_llm([AIMessage(content="x")])
        r = await authenticated_client.post("/agent/run", json={"message": ""})
        assert r.status_code == 422  # Pydantic validation


# ===========================================================================
# Run с tool_calls → interrupt → approve
# ===========================================================================

class TestToolApprovalFlow:
    async def test_tool_call_interrupts(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        patch_llm([
            AIMessage(
                content="",
                tool_calls=[make_tool_call("calculator", {"expression": "2 + 2"})],
            ),
        ])

        r = await authenticated_client.post(
            "/agent/run", json={"message": "Посчитай 2 + 2"}
        )
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["status"] == "interrupted"
        assert body["pending_approval_id"] is not None
        assert len(body["messages"]) == 2  # human + ai(tool_calls)
        assert body["messages"][1]["tool_calls"] is not None

    async def test_approval_creates_record(
        self,
        patch_llm,
        authenticated_client: AsyncClient,
        test_session: AsyncSession,
    ) -> None:
        patch_llm([
            AIMessage(
                content="",
                tool_calls=[make_tool_call("calculator", {"expression": "2 + 2"})],
            ),
        ])

        r = await authenticated_client.post(
            "/agent/run", json={"message": "Посчитай 2 + 2"}
        )
        approval_id = r.json()["pending_approval_id"]

        # Список pending
        r = await authenticated_client.get("/approvals")
        assert r.status_code == 200
        approvals = r.json()
        assert len(approvals) == 1
        assert approvals[0]["id"] == approval_id
        assert approvals[0]["status"] == ApprovalStatus.PENDING
        assert approvals[0]["payload"]["type"] == "tool_approval"

    async def test_approve_executes_tool(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        patch_llm([
            AIMessage(
                content="",
                tool_calls=[make_tool_call("calculator", {"expression": "2 + 2"})],
            ),
            AIMessage(content="4"),
        ])

        # 1. Запуск → interrupt
        r = await authenticated_client.post(
            "/agent/run", json={"message": "Посчитай 2 + 2"}
        )
        assert r.status_code == 200
        body = r.json()
        approval_id = body["pending_approval_id"]
        run_id = body["run_id"]

        # 2. Одобряем
        r = await authenticated_client.post(
            f"/approvals/{approval_id}/decide",
            json={"approved": True, "comment": "ok"},
        )
        assert r.status_code == 200, r.text
        result = r.json()

        assert result["status"] == "completed"
        assert result["run_id"] == run_id
        assert result["pending_approval_id"] is None

        types = [m["type"] for m in result["messages"]]
        assert types == ["human", "ai", "tool", "ai"]

        # tool вернул результат
        assert result["messages"][2]["content"] == "4"
        # финальный ответ LLM
        assert result["messages"][3]["content"] == "4"

    async def test_reject_skips_tool(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        patch_llm([
            AIMessage(
                content="",
                tool_calls=[make_tool_call("calculator", {"expression": "2 + 2"})],
            ),
            AIMessage(content="Хорошо, не считаю."),
        ])

        r = await authenticated_client.post(
            "/agent/run", json={"message": "Посчитай 2 + 2"}
        )
        approval_id = r.json()["pending_approval_id"]

        r = await authenticated_client.post(
            f"/approvals/{approval_id}/decide",
            json={"approved": False, "comment": "не надо"},
        )
        assert r.status_code == 200, r.text
        result = r.json()

        assert result["status"] == "completed"
        types = [m["type"] for m in result["messages"]]
        assert types == ["human", "ai", "tool", "ai"]
        # ToolMessage содержит сообщение об отказе
        assert "отклонил" in result["messages"][2]["content"]

    async def test_decide_twice_conflicts(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        patch_llm([
            AIMessage(
                content="",
                tool_calls=[make_tool_call("calculator", {"expression": "2 + 2"})],
            ),
            AIMessage(content="4"),
        ])

        r = await authenticated_client.post(
            "/agent/run", json={"message": "Посчитай 2 + 2"}
        )
        approval_id = r.json()["pending_approval_id"]

        r1 = await authenticated_client.post(
            f"/approvals/{approval_id}/decide", json={"approved": True}
        )
        assert r1.status_code == 200

        r2 = await authenticated_client.post(
            f"/approvals/{approval_id}/decide", json={"approved": False}
        )
        assert r2.status_code == 409  # ConflictError

    async def test_approval_of_other_user_returns_404(
        self,
        patch_llm,
        authenticated_client: AsyncClient,
        client: AsyncClient,
    ) -> None:
        patch_llm([
            AIMessage(
                content="",
                tool_calls=[make_tool_call("calculator", {"expression": "2 + 2"})],
            ),
        ])
        r = await authenticated_client.post(
            "/agent/run", json={"message": "Посчитай 2 + 2"}
        )
        approval_id = r.json()["pending_approval_id"]

        r = await client.post(
            "/auth/register",
            json={"email": "other@test.com", "password": "password123", "name": "Other User"},
        )
        assert r.status_code == 201, f"register failed: {r.status_code} {r.text}"

        r = await client.post(
            "/auth/login",
            json={"email": "other@test.com", "password": "password123", "name": "Other User"},
        )
        assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
        other_token = r.json()["access_token"]

        r = await client.post(
            f"/approvals/{approval_id}/decide",
            json={"approved": True},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert r.status_code == 404


# ===========================================================================
# Runs и Events
# ===========================================================================

class TestRunsEndpoints:
    async def test_run_appears_in_list(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        patch_llm([AIMessage(content="ok")])
        r = await authenticated_client.post("/agent/run", json={"message": "hi"})
        run_id = r.json()["run_id"]

        r = await authenticated_client.get("/runs")
        assert r.status_code == 200
        runs = r.json()
        assert len(runs) == 1
        assert runs[0]["id"] == run_id
        assert runs[0]["status"] == RunStatus.COMPLETED

    async def test_interrupted_run_listed_with_status(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        patch_llm([
            AIMessage(
                content="",
                tool_calls=[make_tool_call("calculator", {"expression": "1+1"})],
            ),
        ])
        r = await authenticated_client.post("/agent/run", json={"message": "1+1"})
        run_id = r.json()["run_id"]

        r = await authenticated_client.get("/runs?status=interrupted")
        assert r.status_code == 200
        runs = r.json()
        assert any(x["id"] == run_id for x in runs)

        r = await authenticated_client.get("/runs?status=completed")
        runs = r.json()
        assert not any(x["id"] == run_id for x in runs)

    async def test_run_events_include_interrupt(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        patch_llm([
            AIMessage(
                content="",
                tool_calls=[make_tool_call("calculator", {"expression": "1+1"})],
            ),
        ])
        r = await authenticated_client.post("/agent/run", json={"message": "1+1"})
        run_id = r.json()["run_id"]

        r = await authenticated_client.get(f"/runs/{run_id}/events")
        assert r.status_code == 200
        events = r.json()
        types = [e["type"] for e in events]

        # В SSE-stream мы видим только llm_end + interrupt, но их достаточно
        assert EventType.INTERRUPT in types

    async def test_run_of_other_user_404(
        self,
        patch_llm,
        authenticated_client: AsyncClient,
        client: AsyncClient,
    ) -> None:
        patch_llm([AIMessage(content="ok")])
        r = await authenticated_client.post("/agent/run", json={"message": "hi"})
        run_id = r.json()["run_id"]

        await client.post(
            "/auth/register",
            json={"email": "other@test.com", "password": "password123", "name": "Other User"},
        )
        r = await client.post(
            "/auth/login",
            json={"email": "other@test.com", "password": "password123", "name": "Other User"},
        )
        other_token = r.json()["access_token"]

        r = await client.get(
            f"/runs/{run_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert r.status_code == 404


# ===========================================================================
# Threads isolation
# ===========================================================================

class TestThreadIsolation:
    async def test_different_threads_dont_share_context(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        fake = patch_llm([
            AIMessage(content="first"),
            AIMessage(content="second"),
        ])

        r1 = await authenticated_client.post("/agent/run", json={"message": "hi 1"})
        r2 = await authenticated_client.post("/agent/run", json={"message": "hi 2"})

        assert r1.json()["thread_id"] != r2.json()["thread_id"]
        assert fake.call_count == 2
        # Второй вызов видел только SystemMessage + HumanMessage(hi 2)
        second_call_messages = fake.calls[1]
        human_msgs = [m for m in second_call_messages if m.type == "human"]
        assert len(human_msgs) == 1
        assert human_msgs[0].content == "hi 2"

    async def test_same_thread_keeps_history(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        fake = patch_llm([
            AIMessage(content="first"),
            AIMessage(content="second"),
        ])

        r1 = await authenticated_client.post("/agent/run", json={"message": "hi 1"})
        tid = r1.json()["thread_id"]

        r2 = await authenticated_client.post(
            "/agent/run", json={"message": "hi 2", "thread_id": tid}
        )
        assert r2.status_code == 200
        assert r2.json()["thread_id"] == tid

        # Второй вызов llm_node видел историю первого
        second_call_messages = fake.calls[1]
        human_msgs = [m for m in second_call_messages if m.type == "human"]
        assert len(human_msgs) == 2
        assert [m.content for m in human_msgs] == ["hi 1", "hi 2"]