import uuid
from datetime import datetime, timezone
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.hitl.models import Approval
from app.runs.models import Event, Run, RunStatus
from app.core.exceptions import NotFoundError
from app.auth.models import User

async def create_run(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    thread_id: str,
    input_payload: dict[str, str],
) -> Run:
    run = Run(
        user_id=user_id,
        thread_id=thread_id,
        status=RunStatus.RUNNING,
        input=input_payload,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> Run | None:
    return await session.get(Run, run_id)


async def list_runs(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[Run]:
    stmt = select(Run).where(Run.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Run.status == status)
    stmt = stmt.order_by(Run.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_events(session: AsyncSession, run_id: uuid.UUID) -> list[Event]:
    stmt = (
        select(Event)
        .where(Event.run_id == run_id)
        .order_by(Event.created_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_status(session: AsyncSession, run: Run, status: str) -> Run:
    run.status = status
    if status in (RunStatus.COMPLETED, RunStatus.FAILED):
        run.completed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(run)
    return run


async def add_event(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    type: str,
    payload: dict[str, str],
) -> Event:
    event = Event(run_id=run_id, type=type, payload=payload)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def delete_thread(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    thread_id: str,
) -> int:
    """
    Удаляет все runs (events — cascade) и связанные approvals для thread_id.
    Возвращает количество удалённых runs.
    """
    # 1. Approvals — у них FK на runs с ondelete=SET NULL, поэтому
    #    при удалении runs они НЕ удалятся. Чистим вручную.
    await session.execute(
        delete(Approval).where(
            Approval.user_id == user_id,
            Approval.thread_id == thread_id,
        )
    )

    # 2. Runs — events удалятся каскадом (ondelete=CASCADE на FK).
    result = await session.execute(
        delete(Run).where(
            Run.user_id == user_id,
            Run.thread_id == thread_id,
        )
    )
    await session.commit()
    return result.rowcount or 0


async def assert_thread_owner(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    thread_id: str,
) -> None:
    """
    Проверяет, что thread_id принадлежит пользователю user_id.

    Защита от IDOR: клиент не должен читать/продолжать чужой диалог,
    даже зная thread_id. Бросаем NotFoundError (404), а не Forbidden (403) —
    чтобы не подтверждать существование чужого треда.
    """
    stmt = (
        select(Run.id)
        .where(Run.thread_id == thread_id, Run.user_id == user_id)
        .limit(1)
    )
    exists = await session.scalar(stmt)
    if exists is None:
        raise NotFoundError("Thread not found")


async def list_all_runs(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[tuple[Run, User]]:
    """
    Возвращает страницу runs вместе с владельцем.
    Сортировка — новые сверху.
    """
    stmt = (
        select(Run, User)
        .join(User, User.id == Run.user_id)
        .order_by(Run.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if user_id is not None:
        stmt = stmt.where(Run.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Run.status == status)

    result = await session.execute(stmt)
    return list(result.all())


async def count_all_runs(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    status: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(Run)
    if user_id is not None:
        stmt = stmt.where(Run.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Run.status == status)
    return int(await session.scalar(stmt) or 0)


async def get_run_with_user(
    session: AsyncSession,
    run_id: uuid.UUID,
) -> tuple[Run, User] | None:
    stmt = (
        select(Run, User)
        .join(User, User.id == Run.user_id)
        .where(Run.id == run_id)
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.first()


async def admin_delete_thread(
    session: AsyncSession,
    thread_id: str,
) -> int:
    """
    Удаляет все runs (events каскадом) и связанные approvals для thread_id,
    без привязки к конкретному user_id. Только для админа.
    """
    await session.execute(
        delete(Approval).where(Approval.thread_id == thread_id)
    )
    result = await session.execute(
        delete(Run).where(Run.thread_id == thread_id)
    )
    await session.commit()
    return result.rowcount or 0