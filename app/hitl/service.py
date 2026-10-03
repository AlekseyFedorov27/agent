import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.hitl.models import Approval, ApprovalStatus


async def create_pending(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    thread_id: str,
    interrupt_id: str | None,
    payload: dict,
) -> Approval:
    approval = Approval(
        user_id=user_id,
        thread_id=thread_id,
        interrupt_id=interrupt_id,
        status=ApprovalStatus.PENDING,
        payload=payload,
    )
    session.add(approval)
    await session.commit()
    await session.refresh(approval)
    return approval


async def get_approval(
    session: AsyncSession, approval_id: uuid.UUID
) -> Approval | None:
    return await session.get(Approval, approval_id)


async def list_pending(
    session: AsyncSession, user_id: uuid.UUID
) -> list[Approval]:
    stmt = (
        select(Approval)
        .where(
            Approval.user_id == user_id,
            Approval.status == ApprovalStatus.PENDING,
        )
        .order_by(Approval.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def decide(
    session: AsyncSession,
    approval: Approval,
    *,
    approved: bool,
    comment: str | None,
) -> Approval:
    if approval.status != ApprovalStatus.PENDING:
        raise ConflictError("Approval already decided")

    approval.status = (
        ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    )
    approval.comment = comment
    approval.decided_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(approval)
    return approval


async def sync_pending_interrupts(
    session: AsyncSession,
    runtime,
    *,
    thread_id: str,
    user_id: uuid.UUID,
) -> uuid.UUID | None:
    """
    Проверяет state треда. Если есть активные interrupt'ы — создаёт
    Approval для каждого. Возвращает id последнего созданного Approval.
    """
    state = await runtime.get_state(thread_id)
    if not state.next:
        return None

    last_id: uuid.UUID | None = None
    for intr in runtime.get_pending_interrupts(state):
        approval = await create_pending(
            session,
            user_id=user_id,
            thread_id=thread_id,
            interrupt_id=intr.get("id"),
            payload=intr.get("value") or {},
        )
        last_id = approval.id
    return last_id


async def create_pending(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    thread_id: str,
    interrupt_id: str | None,
    payload: dict[str, str],
    run_id: uuid.UUID | None = None,
) -> Approval:
    approval = Approval(
        user_id=user_id,
        thread_id=thread_id,
        interrupt_id=interrupt_id,
        status=ApprovalStatus.PENDING,
        payload=payload,
        run_id=run_id,
    )
    session.add(approval)
    await session.commit()
    await session.refresh(approval)
    return approval


async def sync_pending_interrupts(
    session: AsyncSession,
    runtime,
    *,
    thread_id: str,
    user_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    state = await runtime.get_state(thread_id)
    if not state.next:
        return None

    last_id: uuid.UUID | None = None
    for intr in runtime.get_pending_interrupts(state):
        approval = await create_pending(
            session,
            user_id=user_id,
            thread_id=thread_id,
            interrupt_id=intr.get("id"),
            payload=intr.get("value") or {},
            run_id=run_id,
        )
        last_id = approval.id
    return last_id