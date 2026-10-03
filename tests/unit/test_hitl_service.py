"""Unit-тесты для app.hitl.service."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import register_user
from app.core.exceptions import ConflictError
from app.hitl import service
from app.hitl.models import ApprovalStatus


# ===========================================================================
# Фейковый runtime для sync_pending_interrupts
# ===========================================================================

class FakeState:
    def __init__(self, next_nodes: list[str], interrupts: list[dict]):
        self.next = next_nodes
        self.tasks = [
            SimpleNamespace(
                interrupts=[
                    SimpleNamespace(id=i["id"], value=i["value"]) for i in interrupts
                ]
            )
        ] if interrupts else []


class FakeRuntime:
    def __init__(self, state: FakeState):
        self._state = state

    async def get_state(self, thread_id: str) -> FakeState:
        return self._state

    def get_pending_interrupts(self, state: FakeState) -> list[dict]:
        result = []
        for task in (state.tasks or []):
            for intr in (task.interrupts or []):
                result.append({"id": intr.id, "value": intr.value})
        return result


# ===========================================================================
# create_pending / get_approval
# ===========================================================================

class TestCreatePending:
    async def test_create_pending(self, test_session: AsyncSession) -> None:
        user = await register_user(test_session, "a@test.com", "password123")
        approval = await service.create_pending(
            test_session,
            user_id=user.id,
            thread_id="t-1",
            interrupt_id="intr-1",
            payload={"type": "tool_approval", "tool_calls": []},
        )
        assert approval.id is not None
        assert approval.user_id == user.id
        assert approval.thread_id == "t-1"
        assert approval.status == ApprovalStatus.PENDING
        assert approval.run_id is None
        assert approval.decided_at is None

    async def test_create_pending_with_run_id(self, test_session: AsyncSession) -> None:
        from app.runs import service as runs_service

        user = await register_user(test_session, "a@test.com", "password123")
        run = await runs_service.create_run(
            test_session, user_id=user.id, thread_id="t", input_payload={}
        )

        approval = await service.create_pending(
            test_session,
            user_id=user.id,
            thread_id="t",
            interrupt_id="i",
            payload={},
            run_id=run.id,
        )
        assert approval.run_id == run.id


# ===========================================================================
# list_pending
# ===========================================================================

class TestListPending:
    async def test_list_pending_only_for_user(
        self, test_session: AsyncSession
    ) -> None:
        u1 = await register_user(test_session, "u1@test.com", "password123")
        u2 = await register_user(test_session, "u2@test.com", "password123")

        await service.create_pending(
            test_session, user_id=u1.id, thread_id="t1", interrupt_id="i1", payload={}
        )
        await service.create_pending(
            test_session, user_id=u2.id, thread_id="t2", interrupt_id="i2", payload={}
        )

        pending = await service.list_pending(test_session, u1.id)
        assert len(pending) == 1
        assert pending[0].thread_id == "t1"

    async def test_list_pending_excludes_decided(
        self, test_session: AsyncSession
    ) -> None:
        user = await register_user(test_session, "u@test.com", "password123")
        a1 = await service.create_pending(
            test_session, user_id=user.id, thread_id="t1", interrupt_id="i1", payload={}
        )
        await service.create_pending(
            test_session, user_id=user.id, thread_id="t2", interrupt_id="i2", payload={}
        )

        await service.decide(test_session, a1, approved=True, comment=None)

        pending = await service.list_pending(test_session, user.id)
        assert len(pending) == 1
        assert pending[0].thread_id == "t2"


# ===========================================================================
# decide
# ===========================================================================

class TestDecide:
    async def test_decide_approve(self, test_session: AsyncSession) -> None:
        user = await register_user(test_session, "u@test.com", "password123")
        approval = await service.create_pending(
            test_session, user_id=user.id, thread_id="t", interrupt_id="i", payload={}
        )

        decided = await service.decide(
            test_session, approval, approved=True, comment="looks good"
        )
        assert decided.status == ApprovalStatus.APPROVED
        assert decided.comment == "looks good"
        assert decided.decided_at is not None

    async def test_decide_reject(self, test_session: AsyncSession) -> None:
        user = await register_user(test_session, "u@test.com", "password123")
        approval = await service.create_pending(
            test_session, user_id=user.id, thread_id="t", interrupt_id="i", payload={}
        )

        decided = await service.decide(
            test_session, approval, approved=False, comment="nope"
        )
        assert decided.status == ApprovalStatus.REJECTED

    async def test_decide_twice_raises_conflict(
        self, test_session: AsyncSession
    ) -> None:
        user = await register_user(test_session, "u@test.com", "password123")
        approval = await service.create_pending(
            test_session, user_id=user.id, thread_id="t", interrupt_id="i", payload={}
        )
        await service.decide(test_session, approval, approved=True, comment=None)

        with pytest.raises(ConflictError):
            await service.decide(test_session, approval, approved=False, comment=None)


# ===========================================================================
# sync_pending_interrupts
# ===========================================================================

class TestSyncPendingInterrupts:
    async def test_no_interrupts_returns_none(
        self, test_session: AsyncSession
    ) -> None:
        user = await register_user(test_session, "u@test.com", "password123")
        runtime = FakeRuntime(FakeState(next_nodes=[], interrupts=[]))

        result = await service.sync_pending_interrupts(
            test_session, runtime, thread_id="t", user_id=user.id
        )
        assert result is None

    async def test_creates_approval_for_interrupt(
        self, test_session: AsyncSession
    ) -> None:
        user = await register_user(test_session, "u@test.com", "password123")
        runtime = FakeRuntime(
            FakeState(
                next_nodes=["approval"],
                interrupts=[
                    {
                        "id": "intr-1",
                        "value": {
                            "type": "tool_approval",
                            "tool_calls": [{"name": "calculator", "args": {}}],
                        },
                    }
                ],
            )
        )

        approval_id = await service.sync_pending_interrupts(
            test_session, runtime, thread_id="t-1", user_id=user.id
        )
        assert approval_id is not None

        approval = await service.get_approval(test_session, approval_id)
        assert approval is not None
        assert approval.thread_id == "t-1"
        assert approval.interrupt_id == "intr-1"
        assert approval.payload["type"] == "tool_approval"

    async def test_attaches_run_id(self, test_session: AsyncSession) -> None:
        from app.runs import service as runs_service

        user = await register_user(test_session, "u@test.com", "password123")
        run = await runs_service.create_run(
            test_session, user_id=user.id, thread_id="t", input_payload={}
        )
        runtime = FakeRuntime(
            FakeState(
                next_nodes=["approval"],
                interrupts=[{"id": "i", "value": {"type": "x"}}],
            )
        )

        approval_id = await service.sync_pending_interrupts(
            test_session, runtime, thread_id="t", user_id=user.id, run_id=run.id
        )
        approval = await service.get_approval(test_session, approval_id)
        assert approval.run_id == run.id