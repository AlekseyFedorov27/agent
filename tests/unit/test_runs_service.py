"""Unit-тесты для app.runs.service."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import register_user
from app.runs import service
from app.runs.models import EventType, RunStatus


class TestCreateRun:
    async def test_create_run(self, test_session: AsyncSession) -> None:
        user = await register_user(test_session, "run@test.com", "password123")
        run = await service.create_run(
            test_session,
            user_id=user.id,
            thread_id="t-1",
            input_payload={"message": "hi"},
        )
        assert run.id is not None
        assert run.user_id == user.id
        assert run.thread_id == "t-1"
        assert run.status == RunStatus.RUNNING
        assert run.input == {"message": "hi"}
        assert run.completed_at is None


class TestUpdateStatus:
    async def test_update_to_completed_sets_timestamp(
        self, test_session: AsyncSession
    ) -> None:
        user = await register_user(test_session, "u@test.com", "password123")
        run = await service.create_run(
            test_session, user_id=user.id, thread_id="t", input_payload={}
        )

        run = await service.update_status(test_session, run, RunStatus.COMPLETED)
        assert run.status == RunStatus.COMPLETED
        assert run.completed_at is not None

    async def test_update_to_interrupted_no_timestamp(
        self, test_session: AsyncSession
    ) -> None:
        user = await register_user(test_session, "u@test.com", "password123")
        run = await service.create_run(
            test_session, user_id=user.id, thread_id="t", input_payload={}
        )

        run = await service.update_status(test_session, run, RunStatus.INTERRUPTED)
        assert run.status == RunStatus.INTERRUPTED
        assert run.completed_at is None


class TestEvents:
    async def test_add_event(self, test_session: AsyncSession) -> None:
        user = await register_user(test_session, "e@test.com", "password123")
        run = await service.create_run(
            test_session, user_id=user.id, thread_id="t", input_payload={}
        )

        event = await service.add_event(
            test_session,
            run_id=run.id,
            type=EventType.LLM_END,
            payload={"node": "llm"},
        )
        assert event.id is not None
        assert event.run_id == run.id
        assert event.type == EventType.LLM_END
        assert event.payload == {"node": "llm"}

    async def test_list_events_in_order(self, test_session: AsyncSession) -> None:
        user = await register_user(test_session, "e@test.com", "password123")
        run = await service.create_run(
            test_session, user_id=user.id, thread_id="t", input_payload={}
        )

        for etype in [EventType.LLM_END, EventType.INTERRUPT, EventType.RESUME]:
            await service.add_event(
                test_session, run_id=run.id, type=etype, payload={}
            )

        events = await service.list_events(test_session, run.id)
        assert [e.type for e in events] == [
            EventType.LLM_END,
            EventType.INTERRUPT,
            EventType.RESUME,
        ]


class TestListRuns:
    async def test_list_only_user_runs(self, test_session: AsyncSession) -> None:
        user1 = await register_user(test_session, "u1@test.com", "password123")
        user2 = await register_user(test_session, "u2@test.com", "password123")

        await service.create_run(
            test_session, user_id=user1.id, thread_id="t1", input_payload={}
        )
        await service.create_run(
            test_session, user_id=user2.id, thread_id="t2", input_payload={}
        )

        runs1 = await service.list_runs(test_session, user1.id)
        assert len(runs1) == 1
        assert runs1[0].thread_id == "t1"

    async def test_filter_by_status(self, test_session: AsyncSession) -> None:
        user = await register_user(test_session, "u@test.com", "password123")

        r1 = await service.create_run(
            test_session, user_id=user.id, thread_id="t1", input_payload={}
        )
        r2 = await service.create_run(
            test_session, user_id=user.id, thread_id="t2", input_payload={}
        )
        await service.update_status(test_session, r1, RunStatus.COMPLETED)

        completed = await service.list_runs(
            test_session, user.id, status=RunStatus.COMPLETED
        )
        assert len(completed) == 1
        assert completed[0].id == r1.id

        running = await service.list_runs(
            test_session, user.id, status=RunStatus.RUNNING
        )
        assert len(running) == 1
        assert running[0].id == r2.id


class TestGetRun:
    async def test_get_existing(self, test_session: AsyncSession) -> None:
        user = await register_user(test_session, "g@test.com", "password123")
        created = await service.create_run(
            test_session, user_id=user.id, thread_id="t", input_payload={}
        )
        found = await service.get_run(test_session, created.id)
        assert found is not None
        assert found.id == created.id

    async def test_get_missing(self, test_session: AsyncSession) -> None:
        assert await service.get_run(test_session, uuid.uuid4()) is None