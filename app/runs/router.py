import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.dependencies import get_runtime
from app.agent.runtime import AgentRuntimeService
from app.auth.dependencies import CurrentUser
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.runs import service
from app.runs.schemas import EventOut, RunOut

router = APIRouter(prefix="/runs", tags=["runs"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Runtime = Annotated[AgentRuntimeService, Depends(get_runtime)]


@router.get("", response_model=list[RunOut])
async def list_runs(
    user: CurrentUser,
    session: DbSession,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RunOut]:
    runs = await service.list_runs(session, user.id, status=status, limit=limit)
    return [RunOut.model_validate(r) for r in runs]


# ВАЖНО: этот маршрут объявлен ДО /{run_id}, иначе "threads" упадёт
# в парсер UUID и вернёт 422.
@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: str,
    user: CurrentUser,
    session: DbSession,
    runtime: Runtime,
) -> Response:
    deleted = await service.delete_thread(
        session, user_id=user.id, thread_id=thread_id
    )
    if deleted == 0:
        raise NotFoundError("Thread not found")

    # Чистим чекпоинты LangGraph (не критично, но приятно)
    await runtime.delete_thread_checkpoints(thread_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> RunOut:
    run = await service.get_run(session, run_id)
    if run is None or run.user_id != user.id:
        raise NotFoundError("Run not found")
    return RunOut.model_validate(run)


@router.get("/{run_id}/events", response_model=list[EventOut])
async def get_run_events(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> list[EventOut]:
    run = await service.get_run(session, run_id)
    if run is None or run.user_id != user.id:
        raise NotFoundError("Run not found")
    events = await service.list_events(session, run_id)
    return [EventOut.model_validate(e) for e in events]