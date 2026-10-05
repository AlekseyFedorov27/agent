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


async def _get_pending_by_interrupt(
    session: AsyncSession,
    *,
    thread_id: str,
    interrupt_id: str | None,
) -> Approval | None:
    if interrupt_id is None:
        return None
    stmt = (
        select(Approval)
        .where(
            Approval.thread_id == thread_id,
            Approval.interrupt_id == interrupt_id,
            Approval.status == ApprovalStatus.PENDING,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


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
        intr_id = intr.get("id")

        # Дедуп: если для этого interrupt_id уже есть pending — используем его
        existing = await _get_pending_by_interrupt(
            session, thread_id=thread_id, interrupt_id=intr_id,
        )
        if existing is not None:
            last_id = existing.id
            continue

        approval = await create_pending(
            session,
            user_id=user_id,
            thread_id=thread_id,
            interrupt_id=intr_id,
            payload=intr.get("value") or {},
            run_id=run_id,
        )
        last_id = approval.id
    return last_id


async def revert_decision(
    session: AsyncSession, approval: Approval
) -> Approval:
    """Откат решения — используется, если resume упал."""
    approval.status = ApprovalStatus.PENDING
    approval.decided_at = None
    approval.comment = None
    await session.commit()
    await session.refresh(approval)
    return approval