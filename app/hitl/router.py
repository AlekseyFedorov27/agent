import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.dependencies import get_runtime
from app.agent.runtime import AgentRuntimeService, _serialize_messages
from app.agent.schemas import RunResponse
from app.auth.dependencies import CurrentUser
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.hitl import service
from app.hitl.schemas import ApprovalDecision, ApprovalOut
from app.runs import service as runs_service
from app.runs.models import EventType, RunStatus

router = APIRouter(prefix="/approvals", tags=["hitl"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Runtime = Annotated[AgentRuntimeService, Depends(get_runtime)]


@router.get("", response_model=list[ApprovalOut])
async def list_pending_approvals(
    user: CurrentUser, session: DbSession
) -> list[ApprovalOut]:
    approvals = await service.list_pending(session, user.id)
    return [ApprovalOut.model_validate(a) for a in approvals]


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(
    approval_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> ApprovalOut:
    approval = await service.get_approval(session, approval_id)
    if approval is None or approval.user_id != user.id:
        raise NotFoundError("Approval not found")
    return ApprovalOut.model_validate(approval)


@router.post("/{approval_id}/decide", response_model=RunResponse)
async def decide_approval(
    approval_id: uuid.UUID,
    data: ApprovalDecision,
    user: CurrentUser,
    session: DbSession,
    runtime: Runtime,
) -> RunResponse:
    approval = await service.get_approval(session, approval_id)
    if approval is None or approval.user_id != user.id:
        raise NotFoundError("Approval not found")

    approval = await service.decide(
        session, approval, approved=data.approved, comment=data.comment
    )

    result = await runtime.resume_run(
        approval.thread_id,
        {"approved": data.approved, "comment": data.comment},
    )

    state = await runtime.get_state(approval.thread_id)
    next_nodes = list(state.next) if state.next else []
    messages = result.get("messages", [])

    # Синхронизируем связанный Run, если он есть
    run_id = approval.run_id
    if run_id is not None:
        run = await runs_service.get_run(session, run_id)
        if run is not None:
            await runs_service.update_status(
                session, run,
                RunStatus.INTERRUPTED if next_nodes else RunStatus.COMPLETED,
            )
            await runs_service.add_event(
                session, run_id=run_id, type=EventType.RESUME,
                payload={
                    "approved": data.approved,
                    "comment": data.comment,
                    "next": next_nodes,
                },
            )

    pending_id: uuid.UUID | None = None
    if next_nodes:
        pending_id = await service.sync_pending_interrupts(
            session, runtime,
            thread_id=approval.thread_id, user_id=user.id, run_id=run_id,
        )

    return RunResponse(
        run_id=run_id,
        thread_id=approval.thread_id,
        status="interrupted" if next_nodes else "completed",
        messages=_serialize_messages(messages),
        pending_approval_id=pending_id,
    )