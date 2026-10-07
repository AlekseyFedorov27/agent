import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_superuser
from app.core.database import get_db
from fastapi import Response, status
from app.core.exceptions import NotFoundError
from app.runs import service
from app.agent.dependencies import get_runtime
from app.agent.runtime import AgentRuntimeService, _serialize_messages
from app.agent.schemas import MessageOut
from app.runs.schemas import (
    AdminRunDetailOut,
    AdminRunListOut,
    AdminRunOut,
    EventOut,
)

router = APIRouter(
    prefix="/admin/runs",
    tags=["admin"],
    dependencies=[Depends(require_superuser)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]
Runtime = Annotated[AgentRuntimeService, Depends(get_runtime)]

def _to_admin_run(run, user) -> AdminRunOut:
    return AdminRunOut(
        id=run.id,
        user_id=user.id,
        user_email=user.email,
        user_name=user.name,
        thread_id=run.thread_id,
        status=run.status,
        input=run.input,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.get("", response_model=AdminRunListOut)
async def list_runs(
    session: DbSession,
    user_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminRunListOut:
    rows = await service.list_all_runs(
        session,
        user_id=user_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    total = await service.count_all_runs(
        session, user_id=user_id, status=status,
    )
    return AdminRunListOut(
        items=[_to_admin_run(run, user) for run, user in rows],
        total=total,
    )


@router.get("/{run_id}", response_model=AdminRunDetailOut)
async def get_run_detail(
    run_id: uuid.UUID,
    session: DbSession,
) -> AdminRunDetailOut:
    row = await service.get_run_with_user(session, run_id)
    if row is None:
        raise NotFoundError("Run not found")
    run, user = row
    events = await service.list_events(session, run_id)

    base = _to_admin_run(run, user)
    return AdminRunDetailOut(
        **base.model_dump(),
        events=[EventOut.model_validate(e) for e in events],
    )





@router.get(
    "/threads/{thread_id}/messages",
    response_model=list[MessageOut],
)
async def get_thread_messages_admin(
    thread_id: str,
    runtime: Runtime,
) -> list[MessageOut]:
    """
    Показывает сообщения любого треда — только для админа.
    Читаем из LangGraph-чекпоинта, owner-check не делаем.
    """
    state = await runtime.get_state(thread_id)
    messages = state.values.get("messages", []) if state.values else []
    return _serialize_messages(messages)


@router.delete(
    "/threads/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_thread_admin(
    thread_id: str,
    session: DbSession,
    runtime: Runtime,
) -> Response:
    deleted = await service.admin_delete_thread(session, thread_id=thread_id)
    if deleted == 0:
        raise NotFoundError("Thread not found")

    # Чистим чекпоинты LangGraph — не критично, но приятно
    await runtime.delete_thread_checkpoints(thread_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)